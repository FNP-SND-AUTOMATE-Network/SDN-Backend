"""
VLAN Normalizer
แปลง vendor-specific VLAN response เป็น Unified format
"""
from typing import Any, Dict, List
from app.schemas.unified import UnifiedVlan, UnifiedVlanList


class VlanNormalizer:
    """Normalize VLAN responses from different vendors to unified format"""
    
    def normalize_show_vlans(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize show vlans response → unified VLAN list"""
        
        if driver_used == "CISCO_IOS_XE":
            return self._normalize_cisco_vlans(raw)
        
        if driver_used == "HUAWEI_VRP":
            return self._normalize_huawei_vlans(raw)
        
        
        # Fallback
        return UnifiedVlanList(vlans=[], total_count=0).model_dump()
    
    # =========================================================
    # Cisco
    # =========================================================
    
    def _normalize_cisco_vlans(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Cisco IOS-XE native VLAN response
        Raw: { "Cisco-IOS-XE-native:vlan": { "Cisco-IOS-XE-vlan:vlan-list": [...] } }
        """
        vlans: List[UnifiedVlan] = []
        
        vlan_root = raw.get("Cisco-IOS-XE-native:vlan") or raw.get("vlan") or raw
        vlan_list = (
            vlan_root.get("Cisco-IOS-XE-vlan:vlan-list", [])
            or vlan_root.get("vlan-list", [])
        )
        
        if not isinstance(vlan_list, list):
            vlan_list = [vlan_list]
        
        for v in vlan_list:
            if not isinstance(v, dict):
                continue
            vlans.append(UnifiedVlan(
                vlan_id=int(v.get("id", 0)),
                name=v.get("name"),
                status="active",
            ))
        
        out = UnifiedVlanList(
            vlans=vlans,
            total_count=len(vlans),
        )
        return out.model_dump()
    
    # =========================================================
    # Huawei
    # =========================================================
    
    def _normalize_huawei_vlans(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Huawei VRP8 VLAN response
        Raw: { "huawei-vlan:vlans": { "vlan": [...] } }
        """
        vlans: List[UnifiedVlan] = []
        
        vlans_root = raw.get("huawei-vlan:vlans") or raw.get("vlans") or raw
        vlan_list = vlans_root.get("vlan", [])
        
        if not isinstance(vlan_list, list):
            vlan_list = [vlan_list]
        
        for v in vlan_list:
            if not isinstance(v, dict):
                continue
            
            status = "active"
            admin_status = v.get("adminStatus", "").lower()
            if admin_status == "down":
                status = "suspended"
            
            vlans.append(UnifiedVlan(
                vlan_id=int(v.get("id", v.get("vlanId", 0))),
                name=v.get("name"),
                status=status,
            ))
        
        out = UnifiedVlanList(
            vlans=vlans,
            total_count=len(vlans),
        )
        return out.model_dump()
    
