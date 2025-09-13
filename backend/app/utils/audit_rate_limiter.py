import time
from typing import Dict, Tuple
from datetime import datetime, timedelta

class AuditRateLimiter:
    """
    Rate limiter สำหรับ audit logs เพื่อป้องกันการสร้าง logs เยอะเกินไป
    """
    
    def __init__(self):
        # เก็บ cache ของ audit logs ล่าสุด: {user_id: {action: timestamp}}
        self._last_audit_cache: Dict[str, Dict[str, float]] = {}
        
        # กำหนดระยะเวลาขั้นต่ำระหว่าง audit logs แต่ละประเภท (วินาที)
        self._rate_limits = {
            "USER_VIEW_PROFILE": 300,  # 5 นาที
            "USER_VIEW_DETAIL": 60,    # 1 นาที
            "USER_LIST": 30,           # 30 วินาที
            # Operations ที่สำคัญจะไม่มี rate limit
            "USER_CREATE": 0,
            "USER_UPDATE": 0,
            "USER_DELETE": 0,
            "USER_LOGIN": 0,
            "USER_REGISTER": 0,
            "PASSWORD_CHANGE": 0,
            "ROLE_PROMOTION": 0
        }
    
    def should_create_audit_log(self, user_id: str, action: str, operation_type: str = None) -> bool:
        """
        ตรวจสอบว่าควรสร้าง audit log หรือไม่
        
        Args:
            user_id: ID ของ user
            action: action type (เช่น USER_VIEW)
            operation_type: ประเภทของ operation เฉพาะ (เช่น "profile", "detail")
        
        Returns:
            True หากควรสร้าง audit log
        """
        current_time = time.time()
        
        # สร้าง key สำหรับ cache
        if operation_type:
            cache_key = f"{action}_{operation_type.upper()}"
        else:
            cache_key = action
        
        # ตรวจสอบ rate limit
        rate_limit = self._rate_limits.get(cache_key, 0)
        
        # หากไม่มี rate limit (เป็น 0) ให้สร้าง audit log เสมอ
        if rate_limit == 0:
            return True
        
        # ตรวจสอบ cache
        if user_id not in self._last_audit_cache:
            self._last_audit_cache[user_id] = {}
        
        user_cache = self._last_audit_cache[user_id]
        
        # ตรวจสอบว่าผ่านเวลาขั้นต่ำแล้วหรือไม่
        if cache_key in user_cache:
            time_diff = current_time - user_cache[cache_key]
            if time_diff < rate_limit:
                return False  # ยังไม่ถึงเวลา
        
        # อัปเดต timestamp
        user_cache[cache_key] = current_time
        
        # ทำความสะอาด cache เก่า (เก็บแค่ 1 ชั่วโมงล่าสุด)
        self._cleanup_cache(current_time)
        
        return True
    
    def _cleanup_cache(self, current_time: float):
        """ทำความสะอาด cache ที่เก่าเกินไป"""
        cleanup_threshold = current_time - 3600  # 1 ชั่วโมง
        
        users_to_remove = []
        for user_id, user_cache in self._last_audit_cache.items():
            actions_to_remove = []
            for action, timestamp in user_cache.items():
                if timestamp < cleanup_threshold:
                    actions_to_remove.append(action)
            
            # ลบ actions เก่า
            for action in actions_to_remove:
                del user_cache[action]
            
            # หาก user ไม่มี actions เหลือ ให้ลบ user
            if not user_cache:
                users_to_remove.append(user_id)
        
        # ลบ users ที่ไม่มี cache เหลือ
        for user_id in users_to_remove:
            del self._last_audit_cache[user_id]
    
    def force_reset_user_cache(self, user_id: str, action: str = None):
        """รีเซ็ต cache ของ user เฉพาะ action (สำหรับ testing)"""
        if user_id in self._last_audit_cache:
            if action:
                self._last_audit_cache[user_id].pop(action, None)
            else:
                del self._last_audit_cache[user_id]

# Global instance
audit_rate_limiter = AuditRateLimiter()
