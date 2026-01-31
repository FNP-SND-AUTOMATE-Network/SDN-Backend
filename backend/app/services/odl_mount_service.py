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
from app.schemas.request_spec import RequestSpec
from app.core.logging import logger
from app.database import get_prisma_client


class OdlMountService:
    """
    Service สำหรับ Mount/Unmount NETCONF nodes ใน ODL
    """
    
    # ODL topology-netconf base path
    TOPOLOGY_PATH = "/network-topology:network-topology/topology=topology-netconf"
    
    def __init__(self):
        self.odl_client = OdlRestconfClient()
    
    def _build_mount_payload(self, device) -> Dict[str, Any]:
        """
        สร้าง payload สำหรับ mount NETCONF node
        
        Args:
            device: DeviceNetwork object จาก DB
        
        Returns:
            ODL mount payload
        """
        return {
            "node": [
                {
                    "node-id": device.node_id,
                    "netconf-node-topology:host": device.netconf_host or device.ip_address,
                    "netconf-node-topology:port": device.netconf_port or 830,
                    "netconf-node-topology:username": device.netconf_username,
                    "netconf-node-topology:password": device.netconf_password,
                }
            ]
        }
    
    async def mount_device(self, device_id: str) -> Dict[str, Any]:
        """
        Mount device ใน ODL โดยใช้ข้อมูลจาก Database
        
        Args:
            device_id: Database ID ของ device
        
        Returns:
            {
                "success": True/False,
                "message": "...",
                "node_id": "...",
                "connection_status": "..."
            }
        """
        prisma = get_prisma_client()
        
        try:
            # 1. ดึงข้อมูล device จาก DB
            device = await prisma.devicenetwork.find_unique(
                where={"id": device_id}
            )
            
            if not device:
                raise ValueError(f"Device not found: {device_id}")
            
            # 2. Validate required fields
            if not device.node_id:
                raise ValueError("node_id is required for mounting")
            
            if not (device.netconf_host or device.ip_address):
                raise ValueError("netconf_host or ip_address is required")
            
            if not device.netconf_username or not device.netconf_password:
                raise ValueError("netconf_username and netconf_password are required")
            
            # 3. Check if already mounted
            if device.odl_mounted:
                # Check actual status in ODL
                status = await self.get_connection_status(device.node_id)
                if status.get("mounted"):
                    return {
                        "success": True,
                        "message": f"Device {device.node_id} is already mounted",
                        "node_id": device.node_id,
                        "connection_status": status.get("connection_status", "unknown"),
                        "already_mounted": True
                    }
            
            # 4. Build mount payload
            payload = self._build_mount_payload(device)
            
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
            response = await self.odl_client.send(spec)
            
            # 6. Update database
            await prisma.devicenetwork.update(
                where={"id": device_id},
                data={
                    "odl_mounted": True,
                    "odl_connection_status": "connecting",
                    "last_synced_at": datetime.utcnow()
                }
            )
            
            # 7. Wait and check connection status
            await asyncio.sleep(2)  # รอให้ ODL connect
            status = await self.get_connection_status(device.node_id)
            
            # 8. Update final status
            connection_status = status.get("connection_status", "unknown")
            device_status = "ONLINE" if connection_status == "connected" else "OFFLINE"
            
            await prisma.devicenetwork.update(
                where={"id": device_id},
                data={
                    "odl_connection_status": connection_status,
                    "status": device_status,
                    "last_synced_at": datetime.utcnow()
                }
            )
            
            return {
                "success": True,
                "message": f"Device {device.node_id} mounted successfully",
                "node_id": device.node_id,
                "connection_status": connection_status,
                "device_status": device_status
            }
            
        except Exception as e:
            logger.error(f"Failed to mount device: {e}")
            
            # Update error status in DB
            try:
                await prisma.devicenetwork.update(
                    where={"id": device_id},
                    data={
                        "odl_mounted": False,
                        "odl_connection_status": f"error: {str(e)[:100]}",
                        "status": "OFFLINE"
                    }
                )
            except:
                pass
            
            raise
    
    async def unmount_device(self, device_id: str) -> Dict[str, Any]:
        """
        Unmount device จาก ODL
        
        Args:
            device_id: Database ID ของ device
        
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
            device = await prisma.devicenetwork.find_unique(
                where={"id": device_id}
            )
            
            if not device:
                raise ValueError(f"Device not found: {device_id}")
            
            if not device.node_id:
                raise ValueError("node_id is required for unmounting")
            
            # 2. Send unmount request to ODL (DELETE)
            node_path = f"{self.TOPOLOGY_PATH}/node={device.node_id}"
            
            spec = RequestSpec(
                method="DELETE",
                path=node_path,
                datastore="config",
                headers={"Accept": "application/yang-data+json"}
            )
            
            logger.info(f"Unmounting device {device.node_id} from ODL...")
            await self.odl_client.send(spec)
            
            # 3. Update database
            await prisma.devicenetwork.update(
                where={"id": device_id},
                data={
                    "odl_mounted": False,
                    "odl_connection_status": "not-mounted",
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
        ดึง connection status ของ node จาก ODL
        
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
            node_path = f"{self.TOPOLOGY_PATH}/node={node_id}"
            
            spec = RequestSpec(
                method="GET",
                path=node_path,
                datastore="operational",  # ใช้ operational เพื่อดู actual status
                headers={"Accept": "application/yang-data+json"}
            )
            
            response = await self.odl_client.send(spec)
            
            # Parse response
            node_list = response.get("network-topology:node", response.get("node", []))
            if not node_list:
                return {"mounted": False, "connection_status": "not-mounted"}
            
            node = node_list[0] if isinstance(node_list, list) else node_list
            
            return {
                "mounted": True,
                "connection_status": node.get(
                    "netconf-node-topology:connection-status",
                    "unknown"
                ),
                "host": node.get("netconf-node-topology:host"),
                "port": node.get("netconf-node-topology:port")
            }
            
        except Exception as e:
            logger.debug(f"Node {node_id} not found in ODL: {e}")
            return {"mounted": False, "connection_status": "not-mounted"}
    
    async def check_and_sync_status(self, device_id: str) -> Dict[str, Any]:
        """
        Check connection status และ sync กับ Database
        
        Args:
            device_id: Database ID ของ device
        
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
            device = await prisma.devicenetwork.find_unique(
                where={"id": device_id}
            )
            
            if not device:
                raise ValueError(f"Device not found: {device_id}")
            
            if not device.node_id:
                raise ValueError("node_id is required")
            
            # 2. Get status from ODL
            status = await self.get_connection_status(device.node_id)
            
            # 3. Determine if ready for intent
            is_connected = status.get("connection_status") == "connected"
            is_mounted = status.get("mounted", False)
            ready_for_intent = is_connected and is_mounted
            
            # 4. Update database
            device_status = "ONLINE" if is_connected else "OFFLINE"
            
            await prisma.devicenetwork.update(
                where={"id": device_id},
                data={
                    "odl_mounted": is_mounted,
                    "odl_connection_status": status.get("connection_status", "unknown"),
                    "status": device_status,
                    "last_synced_at": datetime.utcnow()
                }
            )
            
            return {
                "synced": True,
                "node_id": device.node_id,
                "device_id": device_id,
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
    
    async def mount_and_wait(
        self, 
        device_id: str, 
        max_wait_seconds: int = 30,
        check_interval: int = 3
    ) -> Dict[str, Any]:
        """
        Mount device และรอจนกว่าจะ connected (หรือ timeout)
        
        Args:
            device_id: Database ID ของ device
            max_wait_seconds: เวลารอสูงสุด (วินาที)
            check_interval: interval ในการ check status (วินาที)
        
        Returns:
            Mount result พร้อม final connection status
        """
        # 1. Mount
        mount_result = await self.mount_device(device_id)
        
        if not mount_result.get("success"):
            return mount_result
        
        node_id = mount_result.get("node_id")
        
        # 2. Wait for connection
        elapsed = 0
        while elapsed < max_wait_seconds:
            status = await self.get_connection_status(node_id)
            connection_status = status.get("connection_status")
            
            if connection_status == "connected":
                # Update DB and return success
                prisma = get_prisma_client()
                await prisma.devicenetwork.update(
                    where={"id": device_id},
                    data={
                        "odl_connection_status": "connected",
                        "status": "ONLINE",
                        "last_synced_at": datetime.utcnow()
                    }
                )
                
                return {
                    "success": True,
                    "message": f"Device {node_id} mounted and connected",
                    "node_id": node_id,
                    "connection_status": "connected",
                    "device_status": "ONLINE",
                    "ready_for_intent": True,
                    "wait_time_seconds": elapsed
                }
            
            elif connection_status == "unable-to-connect":
                return {
                    "success": False,
                    "message": f"Device {node_id} unable to connect",
                    "node_id": node_id,
                    "connection_status": "unable-to-connect",
                    "device_status": "OFFLINE",
                    "ready_for_intent": False
                }
            
            # Still connecting, wait more
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        # Timeout
        final_status = await self.get_connection_status(node_id)
        return {
            "success": False,
            "message": f"Timeout waiting for connection ({max_wait_seconds}s)",
            "node_id": node_id,
            "connection_status": final_status.get("connection_status", "unknown"),
            "device_status": "OFFLINE",
            "ready_for_intent": False
        }
