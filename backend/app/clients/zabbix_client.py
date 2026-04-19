"""
Zabbix JSON-RPC API Client
เรียก Zabbix API เพื่อดึงข้อมูล hosts, items (SNMP), history, problems

Zabbix API ใช้ JSON-RPC 2.0 protocol ผ่าน HTTP POST
Endpoint: http://<zabbix-web>/api_jsonrpc.php

Usage:
    from app.clients.zabbix_client import zabbix_client
    
    hosts = await zabbix_client.get_hosts()
    items = await zabbix_client.get_items(host_id="10001")
    history = await zabbix_client.get_history(item_ids=["12345"])
"""

import httpx
import time
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logging import logger


class ZabbixAPIError(Exception):
    """Raised when Zabbix API returns an error."""
    def __init__(self, code: int, message: str, data: str = ""):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"Zabbix API Error [{code}]: {message} — {data}")


class ZabbixClient:
    """
    Async client for Zabbix JSON-RPC 2.0 API.
    
    Zabbix 7.x: auth ผ่าน HTTP header (Authorization: Bearer <token>)
    ไม่ใส่ auth ใน JSON body อีกแล้ว
    """

    def __init__(self):
        self._request_id = 0

    @property
    def api_url(self) -> str:
        return settings.ZABBIX_API_URL

    @property
    def auth_token(self) -> str:
        return settings.ZABBIX_API_TOKEN

    # ── Generic JSON-RPC caller ──────────────────────────────────

    async def _call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """
        ส่งคำสั่ง JSON-RPC 2.0 ไปยัง Zabbix API
        - สร้าง JSON-RPC payload และแนบ Auth Token ใน HTTP Header
        - รองรับ Zabbix 7.x (ส่ง auth ผ่าน Bearer Token แทน JSON body)
        - คืนค่าเฉพาะ "result" field จาก response
        - Raise ZabbixAPIError ถ้า API ตอบ error กลับมา

        Args:
            method: Zabbix API method (e.g., "host.get", "item.get")
            params: Method parameters

        Returns:
            The "result" field from the JSON-RPC response

        Raises:
            ZabbixAPIError: If the API returns an error
        """
        self._request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._request_id,
        }

        # Zabbix 7.x: ส่ง auth ผ่าน HTTP header แทน JSON body
        headers = {"Content-Type": "application/json-rpc"}
        if method != "apiinfo.version":
            headers["Authorization"] = f"Bearer {self.auth_token}"

        logger.debug(f"[ZabbixAPI] Calling {method} (id={self._request_id})")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                )

            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                err = data["error"]
                raise ZabbixAPIError(
                    code=err.get("code", -1),
                    message=err.get("message", "Unknown"),
                    data=err.get("data", ""),
                )

            logger.debug(f"[ZabbixAPI] {method} OK — {len(str(data.get('result', '')))} chars")
            return data.get("result")

        except httpx.HTTPStatusError as e:
            logger.error(f"[ZabbixAPI] HTTP error calling {method}: {e}")
            raise ZabbixAPIError(-1, f"HTTP {e.response.status_code}", str(e))
        except httpx.RequestError as e:
            logger.error(f"[ZabbixAPI] Connection error calling {method}: {e}")
            raise ZabbixAPIError(-1, "Connection failed", str(e))

    # ── API Info ─────────────────────────────────────────────────

    async def get_api_version(self) -> str:
        """ดึงเวอร์ชัน Zabbix API (ไม่ต้อง auth) — ใช้สำหรับ Health Check การเชื่อมต่อ"""
        return await self._call("apiinfo.version")

    # ── Hosts ────────────────────────────────────────────────────

    async def get_hosts(
        self,
        group_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        ดึงรายการ Hosts ทั้งหมดที่อยู่ใน Zabbix Monitoring
        - รองรับการกรองตาม group_ids และค้นหาตามชื่อ
        - คืนข้อมูล hostid, host, name, status, interfaces[], groups[]
        """
        params: Dict[str, Any] = {
            "output": [
                "hostid", "host", "name", "status", "description",
            ],
            "selectInterfaces": [
                "interfaceid", "ip", "dns", "port", "type", "main", "available",
            ],
            "selectHostGroups": ["groupid", "name"],
            "sortfield": "name",
        }

        if group_ids:
            params["groupids"] = group_ids
        if search:
            params["search"] = {"name": search}

        return await self._call("host.get", params)

    async def get_host(self, host_id: str) -> Optional[Dict[str, Any]]:
        """ดึงข้อมูล Host เดี่ยวตาม host_id พร้อม interfaces, groups, templates"""
        params = {
            "output": "extend",
            "hostids": [host_id],
            "selectInterfaces": "extend",
            "selectHostGroups": ["groupid", "name"],
            "selectParentTemplates": ["templateid", "name"],
        }
        result = await self._call("host.get", params)
        return result[0] if result else None

    # ── Host Groups ──────────────────────────────────────────────

    async def get_host_groups(self) -> List[Dict[str, Any]]:
        """ดึงรายการ Host Groups ทั้งหมดที่มี Host อยู่ในกลุ่ม"""
        return await self._call("hostgroup.get", {
            "output": ["groupid", "name"],
            "sortfield": "name",
            "with_hosts": True,  # Only groups that have hosts
        })

    # ── Items (SNMP data points) ─────────────────────────────────

    async def get_items(
        self,
        host_id: Optional[str] = None,
        host_ids: Optional[List[str]] = None,
        search_key: Optional[str] = None,
        item_type: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        ดึงรายการ Items (จุดเก็บข้อมูล SNMP/Agent) ของ Host
        - รองรับการกรองตาม host_id/host_ids, key และ item_type

        item_type values:
            0 = Zabbix agent
            2 = Zabbix trapper
            4 = SNMP agent (SNMPv1/v2/v3)
            20 = SNMP trap

        For SNMP items, use item_type=4
        """
        params: Dict[str, Any] = {
            "output": [
                "itemid", "name", "key_", "type", "value_type",
                "lastvalue", "lastclock", "units", "description",
                "status", "state", "error", "hostid"
            ],
            "sortfield": "name",
            "limit": limit,
            "filter": {"status": "0"},  # Only enabled items
        }

        if host_ids:
            params["hostids"] = host_ids
        elif host_id:
            params["hostids"] = [host_id]

        if search_key:
            params["search"] = {"key_": search_key}
        if item_type is not None:
            params["filter"]["type"] = str(item_type)

        return await self._call("item.get", params)

    async def get_snmp_items(self, host_id: Optional[str] = None, host_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        ดึงเฉพาะ SNMP Items (type=4 + type=20) เพื่อรองรับทั้ง Zabbix เก่าและใหม่
        - Type 4 = SNMP agent ใน Zabbix < 6.0
        - Type 20 = SNMP agent ใน Zabbix 6.0+
        """
        # Type 20 = SNMP agent ใน Zabbix 6.0+
        # Type 4 = SNMP agent ใน Zabbix < 6.0
        # ดึงทั้ง type 4 และ 20 เพื่อ compatibility
        items_v2 = await self.get_items(host_id=host_id, host_ids=host_ids, item_type=4)
        items_v3 = await self.get_items(host_id=host_id, host_ids=host_ids, item_type=20)
        return items_v2 + items_v3

    async def get_items_by_tag(
        self,
        host_ids: List[str],
        tag: str,
        value: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetch items filtered by Zabbix tag.

        ใช้สำหรับดึง items ตาม tag "component" เช่น cpu, memory, network
        ซึ่ง Zabbix Template จะติด tag ไว้ให้อัตโนมัติ

        Args:
            host_ids: List of host IDs to query
            tag:      Tag name (e.g. "component")
            value:    Tag value (e.g. "cpu", "memory", "network")
        """
        params: Dict[str, Any] = {
            "output": ["itemid", "name", "lastvalue", "lastclock", "units", "key_", "hostid"],
            "hostids": host_ids,
            "tags": [
                {"tag": tag, "value": value}
            ],
            "filter": {"status": "0"},  # Only enabled items
            "sortfield": "name",
        }
        return await self._call("item.get", params)

    # ── History ──────────────────────────────────────────────────

    async def get_history(
        self,
        item_ids: List[str],
        history_type: int = 0,
        time_from: Optional[int] = None,
        time_till: Optional[int] = None,
        limit: int = 100,
        sort_order: str = "DESC",
    ) -> List[Dict[str, Any]]:
        """
        ดึงข้อมูลย้อนหลังของ Items ตามช่วงเวลาที่กำหนด
        - ใช้แสดงกราฟ Traffic, CPU, Memory ย้อนหลัง

        history_type:
            0 = numeric float
            1 = character
            2 = log
            3 = numeric unsigned
            4 = text

        For traffic counters (ifInOctets, ifOutOctets), use type=3 (unsigned).
        For CPU/memory percentages, use type=0 (float).
        """
        params: Dict[str, Any] = {
            "output": "extend",
            "itemids": item_ids,
            "history": history_type,
            "sortfield": "clock",
            "sortorder": sort_order,
            "limit": limit,
        }

        if time_from is not None:
            params["time_from"] = time_from
        if time_till is not None:
            params["time_till"] = time_till

        return await self._call("history.get", params)

    # ── Trends (for longer time periods) ─────────────────────────

    async def get_trends(
        self,
        item_ids: List[str],
        time_from: Optional[int] = None,
        time_till: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        ดึงข้อมูล Trend (สรุปรายชั่วโมง) สำหรับข้อมูลย้อนหลัง > 1 วัน
        - Zabbix จะสรุปข้อมูลรายชั่วโมงอัตโนมัติ (avg, min, max, count)
        """
        params: Dict[str, Any] = {
            "output": "extend",
            "itemids": item_ids,
            "sortfield": "clock",
            "sortorder": "ASC",
            "limit": limit,
        }

        if time_from is not None:
            params["time_from"] = time_from
        if time_till is not None:
            params["time_till"] = time_till

        return await self._call("trend.get", params)

    # ── Problems / Triggers ──────────────────────────────────────

    async def get_problems(
        self,
        severity_min: int = 0,
        host_ids: Optional[List[str]] = None,
        limit: int = 100,
        recent: bool = True,
        time_from: Optional[int] = None,
        time_till: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        ดึงรายการปัญหา (Problems) ที่ยังไม่แก้ไข (Active)
        - กรองตามระดับความรุนแรง (severity) และช่วงเวลา

        severity: 0=Not classified, 1=Info, 2=Warning, 
                  3=Average, 4=High, 5=Disaster
        """
        params: Dict[str, Any] = {
            "output": "extend",
            "selectTags": "extend",
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": limit,
            "recent": recent,
            "severities": list(range(severity_min, 6)),
        }

        if host_ids:
            params["hostids"] = host_ids
        if time_from is not None:
            params["time_from"] = time_from
        if time_till is not None:
            params["time_till"] = time_till

        return await self._call("problem.get", params)

    async def get_problems_count(
        self,
        severity_min: int = 0,
        host_ids: Optional[List[str]] = None,
        recent: bool = True,
        time_from: Optional[int] = None,
        time_till: Optional[int] = None,
    ) -> int:
        """นับจำนวน Problems ทั้งหมด (ไม่จำกัด limit) สำหรับใช้แสดงจำนวนรวมบน Dashboard"""
        params: Dict[str, Any] = {
            "countOutput": True,
            "recent": recent,
            "severities": list(range(severity_min, 6)),
        }

        if host_ids:
            params["hostids"] = host_ids
        if time_from is not None:
            params["time_from"] = time_from
        if time_till is not None:
            params["time_till"] = time_till

        result = await self._call("problem.get", params)
        try:
            return int(result)
        except (TypeError, ValueError):
            return 0

    async def get_triggers(
        self,
        host_ids: Optional[List[str]] = None,
        only_active: bool = True,
        min_severity: int = 0,
    ) -> List[Dict[str, Any]]:
        """ดึงรายการ Triggers พร้อมข้อมูล Host ที่เกี่ยวข้อง สำหรับดูว่า Host ไหนมีปัญหาอยู่"""
        params: Dict[str, Any] = {
            "output": [
                "triggerid", "description", "priority", "value",
                "lastchange", "status", "state",
            ],
            "selectHosts": ["hostid", "name"],
            "selectItems": ["itemid", "name", "key_", "lastvalue"],
            "sortfield": "priority",
            "sortorder": "DESC",
            "min_severity": min_severity,
        }

        if only_active:
            params["filter"] = {"value": 1}  # 1 = PROBLEM state
        if host_ids:
            params["hostids"] = host_ids

        return await self._call("trigger.get", params)


# ── Singleton ────────────────────────────────────────────────────
zabbix_client = ZabbixClient()
