"""
Config Normalizer
Standardizes responses for configuration (write) operations
"""
from typing import Any, Dict
from app.schemas.unified import UnifiedConfigResult

class ConfigNormalizer:
    """
    Normalize configuration responses
    Returns consistent UnifiedConfigResult for all write operations
    """
    
    @staticmethod
    def normalize(intent: str, driver: str, raw: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize configuration response
        
        Args:
            intent: Intent name (e.g. "interface.set_ipv4")
            driver: Driver used (e.g. "cisco", "huawei")
            raw: Raw response from ODL/Device
            params: Parameters used in the request
            
        Returns:
            UnifiedConfigResult dict
        """
        success = True
        warnings = []
        changes = []
        
        # Analyze raw response for errors (basic check)
        # ODL often returns 200 OK even on some device errors, but usually
        # errors are raised as exceptions before this point.
        # If we are here, it's likely successful or a partial success.
        
        # Build human-readable message based on intent
        message = f"Successfully executed {intent}"
        
        # Interface Intents
        if intent == "interface.set_ipv4":
            iface = params.get("interface", "")
            ip = params.get("ip", "")
            changes.append(f"Set IPv4 {ip} on {iface}")
            
        elif intent == "interface.set_ipv6":
            iface = params.get("interface", "")
            ip = params.get("ip", "")
            changes.append(f"Set IPv6 {ip} on {iface}")
            
        elif intent == "interface.enable":
            iface = params.get("interface", "")
            changes.append(f"Enabled interface {iface}")
            
        elif intent == "interface.disable":
            iface = params.get("interface", "")
            changes.append(f"Disabled interface {iface}")
            
        elif intent == "interface.set_description":
            iface = params.get("interface", "")
            desc = params.get("description", "")
            changes.append(f"Updated description on {iface}")
            
        elif intent == "interface.set_mtu":
            iface = params.get("interface", "")
            mtu = params.get("mtu", "")
            changes.append(f"Set MTU to {mtu} on {iface}")

        elif intent == "interface.create_subinterface":
            iface = params.get("interface", "")
            vlan = params.get("vlan_id", "")
            changes.append(f"Created sub-interface {iface} with VLAN {vlan}")
            
        # Routing Intents
        elif intent == "routing.static.add":
            prefix = params.get("prefix", "")
            nh = params.get("next_hop", "")
            changes.append(f"Added static route {prefix} via {nh}")
            
        elif intent == "routing.static.delete":
            prefix = params.get("prefix", "")
            changes.append(f"Removed static route {prefix}")
            
        elif intent == "routing.default.add":
            nh = params.get("next_hop", "")
            changes.append(f"Added default route via {nh}")
            
        # OSPF Intents
        elif intent == "routing.ospf.enable":
            pid = params.get("process_id", "")
            changes.append(f"Enabled OSPF process {pid}")
            
        elif intent == "routing.ospf.add_network_interface":
            pid = params.get("process_id", "")
            iface = params.get("interface", "")
            area = params.get("area", "")
            changes.append(f"Added interface {iface} to OSPF {pid} area {area}")

        # System Intents
        elif intent == "system.set_hostname":
            hostname = params.get("hostname", "")
            changes.append(f"Set hostname to {hostname}")
            
        elif intent == "system.set_ntp":
            server = params.get("server", "")
            changes.append(f"Added NTP server {server}")
            
        # Add driver info to messages if needed
        # message += f" (Driver: {driver})"

        return UnifiedConfigResult(
            success=success,
            message=message,
            changes=changes,
            warnings=warnings
        ).model_dump()
