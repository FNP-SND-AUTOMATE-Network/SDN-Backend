"""
ODL Mount Service
บริการ Mount/Unmount NETCONF Nodes ใน OpenDaylight Controller

หน้าที่หลัก:
- Mount: ลงทะเบียนอุปกรณ์ผ่าน NETCONF เข้า ODL Topology
- Unmount: ถอดอุปกรณ์ออกจาก ODL Topology
- Sync Status: ซิงค์สถานะการเชื่อมต่อ NETCONF จาก ODL ลง DB
- อัปเดต Database Status หลัง Mount/Unmount

Flow:
1. รับข้อมูล Device จาก Database (รวม NETCONF Credentials)
2. สร้าง Payload สำหรับ Mount
3. ส่งไปยัง ODL RESTCONF API
4. อัปเดต Status ใน Database
5. Sync Connection Status
"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import json
from app.clients.odl_restconf_client import OdlRestconfClient
from app.core.errors import OdlRequestError
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client
from app.services.phpipam_service import PhpipamService


# Map ODL connection status string to DB enum value
def map_odl_status_to_enum(odl_status: str) -> str:
    """
    Map ODL connection-status string to Prisma enum
    ODL returns: 'connected', 'connecting', 'unable-to-connect'
    DB enum: CONNECTED, CONNECTING, UNABLE_TO_CONNECT
    """
    mapping = {
        "connected": "CONNECTED",
        "connecting": "CONNECTING",
        "unable-to-connect": "UNABLE_TO_CONNECT",
        "not-mounted": "UNABLE_TO_CONNECT",
        "unknown": "UNABLE_TO_CONNECT",
    }
    return mapping.get(odl_status.lower(), "UNABLE_TO_CONNECT")


class OdlMountService:
    """
    Service สำหรับ Mount/Unmount NETCONF nodes ใน ODL
    
    หมายเหตุ: ทุก method รับ node_id เท่านั้น (เช่น "CSR1", "router-core-01")
    node_id เป็น unique field ใน Database และใช้ตรงกับ ODL
    """
    
    # ODL topology-netconf base path
    TOPOLOGY_PATH = "/network-topology:network-topology/topology=topology-netconf"
    
    def __init__(self):
        self.odl_client = OdlRestconfClient()
        self.phpipam_service = PhpipamService()
        # Per-device lock to prevent concurrent mount/unmount on the same device
        self._device_locks: Dict[str, asyncio.Lock] = {}
    
    def _get_device_lock(self, node_id: str) -> asyncio.Lock:
        """Get or create a per-device lock to serialize mount/unmount ops."""
        if node_id not in self._device_locks:
            self._device_locks[node_id] = asyncio.Lock()
        return self._device_locks[node_id]

    async def _find_device(self, node_id: str):
        """
        ค้นหา device จาก node_id (หรือ fallback ไป device_name)
        
        Args:
            node_id: ODL node-id (เช่น "CSR1") หรือ device_name
        
        Returns:
            DeviceNetwork object หรือ None
        """
        prisma = get_prisma_client()
        
        # 1. ลองหาจาก node_id ก่อน
        device = await prisma.devicenetwork.find_unique(
            where={"node_id": node_id}
        )
        
        # 2. ถ้าไม่เจอ ลองหาจาก device_name
        if not device:
            device = await prisma.devicenetwork.find_first(
                where={"device_name": node_id}
            )
        
        return device
    
    def _build_mount_payload(self, device, username: str, password: str) -> Dict[str, Any]:
        """
        สร้าง payload สำหรับ mount NETCONF node (ODL Potassium compatible)
        
        Args:
            device: DeviceNetwork object จาก DB
            username: ODL Netconf Username
            password: ODL Netconf Password (Plaintext)
        
        Returns:
            ODL mount payload with RFC-8040 compliant structure
        """
        profile = self._get_mount_profile(device)

        keepalive_delay = profile["keepalive_delay"]
        reconnect_on_changed_schema = profile["reconnect_on_changed_schema"]
        connection_timeout_ms = profile["connection_timeout_ms"]
        request_timeout_ms = profile["request_timeout_ms"]
        max_attempts = profile["max_attempts"]
        between_attempts_ms = profile["between_attempts_ms"]
        concurrent_rpc_limit = profile["concurrent_rpc_limit"]
        sleep_factor = profile["sleep_factor"]
        schemaless = profile["schemaless"]

        return {
            "network-topology:node": [
                {
                    "node-id": device.node_id,
                    "netconf-node-topology:host": device.netconf_host or device.ip_address,
                    "netconf-node-topology:port": getattr(device, 'netconf_port', 830) or 830,
                    "netconf-node-topology:username": username,
                    "netconf-node-topology:password": password,
                    "netconf-node-topology:tcp-only": False,
                    "netconf-node-topology:keepalive-delay": keepalive_delay,
                    "netconf-node-topology:connection-timeout-millis": connection_timeout_ms,
                    "netconf-node-topology:default-request-timeout-millis": request_timeout_ms,
                    "netconf-node-topology:max-connection-attempts": max_attempts,
                    "netconf-node-topology:between-attempts-timeout-millis": between_attempts_ms,
                    "netconf-node-topology:concurrent-rpc-limit": concurrent_rpc_limit,
                    "netconf-node-topology:sleep-factor": sleep_factor,
                    "netconf-node-topology:reconnect-on-changed-schema": reconnect_on_changed_schema,
                    "netconf-node-topology:schemaless": schemaless,
                    "netconf-node-topology:lock-datastore": False
                }
            ]
        }

    def _get_mount_profile(self, device: Any) -> Dict[str, Any]:
        """
        Return mount tuning profile by vendor/type.

        Profiles are intentionally explicit so we can reason about
        Cisco and Huawei behavior separately.
        """
        if self._is_cisco_device(device):
            profile = self._get_cisco_mount_profile()

            # CSR1000v is more sensitive during initial schema discovery.
            if self._is_csr1000v_device(device):
                profile.update(self._get_csr1000v_overrides())
            return profile

        if self._is_huawei_device(device):
            return self._get_huawei_mount_profile()

        return self._get_default_mount_profile()

    @staticmethod
    def _get_default_mount_profile() -> Dict[str, Any]:
        """Fallback profile for non-Cisco/non-Huawei devices."""
        return {
            "keepalive_delay": 30,
            "reconnect_on_changed_schema": True,
            "schemaless": False,
            "connection_timeout_ms": 180000,
            "request_timeout_ms": 600000,
            "max_attempts": 3,
            "between_attempts_ms": 8000,
            "concurrent_rpc_limit": 2,
            "sleep_factor": 1.5,
        }

    @staticmethod
    def _get_cisco_mount_profile() -> Dict[str, Any]:
        """Cisco baseline profile aligned with Huawei stability profile."""
        return {
            "keepalive_delay": 300,
            "reconnect_on_changed_schema": False,
            "schemaless": False,
            "connection_timeout_ms": 360000,
            "request_timeout_ms": 1200000,
            "max_attempts": 8,
            "between_attempts_ms": 30000,
            "concurrent_rpc_limit": 32,  # high enough for schema discovery, low enough to not flood SSH
            "sleep_factor": 2.5,
        }

    @staticmethod
    def _get_csr1000v_overrides() -> Dict[str, Any]:
        return {
            "keepalive_delay": 300,
            "schemaless": False,
            "connection_timeout_ms": 360000,
            "request_timeout_ms": 1200000,
            "max_attempts": 8,
            "between_attempts_ms": 30000,
            "concurrent_rpc_limit": 32,    
            "sleep_factor": 2.5,
        }

    @staticmethod
    def _get_huawei_mount_profile() -> Dict[str, Any]:
        """Huawei baseline profile."""
        return {
            "keepalive_delay": 300,
            "schemaless": False,
            "reconnect_on_changed_schema": False,
            "connection_timeout_ms": 360000,
            "request_timeout_ms": 1200000,
            "max_attempts": 8,
            "between_attempts_ms": 30000,
            "concurrent_rpc_limit": 32,  # high enough for schema discovery, low enough to not flood SSH
            "sleep_factor": 2.5,
        }

    @staticmethod
    def _is_cisco_device(device: Any) -> bool:
        """Best-effort Cisco detection from vendor / os_type fields."""
        vendor = str(getattr(device, "vendor", "") or "")
        os_type = str(getattr(device, "os_type", "") or "")
        operating_system = getattr(device, "operatingSystem", None)
        os_type_rel = str(getattr(operating_system, "os_type", "") or "")
        fingerprint = f"{vendor} {os_type} {os_type_rel}".upper()
        return "CISCO" in fingerprint

    @staticmethod
    def _is_huawei_device(device: Any) -> bool:
        """Best-effort Huawei detection from vendor / os_type fields."""
        vendor = str(getattr(device, "vendor", "") or "")
        os_type = str(getattr(device, "os_type", "") or "")
        operating_system = getattr(device, "operatingSystem", None)
        os_type_rel = str(getattr(operating_system, "os_type", "") or "")
        fingerprint = f"{vendor} {os_type} {os_type_rel}".upper()
        return "HUAWEI" in fingerprint

    @staticmethod
    def _is_csr1000v_device(device: Any) -> bool:
        """Best-effort CSR1000v detection from name/vendor/os fields."""
        vendor = str(getattr(device, "vendor", "") or "")
        os_type = str(getattr(device, "os_type", "") or "")
        device_name = str(getattr(device, "device_name", "") or "")
        node_id = str(getattr(device, "node_id", "") or "")
        fingerprint = f"{vendor} {os_type} {device_name} {node_id}".upper()
        return "CSR" in fingerprint or "CSR1000V" in fingerprint

    async def _delete_node_from_odl(self, node_id: str) -> bool:
        """
        DELETE node จาก ODL config datastore.
        Returns True ถ้าสำเร็จ (รวมถึงกรณีที่ node ถูกลบไปแล้ว)
        Raises exception เฉพาะ error ที่ไม่ใช่ "already absent".
        """
        node_path = f"{self.TOPOLOGY_PATH}/node={node_id}"
        spec = RequestSpec(
            method="DELETE",
            path=node_path,
            datastore="config",
            headers={"Accept": "application/yang-data+json"},
        )
        try:
            await self.odl_client.send(spec)
            return True
        except OdlRequestError as e:
            if e.status_code == 404:
                logger.info(f"Node {node_id} already absent from ODL config (404) — treating as success")
                return True

            # ODL may return 409/data-missing when config node is already absent
            # while operational state is still stale for a short time.
            if e.status_code == 409:
                details = getattr(e, "detail", {}) or {}
                body_text = ""
                if isinstance(details, dict):
                    nested = details.get("details", {})
                    if isinstance(nested, dict):
                        body_text = str(nested.get("body", ""))

                missing_patterns = (
                    "data-missing",
                    "Data does not exist",
                    "does not exist in the OpenDaylight controller",
                )

                if any(pat in body_text for pat in missing_patterns):
                    logger.info(
                        f"Node {node_id} already absent from ODL config (409 data-missing) — treating as success"
                    )
                    return True

                # Some ODL builds may nest error-tag in JSON objects; parse defensively.
                try:
                    parsed = json.loads(body_text) if body_text else {}
                    errors = (((parsed or {}).get("errors") or {}).get("error") or [])
                    if isinstance(errors, list) and any(
                        isinstance(err, dict) and str(err.get("error-tag", "")).lower() == "data-missing"
                        for err in errors
                    ):
                        logger.info(
                            f"Node {node_id} already absent from ODL config (409 error-tag=data-missing) — treating as success"
                        )
                        return True
                except Exception:
                    pass
            raise

    async def _wait_until_node_absent(
        self,
        node_id: str,
        max_wait_seconds: int = 30,
        check_interval: int = 2,
    ) -> bool:
        """
        Wait until node disappears from ODL operational topology.
        Returns True when absent, False on timeout.
        """
        elapsed = 0
        while elapsed < max_wait_seconds:
            status = await self.get_connection_status(node_id)
            if not status.get("mounted"):
                return True

            await asyncio.sleep(check_interval)
            elapsed += check_interval

        return False

    async def _wait_until_not_connecting(
        self,
        node_id: str,
        max_wait_seconds: int = 20,
        check_interval: int = 2,
    ) -> Dict[str, Any]:
        """
        Wait while node is in 'connecting' to avoid tearing down a fresh session too early.
        Returns latest status snapshot.
        """
        elapsed = 0
        last_status: Dict[str, Any] = {"mounted": False, "connection_status": "not-mounted"}
        while elapsed < max_wait_seconds:
            last_status = await self.get_connection_status(node_id)
            if last_status.get("connection_status") != "connecting":
                return last_status

            await asyncio.sleep(check_interval)
            elapsed += check_interval

        return last_status

    async def _is_node_present_in_config(self, node_id: str) -> bool:
        """
        Check if node exists in ODL config datastore even when operational node is absent.
        """
        node_path = f"{self.TOPOLOGY_PATH}/node={node_id}"
        spec = RequestSpec(
            method="GET",
            path=node_path,
            datastore="config",
            headers={"Accept": "application/yang-data+json"},
        )
        try:
            response = await self.odl_client.send(spec)
            node_list = response.get("network-topology:node", response.get("node", []))
            return bool(node_list)
        except OdlRequestError as e:
            if e.status_code == 404:
                return False
            logger.debug(f"Config node check error for {node_id}: {e}")
            return False
        except Exception as e:
            logger.debug(f"Config node check failed for {node_id}: {e}")
            return False
    
    async def mount_device(self, node_id: str, user_id: str) -> Dict[str, Any]:
        """
        Mount device ใน ODL โดยใช้ข้อมูลจาก Database
        
        Args:
            node_id: ODL node-id (เช่น "CSR1")
            user_id: ID ของ User ที่ทำการ mount
        
        Returns:
            Dict with success, message, node_id, connection_status, device_id
        """
        lock = self._get_device_lock(node_id)
        async with lock:
            return await self._mount_device_impl(node_id, user_id)

    async def _mount_device_impl(self, node_id: str, user_id: str) -> Dict[str, Any]:
        """Internal mount implementation; caller controls locking."""
        from app.services.device_credentials_service import DeviceCredentialsService

        prisma = get_prisma_client()
        device = None

        try:
            # 1. ดึงข้อมูล device จาก DB
            device = await self._find_device(node_id)

            if not device:
                raise ValueError(f"Device not found: {node_id}")

            # 2. Validate required fields
            if not device.node_id:
                raise ValueError("node_id is required for mounting")

            if not (device.netconf_host or device.ip_address):
                raise ValueError("netconf_host or ip_address is required")

            # 2.5 Fetch User Credentials (Fetch raw Prisma model to get the password)
            credentials = await prisma.devicecredentials.find_unique(where={"userId": user_id})
            if not credentials:
                raise ValueError("Device Credentials not configured for your profile")

            creds_svc = DeviceCredentialsService(prisma)
            plain_pw = creds_svc.decrypt_password(credentials.devicePasswordHash)

            # 3. Check if already mounted (always check ODL regardless of DB flag)
            odl_status = await self.get_connection_status(device.node_id)

            if odl_status.get("mounted"):
                connection_status = odl_status.get("connection_status", "unknown")

                if connection_status == "connected":
                    # Already mounted and connected → no action needed
                    # Sync DB if out of sync
                    if not device.odl_mounted:
                        await prisma.devicenetwork.update(
                            where={"id": device.id},
                            data={
                                "odl_mounted": True,
                                "odl_connection_status": "CONNECTED",
                                "status": "ONLINE",
                                "last_synced_at": datetime.utcnow()
                            }
                        )
                        await self.phpipam_service.sync_device_status_to_ipam(device.id, "ONLINE")
                    return {
                        "success": True,
                        "message": f"Device {device.node_id} is already mounted and connected",
                        "node_id": device.node_id,
                        "device_id": device.id,
                        "connection_status": connection_status,
                        "already_mounted": True
                    }
                elif connection_status == "connecting":
                    # Do not immediately remount while ODL is still negotiating schema/session.
                    logger.info(
                        f"Device {device.node_id} is currently connecting. Waiting briefly before deciding remount..."
                    )
                    latest = await self._wait_until_not_connecting(
                        device.node_id,
                        max_wait_seconds=20,
                        check_interval=2,
                    )
                    latest_conn = latest.get("connection_status", "unknown")

                    if latest.get("mounted") and latest_conn == "connected":
                        await prisma.devicenetwork.update(
                            where={"id": device.id},
                            data={
                                "odl_mounted": True,
                                "odl_connection_status": "CONNECTED",
                                "status": "ONLINE",
                                "last_synced_at": datetime.utcnow()
                            }
                        )
                        return {
                            "success": True,
                            "message": f"Device {device.node_id} became connected during wait",
                            "node_id": device.node_id,
                            "device_id": device.id,
                            "connection_status": "connected",
                            "already_mounted": True,
                            "ready_for_intent": True,
                        }

                    connection_status = latest_conn

                else:
                    # Node exists but NOT connected (connecting / unable-to-connect)
                    # → Unmount stale node first, then remount with fresh credentials
                    logger.info(
                        f"Device {device.node_id} has stale mount (status: {connection_status}), "
                        "unmounting before remount..."
                    )
                    await self._delete_node_from_odl(device.node_id)

                    # Wait until the stale operational node disappears to avoid session overlap.
                    removed = await self._wait_until_node_absent(device.node_id, max_wait_seconds=30, check_interval=2)
                    if not removed:
                        raise RuntimeError(
                            f"ODL is still tearing down old NETCONF session for {device.node_id}. "
                            "Please retry in a few seconds or use force-remount."
                        )

            # 3.5 Cleanup orphan config node if operational says not mounted.
            # This avoids stale topology entries causing mountpoint/transaction conflicts.
            if not odl_status.get("mounted") and await self._is_node_present_in_config(device.node_id):
                logger.warning(
                    f"Detected orphan config node for {device.node_id}. Cleaning up before mount..."
                )
                await self._delete_node_from_odl(device.node_id)
                await asyncio.sleep(2)

            # 4. Build mount payload
            payload = self._build_mount_payload(device, credentials.deviceUsername, plain_pw)

            # 5. Send mount request to ODL
            node_path = f"{self.TOPOLOGY_PATH}/node={device.node_id}"

            spec = RequestSpec(
                method="PUT",
                path=node_path,
                datastore="config",
                headers={
                    "Content-Type": "application/yang-data+json",
                    "Accept": "application/yang-data+json"
                },
                payload=payload
            )

            logger.info(f"Mounting device {device.node_id} to ODL...")
            await self.odl_client.send(spec)

            # 6. Update database — PUT สำเร็จ = mount entry created
            # Connection status จะเป็น "CONNECTING" ซึ่งเป็นเรื่องปกติ
            # (ODL ต้องใช้เวลา 30-120 วินาทีในการ download YANG modules)
            await prisma.devicenetwork.update(
                where={"id": device.id},
                data={
                    "odl_mounted": True,
                    "odl_connection_status": "CONNECTING",
                    "last_synced_at": datetime.utcnow()
                }
            )

            # Return immediately after mount request is accepted.
            # ODL will continue connection + YANG loading asynchronously.
            return {
                "success": True,
                "message": f"Device {device.node_id} mount request accepted. Mounting in progress...",
                "node_id": device.node_id,
                "device_id": device.id,
                "connection_status": "connecting",
                "device_status": "CONNECTING",
                "ready_for_intent": False,
            }

        except Exception as e:
            logger.error(f"Failed to mount device: {e}")

            # Update error status in DB
            if device:
                try:
                    await prisma.devicenetwork.update(
                        where={"id": device.id},
                        data={
                            "odl_mounted": False,
                            "odl_connection_status": "UNABLE_TO_CONNECT",
                            "status": "OFFLINE"
                        }
                    )
                    await self.phpipam_service.sync_device_status_to_ipam(device.id, "OFFLINE")
                except Exception:
                    pass

            raise
    
    async def unmount_device(self, node_id: str) -> Dict[str, Any]:
        """
        Unmount device จาก ODL
        
        Args:
            node_id: ODL node-id (เช่น "CSR1")
        
        Returns:
            {
                "success": True/False,
                "message": "...",
                "node_id": "..."
            }
        """
        lock = self._get_device_lock(node_id)
        async with lock:
            return await self._unmount_device_impl(node_id)

    async def _unmount_device_impl(self, node_id: str) -> Dict[str, Any]:
        """Internal unmount implementation; caller controls locking."""
        prisma = get_prisma_client()

        try:
            # 1. ดึงข้อมูล device จาก DB
            device = await self._find_device(node_id)

            if not device:
                raise ValueError(f"Device not found: {node_id}")

            if not device.node_id:
                raise ValueError("node_id is required for unmounting")

            # 2. Check if actually mounted before sending DELETE
            odl_status = await self.get_connection_status(device.node_id)

            if not odl_status.get("mounted"):
                # Node not in ODL — just sync DB and return success
                logger.info(f"Device {device.node_id} is not mounted in ODL — syncing DB only")
                await prisma.devicenetwork.update(
                    where={"id": device.id},
                    data={
                        "odl_mounted": False,
                        "odl_connection_status": "UNABLE_TO_CONNECT",
                        "status": "OFFLINE",
                        "last_synced_at": datetime.utcnow()
                    }
                )
                await self.phpipam_service.sync_device_status_to_ipam(device.id, "OFFLINE")
                return {
                    "success": True,
                    "message": f"Device {device.node_id} was already unmounted (DB synced)",
                    "node_id": device.node_id,
                }

            # 3. Send unmount request to ODL (DELETE from config datastore)
            # _delete_node_from_odl handles 404 gracefully
            logger.info(f"Unmounting device {device.node_id} from ODL...")
            await self._delete_node_from_odl(device.node_id)

            # 4. Verify ODL actually removed the node from operational datastore
            removed = await self._wait_until_node_absent(device.node_id, max_wait_seconds=20, check_interval=2)
            if not removed:
                logger.warning(
                    f"Node {device.node_id} still reported as mounted in ODL operational DS "
                    "after DELETE timeout. DB will be updated to OFFLINE; ODL should clean up asynchronously."
                )
            else:
                logger.info(f"Node {device.node_id} confirmed removed from ODL operational DS.")

            # 5. Update database
            await prisma.devicenetwork.update(
                where={"id": device.id},
                data={
                    "odl_mounted": False,
                    "odl_connection_status": "UNABLE_TO_CONNECT",
                    "status": "OFFLINE",
                    "last_synced_at": datetime.utcnow()
                }
            )
            await self.phpipam_service.sync_device_status_to_ipam(device.id, "OFFLINE")
            

            return {
                "success": True,
                "message": f"Device {device.node_id} unmounted successfully",
                "node_id": device.node_id
            }

        except Exception as e:
            logger.error(f"Failed to unmount device: {e}")
            raise
    
    async def get_connection_status(self, node_id: str) -> Dict[str, Any]:
        """
        ดึง connection status ของ node จาก ODL (operational datastore เท่านั้น)
        
        ใช้ ?content=nonconfig เพื่อ filter เฉพาะ operational data
        ซึ่งมี netconf-node-topology:connection-status ที่บอก status จริง
        
        Args:
            node_id: ODL node-id
        
        Returns:
            {
                "mounted": True/False,
                "connection_status": "connected/connecting/unable-to-connect",
                "host": "...",
                "port": ...
            }
        """
        try:
            # ?content=nonconfig → ดึงเฉพาะ operational data (ไม่เอา config ปนมา)
            # ทำให้ได้ connection-status ที่แม่นยำจาก ODL
            node_path = f"{self.TOPOLOGY_PATH}/node={node_id}?content=nonconfig"
            
            spec = RequestSpec(
                method="GET",
                path=node_path,
                datastore="config",  # RFC-8040: /rests/data/ (query param จัดการ filter เอง)
                headers={"Accept": "application/yang-data+json"}
            )
            
            response = await self.odl_client.send(spec)
            
            # Parse response
            node_list = response.get("network-topology:node", response.get("node", []))
            if not node_list:
                return {"mounted": False, "connection_status": "not-mounted"}
            
            node = node_list[0] if isinstance(node_list, list) else node_list
            
            connection_status = node.get(
                "netconf-node-topology:connection-status",
                "unknown"
            )
            connected_message = node.get("netconf-node-topology:connected-message")
            
            return {
                "mounted": True,
                "connection_status": connection_status,
                "connected_message": connected_message,
                "host": node.get("netconf-node-topology:host"),
                "port": node.get("netconf-node-topology:port"),
            }
            
        except OdlRequestError as e:
            if e.status_code == 404:
                return {"mounted": False, "connection_status": "not-mounted"}
            logger.debug(f"Node {node_id} status check error: {e}")
            return {"mounted": False, "connection_status": "not-mounted"}
        except Exception as e:
            logger.debug(f"Node {node_id} not found in ODL: {e}")
            return {"mounted": False, "connection_status": "not-mounted"}
    
    async def check_and_sync_status(self, node_id: str) -> Dict[str, Any]:
        """
        Check connection status และ sync กับ Database
        
        Args:
            node_id: ODL node-id (เช่น "CSR1")
        
        Returns:
            {
                "synced": True/False,
                "node_id": "...",
                "connection_status": "...",
                "ready_for_intent": True/False
            }
        """
        prisma = get_prisma_client()
        
        try:
            # 1. ดึงข้อมูล device จาก DB
            device = await self._find_device(node_id)
            
            if not device:
                raise ValueError(f"Device not found: {node_id}")
            
            # 2. Get status from ODL
            status = await self.get_connection_status(device.node_id)
            
            # 3. Determine if ready for intent
            is_connected = status.get("connection_status") == "connected"
            is_mounted = status.get("mounted", False)
            ready_for_intent = is_connected and is_mounted
            
            # 4. Update database
            device_status = "ONLINE" if is_connected else "OFFLINE"
            db_status = map_odl_status_to_enum(status.get("connection_status", "unknown"))
            
            await prisma.devicenetwork.update(
                where={"id": device.id},
                data={
                    "odl_mounted": is_mounted,
                    "odl_connection_status": db_status,
                    "status": device_status,
                    "last_synced_at": datetime.utcnow()
                }
            )
            # Sync phpIPAM tag to match new device status
            if str(device.status) != device_status:
                await self.phpipam_service.sync_device_status_to_ipam(device.id, device_status)
            
            return {
                "synced": True,
                "node_id": device.node_id,
                "device_id": device.id,
                "device_name": device.device_name,
                "mounted": is_mounted,
                "connection_status": status.get("connection_status", "unknown"),
                "connected_message": status.get("connected_message"),
                "device_status": device_status,
                "ready_for_intent": ready_for_intent,
                "message": "Ready to use Intent API" if ready_for_intent else "Device not connected yet"
            }
            
        except Exception as e:
            logger.error(f"Failed to sync status: {e}")
            raise
    
    async def wait_until_connected(
        self,
        node_id: str,
        max_wait_seconds: int = 120,
        check_interval: int = 5,
    ) -> Dict[str, Any]:
        """
        Poll ODL until the node reports 'connected' (or timeout/failure).

        This is the ONLY safe gate before issuing any NETCONF RPC (get-config,
        get-interface, etc.) against a mounted node.  Calling those RPCs while
        ODL is still in the 'connecting' state forces it to queue the requests
        internally; if too many queue up the NETCONF session is torn down and
        the node becomes permanently stuck.

        Args:
            node_id: ODL node-id (e.g. "ASR02XE")
            max_wait_seconds: How long to poll before giving up (default 120 s).
                              Real Cisco ASR hardware typically needs 30–90 s to
                              download and compile its full YANG schema set.
            check_interval: Seconds between each status poll (default 5 s).

        Returns:
            {
                "ready": True/False,
                "connection_status": "connected" | "connecting" | "unable-to-connect" | "unknown",
                "waited_seconds": int,
                "message": str
            }
        """
        elapsed = 0
        while elapsed < max_wait_seconds:
            status = await self.get_connection_status(node_id)
            conn = status.get("connection_status", "unknown")

            logger.info(
                f"[wait_until_connected] {node_id}: status={conn}, "
                f"elapsed={elapsed}s / {max_wait_seconds}s"
            )

            if conn == "connected":
                return {
                    "ready": True,
                    "connection_status": conn,
                    "waited_seconds": elapsed,
                    "message": f"Device {node_id} is fully connected and ready.",
                }

            if conn == "unable-to-connect":
                return {
                    "ready": False,
                    "connection_status": conn,
                    "connected_message": status.get("connected_message"),
                    "waited_seconds": elapsed,
                    "message": (
                        f"ODL reported 'unable-to-connect' for {node_id}. "
                        "Check NETCONF credentials and device reachability."
                    ),
                }

            # Still 'connecting' — wait and try again
            await asyncio.sleep(check_interval)
            elapsed += check_interval

        # Timed out while still connecting
        final = await self.get_connection_status(node_id)
        return {
            "ready": False,
            "connection_status": final.get("connection_status", "unknown"),
            "connected_message": final.get("connected_message"),
            "waited_seconds": elapsed,
            "message": (
                f"Timeout ({max_wait_seconds}s) waiting for {node_id} to become connected. "
                "ODL may still be downloading YANG modules. "
                "Call GET /status again in a few seconds or increase max_wait_seconds."
            ),
        }

    async def mount_and_wait(
        self, 
        node_id: str, 
        user_id: str,
        max_wait_seconds: int = 120,
        check_interval: int = 5
    ) -> Dict[str, Any]:
        """
        Mount device และรอจนกว่าจะ connected (หรือ timeout)
        ใช้ per-device lock เพื่อป้องกัน concurrent mount/unmount
        
        Args:
            node_id: ODL node-id (เช่น "CSR1")
            user_id: ID ของ User ที่กระทำการ mount
            max_wait_seconds: เวลารอสูงสุด (วินาที)
            check_interval: interval ในการ check status (วินาที)
        
        Returns:
            Mount result พร้อม final connection status
        """
        lock = self._get_device_lock(node_id)
        async with lock:
            return await self._mount_and_wait_impl(
                node_id, user_id, max_wait_seconds, check_interval
            )

    async def _mount_and_wait_impl(
        self,
        node_id: str,
        user_id: str,
        max_wait_seconds: int,
        check_interval: int,
    ) -> Dict[str, Any]:
        """Internal implementation of mount_and_wait (runs under device lock)."""
        prisma = get_prisma_client()

        # 1. Mount — call internal impl since caller already holds lock
        mount_result = await self._mount_device_impl(node_id, user_id)
        
        if not mount_result.get("success"):
            return mount_result
        
        # Already connected during mount? Return immediately
        if mount_result.get("connection_status") == "connected":
            mount_result["ready_for_intent"] = True
            mount_result["wait_time_seconds"] = 0
            return mount_result
        
        # 2. Use device_id from mount_result (avoid duplicate DB query)
        device_id = mount_result.get("device_id")
        
        # 3. Wait for connection
        elapsed = 0
        while elapsed < max_wait_seconds:
            status = await self.get_connection_status(node_id)
            connection_status = status.get("connection_status")

            if connection_status == "connected":
                # Update DB and return success
                await prisma.devicenetwork.update(
                    where={"id": device_id},
                    data={
                        "odl_connection_status": "CONNECTED",
                        "status": "ONLINE",
                        "last_synced_at": datetime.utcnow()
                    }
                )
                await self.phpipam_service.sync_device_status_to_ipam(device_id, "ONLINE")
                
                return {
                    "success": True,
                    "message": f"Device {node_id} mounted and connected",
                    "node_id": node_id,
                    "device_id": device_id,
                    "connection_status": "connected",
                    "device_status": "ONLINE",
                    "ready_for_intent": True,
                    "wait_time_seconds": elapsed
                }
            
            elif connection_status == "unable-to-connect":
                await prisma.devicenetwork.update(
                    where={"id": device_id},
                    data={
                        "odl_mounted": False,
                        "odl_connection_status": "UNABLE_TO_CONNECT",
                        "status": "OFFLINE",
                        "last_synced_at": datetime.utcnow()
                    }
                )
                await self.phpipam_service.sync_device_status_to_ipam(device_id, "OFFLINE")
                
                return {
                    "success": False,
                    "message": f"Device {node_id} unable to connect",
                    "node_id": node_id,
                    "device_id": device_id,
                    "connection_status": "unable-to-connect",
                    "device_status": "OFFLINE",
                    "ready_for_intent": False
                }
            
            # Still connecting, wait more
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        # Timeout
        final_status = await self.get_connection_status(node_id)
        
        await prisma.devicenetwork.update(
            where={"id": device_id},
            data={
                "odl_mounted": True,
                "odl_connection_status": map_odl_status_to_enum(
                    final_status.get("connection_status", "unknown")
                ),
                "status": "OFFLINE",
                "last_synced_at": datetime.utcnow()
            }
        )
        await self.phpipam_service.sync_device_status_to_ipam(device_id, "OFFLINE")
        
        return {
            "success": False,
            "message": f"Timeout waiting for connection ({max_wait_seconds}s)",
            "node_id": node_id,
            "device_id": device_id,
            "connection_status": final_status.get("connection_status", "unknown"),
            "device_status": "OFFLINE",
            "ready_for_intent": False
        }

    async def force_remount(
        self,
        node_id: str,
        user_id: str,
        max_wait_seconds: int = 120,
        cleanup_wait: int = 10,
    ) -> Dict[str, Any]:
        """
        Force-remount a stuck device.
        ใช้ per-device lock + ย้าย logic จาก API layer เข้ามาใน service layer
        เพื่อให้จัดการ state ได้ดีขึ้น
        """
        lock = self._get_device_lock(node_id)
        async with lock:
            logger.info(f"[force-remount] Starting force-remount for {node_id}")

            # Step 1: Hard-delete from ODL config (handles 404 gracefully)
            try:
                await self._delete_node_from_odl(node_id)
                logger.info(f"[force-remount] Deleted {node_id} from ODL config")
            except Exception as e:
                logger.warning(f"[force-remount] Delete step failed for {node_id}: {e}")

            # Step 2: Update DB to reflect unmounted state
            device = await self._find_device(node_id)
            if device:
                prisma = get_prisma_client()
                await prisma.devicenetwork.update(
                    where={"id": device.id},
                    data={
                        "odl_mounted": False,
                        "odl_connection_status": "UNABLE_TO_CONNECT",
                        "status": "OFFLINE",
                    }
                )
                await self.phpipam_service.sync_device_status_to_ipam(device.id, "OFFLINE")

            # Step 3: Wait for ODL session teardown
            logger.info(f"[force-remount] Waiting {cleanup_wait}s for ODL session teardown")
            await asyncio.sleep(cleanup_wait)

            # Step 4: Verify node is gone
            residual = await self.get_connection_status(node_id)
            if residual.get("mounted"):
                logger.warning(
                    f"[force-remount] Node {node_id} still visible after {cleanup_wait}s — proceeding"
                )

            # Step 5: Mount and wait (inside same lock)
            return await self._mount_and_wait_impl(
                node_id, user_id, max_wait_seconds, check_interval=5
            )
