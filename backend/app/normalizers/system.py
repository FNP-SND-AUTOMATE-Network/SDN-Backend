"""
System Normalizer
แปลง vendor-specific system response เป็น Unified format
"""
from typing import Any, Dict
from app.schemas.unified import UnifiedSystemInfo, UnifiedRunningConfig


class SystemNormalizer:
    """
    Normalize system responses from different vendors to unified format
    """
    
    def normalize_show_version(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize show version response"""
        if driver_used == "openconfig":
            return self._normalize_openconfig_version(raw)
        
        if driver_used == "cisco":
            return self._normalize_cisco_version(raw)
        
        if driver_used == "huawei":
            return self._normalize_huawei_version(raw)

        return {"vendor": driver_used, "raw": raw}
    
    def normalize_show_running_config(self, driver_used: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize running config response"""
        # Running config ไม่ต้อง normalize มาก - ส่ง JSON กลับไปเลย
        # แต่จัดรูปแบบให้สวยงาม
        
        import json
        config_text = json.dumps(raw, indent=2)
        
        out = UnifiedRunningConfig(
            config_text=config_text,
            section=None
        )
        return out.model_dump()
    
    # ===== OpenConfig Normalizers =====
    
    def _normalize_openconfig_version(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize OpenConfig system state"""
        state = raw.get("openconfig-system:state") or raw.get("state") or raw
        
        out = UnifiedSystemInfo(
            hostname=state.get("hostname", "unknown"),
            vendor="openconfig",
            model=state.get("hardware", {}).get("model"),
            serial_number=state.get("hardware", {}).get("serial-number"),
            software_version=state.get("software-version"),
            uptime=state.get("boot-time"),
        )
        return out.model_dump()
    
    # ===== Cisco Normalizers =====
    
    def _normalize_cisco_version(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Cisco version info"""
        native = raw.get("Cisco-IOS-XE-native:native") or raw
        version = native.get("version") or raw.get("Cisco-IOS-XE-native:version")
        
        out = UnifiedSystemInfo(
            hostname=native.get("hostname", "unknown"),
            vendor="cisco",
            model=native.get("license", {}).get("udi", {}).get("pid"),
            serial_number=native.get("license", {}).get("udi", {}).get("sn"),
            software_version=str(version) if version else None,
        )
        return out.model_dump()
    
    # ===== Huawei Normalizers =====
    
    def _normalize_huawei_version(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Huawei version info"""
        system = raw.get("huawei-system:system") or raw
        
        out = UnifiedSystemInfo(
            hostname=system.get("hostName", "unknown"),
            vendor="huawei",
            model=system.get("productName"),
            serial_number=system.get("esn"),
            software_version=system.get("vrpVersion"),
            uptime=system.get("upTime"),
        )
        return out.model_dump()
