from typing import Dict, Any, List
from app.drivers.base import BaseDriver
from app.schemas.request_spec import RequestSpec
from app.core.errors import UnsupportedIntent


class OpenFlowDriver(BaseDriver):
    """
    Driver for handling OpenFlow operations directly via ODL.
    Unlike NETCONF drivers, this uses the datapath_id to build the RESTCONF path.
    """

    SUPPORTED_INTENTS: List[str] = [
        "flow.add",
        "flow.delete",
        "show.flows",
    ]

    def build(self, device: Any, intent: str, params: Dict[str, Any]) -> RequestSpec:
        """
        Build an OpenFlow RESTCONF request.
        
        Args:
            device: The DeviceNetwork object which should have `datapath_id`
            intent: The specific intent name (e.g. "flow.add")
            params: Parameters including table_id, flow_id, priority, match, instructions
            
        Returns:
            RequestSpec ready to be sent to ODL.
        """
        
        path, payload, method = self._route_intent(intent, device, params)
        
        # Use 'config' datastore for add/delete since we are writing to ODL.
        # Use 'operational' datastore (or generic) when reading flows.
        # Depending on ODL version, reading from config vs operational shows different views.
        # For showing flows currently operating on the switch, 'operational' is standard.
        # But we will let the intent specify if we want 'config' or 'operational', default to what is appropriate.
        datastore = "operational" if intent == "show.flows" else "config"
        
        return RequestSpec(
            method=method,
            datastore=datastore, 
            path=path,
            payload=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            intent=intent,
            driver="openflow"
        )
    def _route_intent(self, intent: str, device: Any, params: Dict[str, Any]) -> tuple[str, Dict[str, Any] | None, str]:
        """Route the intent to the correct handler method"""
        
        if not device.datapath_id:
            raise ValueError(f"Device {device.node_id} is lacking a 'datapath_id'. An OpenFlow driver requires this.")
            
        # ODL node for OpenFlow is typically "openflow:{datapath_id}"
        # Make sure datapath_id does not already contain "openflow:"
        dp_id = device.datapath_id
        if dp_id.startswith("openflow:"):
            node_identifier = dp_id
        else:
            # Handle cases where DPID might be a long int string vs padded hex
            try:
                # If they passed '1', format it if needed, or just use it.
                # Assuming ODL assigns exactly openflow:1 or openflow:2 etc.
                if dp_id.isdigit():
                    node_identifier = f"openflow:{int(dp_id)}"
                else:
                    node_identifier = f"openflow:{dp_id}"
            except ValueError:
                node_identifier = f"openflow:{dp_id}"
                
        # Base path for OpenFlow table operations
        # /rests/data/opendaylight-inventory:nodes/node={node_id}/flow-node-inventory:table={table_id}/flow={flow_id}
        base_path = f"/rests/data/opendaylight-inventory:nodes/node={node_identifier}"

        table_id = params.get("table_id", 0)
        flow_id = params.get("flow_id")
        
        if intent == "flow.add":
            if not flow_id:
                raise ValueError("flow_id is required for flow.add")
                
            path = f"{base_path}/flow-node-inventory:table={table_id}/flow={flow_id}"
            
            # Construct the flow payload based on user's examples
            flow_data = {
                "id": flow_id,
                "table_id": table_id,
                "priority": params.get("priority", 10),
                "match": params.get("match", {}),
                "instructions": params.get("instructions", {})
            }
            
            # The root wrapper for ODL PUT is typically just the flow-node-inventory namespace wrapping the array
            # "flow-node-inventory:flow": [ { ... } ]
            payload = {
                "flow-node-inventory:flow": [
                    flow_data
                ]
            }
            return path, payload, "PUT"
            
        elif intent == "flow.delete":
             if not flow_id:
                  raise ValueError("flow_id is required for flow.delete")
             path = f"{base_path}/flow-node-inventory:table={table_id}/flow={flow_id}"
             return path, None, "DELETE"
             
        elif intent == "show.flows":
            # If table_id is provided, show that table. Otherwise show all tables.
            if "table_id" in params:
                 path = f"{base_path}/flow-node-inventory:table={table_id}"
            else:
                 path = base_path
            return path, None, "GET"

        else:
            raise UnsupportedIntent(intent, driver="openflow")
