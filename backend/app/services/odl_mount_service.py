"""
ODL Mount Service
Service สำหรับ Mount/Unmount NETCONF nodes ใน OpenDaylight

Flow:
1. รับข้อมูล device จาก Database (รวม NETCONF credentials)
2. สร้าง payload สำหรับ mount
3. ส่งไปยัง ODL RESTCONF API
4. Update status ใน Database
5. Sync connection status
"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
from app.clients.odl_restconf_client import OdlRestconfClient
from app.core.errors import OdlRequestError
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client


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
        return {
            "network-topology:node": [
                {
                    "node-id": device.node_id,
                    "netconf-node-topology:host": device.netconf_host or device.ip_address,
                    "netconf-node-topology:port": getattr(device, 'netconf_port', 830) or 830,
                    "netconf-node-topology:username": username,
                    "netconf-node-topology:password": password,
                    "netconf-node-topology:tcp-only": False,
                    "netconf-node-topology:keepalive-delay": 120,
                    "netconf-node-topology:connection-timeout-millis": 120000,
                    "netconf-node-topology:default-request-timeout-millis": 300000,
                    "netconf-node-topology:max-connection-attempts": 15,
                    "netconf-node-topology:between-attempts-timeout-millis": 5000,          
                    "netconf-node-topology:sleep-factor": 1.5,
                    "netconf-node-topology:reconnect-on-changed-schema": True,
                    "netconf-node-topology:schemaless": False,
                    "netconf-node-topology:lock-datastore": False
                }
            ]
        }

    async def _delete_node_from_odl(self, node_id: str) -> bool:
        """
        DELETE node จาก ODL config datastore.
        Returns True ถ้าสำเร็จ (รวมถึง 404 ที่แปลว่าลบไปแล้ว)
        Raises exception เฉพาะ error ที่ไม่ใช่ 404
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
            raise
    
    async def mount_device(self, node_id: str, user_id: str) -> Dict[str, Any]:
        """
        Mount device ใน ODL โดยใช้ข้อมูลจาก Database
        
        Args:
            node_id: ODL node-id (เช่น "CSR1")
            user_id: ID ของ User ที่ทำการ mount
        
        Returns:
            Dict with success, message, node_id, connection_status, device_id
        """
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
                    return {
                        "success": True,
                        "message": f"Device {device.node_id} is already mounted and connected",
                        "node_id": device.node_id,
                        "device_id": device.id,
                        "connection_status": connection_status,
                        "already_mounted": True
                    }
                else:
                    # Node exists but NOT connected (connecting / unable-to-connect)
                    # → Unmount stale node first, then remount with fresh credentials
                    logger.info(f"Device {device.node_id} has stale mount (status: {connection_status}), unmounting before remount...")
                    await self._delete_node_from_odl(device.node_id)
                    # Give ODL time to tear down the NETCONF session
                    await asyncio.sleep(5)
            
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
            
            # 7. Quick check — ไม่ block นาน, ใช้ wait-ready endpoint แทน
            await asyncio.sleep(3)
            status = await self.get_connection_status(device.node_id)
            connection_status = status.get("connection_status", "connecting")
            
            # 8. Update final status (if already resolved)
            if connection_status == "connected":
                await prisma.devicenetwork.update(
                    where={"id": device.id},
                    data={
                        "odl_connection_status": "CONNECTED",
                        "status": "ONLINE",
                        "last_synced_at": datetime.utcnow()
                    }
                )
            
            # mount_device returns success=True if PUT succeeded,
            # regardless of whether ODL has finished connecting yet.
            # Use wait-ready or mount_and_wait for full connection guarantee.
            return {
                "success": True,
                "message": (
                    f"Device {device.node_id} mounted and connected"
                    if connection_status == "connected"
                    else f"Device {device.node_id} mount request sent (status: {connection_status}). "
                         "Use GET /wait-ready to poll until fully connected."
                ),
                "node_id": device.node_id,
                "device_id": device.id,
                "connection_status": connection_status,
                "device_status": "ONLINE" if connection_status == "connected" else "CONNECTING",
                "ready_for_intent": connection_status == "connected",
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
            # ODL may take a few seconds to tear down the NETCONF session
            await asyncio.sleep(3)
            verify_status = await self.get_connection_status(device.node_id)
            if verify_status.get("mounted"):
                logger.warning(
                    f"Node {device.node_id} still reported as mounted in ODL operational DS "
                    "after DELETE. The NETCONF session may still be tearing down. "
                    "DB will be updated to OFFLINE; ODL will clean up asynchronously."
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
            
            return {
                "mounted": True,
                "connection_status": connection_status,
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
            
            return {
                "synced": True,
                "node_id": device.node_id,
                "device_id": device.id,
                "device_name": device.device_name,
                "mounted": is_mounted,
                "connection_status": status.get("connection_status", "unknown"),
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

        # 1. Mount — mount_device returns device_id so we don't need to query again
        mount_result = await self.mount_device(node_id, user_id)
        
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
