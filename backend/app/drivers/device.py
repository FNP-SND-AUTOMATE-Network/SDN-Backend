"""
Device Driver - สำหรับ Mount/Unmount NETCONF devices ใน ODL

Note: mount/unmount ไม่ผ่าน intent system แล้ว ใช้ dedicated REST endpoints แทน:
    POST /api/v1/nbi/devices/{node_id}/mount
    POST /api/v1/nbi/devices/{node_id}/unmount

build_mount/build_unmount methods ยังคงใช้งานได้โดย OdlMountService
"""
from typing import Any, Dict
from app.schemas.request_spec import RequestSpec


class DeviceDriver:
    """
    Driver สำหรับจัดการ NETCONF device mounting ใน OpenDaylight
    
    ไม่ต้องใช้ DeviceProfile เพราะเป็นการสร้าง/ลบ device เอง
    
    Note: build_mount และ build_unmount ยังคงใช้งานได้โดย OdlMountService
          แต่ไม่ผ่าน intent system แล้ว (ใช้ dedicated REST endpoints แทน)
    """
    name = "device"
    
    def build_mount(self, node_id: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Build RESTCONF request for mounting NETCONF device
        
        RFC-8040 path: /network-topology:network-topology/topology=topology-netconf/node={node_id}
        
        Required params:
            - host: IP address of device
            - port: NETCONF port (usually 830)
            - username: Device username
            - password: Device password
        
        Optional params:
            - tcp_only: Use TCP only (default: false)
            - keepalive_delay: Keepalive delay in seconds (default: 10)
            - connection_timeout: Connection timeout in ms (default: 20000)
            - default_request_timeout: Request timeout in ms (default: 60000)
            - reconnect_on_changed_schema: Reconnect if schema changes (default: false)
        """
        host = params["host"]
        port = params.get("port", 830)
        username = params["username"]
        password = params["password"]
        
        # Optional params with defaults
        tcp_only = params.get("tcp_only", False)
        schemaless = params.get("schemaless", False)
        connection_timeout = params.get("connection_timeout", 20000)
        default_request_timeout = params.get("default_request_timeout", 60000)
        keepalive_delay = params.get("keepalive_delay", 120)
        reconnect_on_changed_schema = params.get("reconnect_on_changed_schema", True)
        
        path = f"/network-topology:network-topology/topology=topology-netconf/node={node_id}"
        
        payload = {
            "network-topology:node": [
                {
                    "node-id": node_id,
                    "netconf-node-topology:host": host,
                    "netconf-node-topology:port": port,
                    "netconf-node-topology:username": username,
                    "netconf-node-topology:password": password,
                    "netconf-node-topology:tcp-only": tcp_only,
                    "netconf-node-topology:schemaless": schemaless,
                    "netconf-node-topology:connection-timeout-millis": connection_timeout,
                    "netconf-node-topology:default-request-timeout-millis": default_request_timeout,
                    "netconf-node-topology:keepalive-delay": keepalive_delay,
                    "netconf-node-topology:reconnect-on-changed-schema": reconnect_on_changed_schema
                }
            ]
        }
        
        return RequestSpec(
            method="PUT",
            datastore="config",
            path=path,
            payload=payload,
            headers={
                "Content-Type": "application/yang-data+json",
                "Accept": "application/yang-data+json"
            },
            intent="device.mount",
            driver=self.name
        )
    
    def build_unmount(self, node_id: str) -> RequestSpec:
        """
        Build RESTCONF request for unmounting NETCONF device
        
        RFC-8040 path: DELETE /network-topology:network-topology/topology=topology-netconf/node={node_id}
        """
        path = f"/network-topology:network-topology/topology=topology-netconf/node={node_id}"
        
        return RequestSpec(
            method="DELETE",
            datastore="config",
            path=path,
            payload=None,
            headers={
                "Accept": "application/yang-data+json"
            },
            intent="device.unmount",
            driver=self.name
        )
    
    def build_get_status(self, node_id: str) -> RequestSpec:
        """
        Build RESTCONF request for getting device connection status
        
        RFC-8040 path: GET /network-topology:network-topology/topology=topology-netconf/node={node_id}
        """
        path = f"/network-topology:network-topology/topology=topology-netconf/node={node_id}"
        
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={
                "Accept": "application/yang-data+json"
            },
            intent="device.status",
            driver=self.name
        )
    
    def build_list_devices(self) -> RequestSpec:
        """
        Build RESTCONF request for listing all mounted NETCONF devices
        
        RFC-8040 path: GET /network-topology:network-topology/topology=topology-netconf
        """
        path = "/network-topology:network-topology/topology=topology-netconf"
        
        return RequestSpec(
            method="GET",
            datastore="operational",
            path=path,
            payload=None,
            headers={
                "Accept": "application/yang-data+json"
            },
            intent="device.list",
            driver=self.name
        )
