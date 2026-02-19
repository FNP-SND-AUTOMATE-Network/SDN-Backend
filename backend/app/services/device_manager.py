"""
DeviceManager — In-memory Capability Cache & Guard

จัดการข้อมูล capabilities ของอุปกรณ์จาก ODL NETCONF topology
ใช้ synchronous `requests` + Basic Auth

Features:
- In-memory Dictionary cache (node_id → capabilities, status, sync time)
- Startup sync: ดึง topology ทั้งหมด + polling สำหรับ non-connected devices
- Capability Guard: ตรวจสอบว่า device รองรับ module ที่ต้องการหรือไม่
- Error Handling: กรอง unavailable-capabilities (unable-to-resolve)

Usage:
    dm = DeviceManager()
    dm.sync_all()                                        # ดึง topology + poll
    dm.is_feature_supported("NE40E-R1", "huawei-ospfv2") # check module
    dm.get_device_status("NE40E-R1")                     # ดูสถานะ
"""

import time
import requests
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app.core.config import settings
from app.core.logging import logger


class DeviceManager:
    """
    จัดการ device capabilities ผ่าน in-memory cache

    Architecture:
        1. sync_all() ดึง topology จาก ODL
        2. Parse capabilities → แยก available / unavailable
        3. Polling loop สำหรับ devices ที่ยัง connecting
        4. is_feature_supported() ตรวจสอบ cache ก่อนส่ง request
    """

    # ── Constructor ──────────────────────────────────────────
    def __init__(
        self,
        odl_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        poll_interval: int = 3,
        poll_max_retries: int = 5,
    ):
        """
        Args:
            odl_url:          ODL base URL (default จาก settings)
            username:         Basic Auth username (default: admin)
            password:         Basic Auth password (default: admin)
            poll_interval:    วินาทีระหว่าง poll รอบ (default: 3)
            poll_max_retries: จำนวนรอบ poll สูงสุด (default: 5)
        """
        self._base_url = (odl_url or settings.ODL_BASE_URL).rstrip("/")
        self._auth = (username or settings.ODL_USERNAME, password or settings.ODL_PASSWORD)
        self._poll_interval = poll_interval
        self._poll_max_retries = poll_max_retries

        # ── In-memory cache ──
        # key: node_id (str)
        # value: {
        #     "available_capabilities":   list[str],
        #     "unavailable_capabilities": list[str],
        #     "connection_status":        str,
        #     "last_sync_time":           str (ISO format)
        # }
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ── HTTP helper (sync, requests) ────────────────────────
    def _request(self, method: str, path: str, json_body: Optional[dict] = None) -> requests.Response:
        """
        ส่ง HTTP request ไปยัง ODL RESTCONF
        ใช้ Basic Auth (admin:admin) ตาม requirement
        """
        url = f"{self._base_url}/rests/data{path}"
        headers = {
            "Accept": "application/yang-data+json",
            "Content-Type": "application/yang-data+json",
        }

        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                auth=self._auth,
                json=json_body,
                timeout=15,
            )
            return resp
        except requests.exceptions.RequestException as e:
            logger.error(f"[DeviceManager] HTTP {method} {url} failed: {e}")
            raise

    # ── Topology sync ───────────────────────────────────────
    def sync_all(self) -> Dict[str, Dict[str, Any]]:
        """
        ดึง topology ทั้งหมดจาก ODL แล้ว cache
        สำหรับ device ที่ยัง connecting จะ poll รอจนกว่าจะ connected

        Returns:
            dict ของ node_id → device info ทั้งหมดที่ sync ได้
        """
        logger.info("[DeviceManager] Starting full topology sync...")

        # GET topology จาก ODL
        path = "/network-topology:network-topology/topology=topology-netconf"
        resp = self._request("GET", path)

        if resp.status_code != 200:
            logger.error(f"[DeviceManager] Failed to fetch topology: {resp.status_code} {resp.text[:200]}")
            return self._cache

        data = resp.json()

        # Parse topology → list of nodes
        topology = data.get("network-topology:topology", [{}])
        if isinstance(topology, list) and len(topology) > 0:
            nodes = topology[0].get("node", [])
        else:
            nodes = []

        logger.info(f"[DeviceManager] Found {len(nodes)} nodes in topology")

        for node_data in nodes:
            node_id = node_data.get("node-id")
            if not node_id:
                continue

            # Skip ODL controller node
            if node_id == "controller-config":
                continue

            # Parse ข้อมูลเบื้องต้น
            status = self._get_connection_status(node_data)

            if status == "connected":
                # Device พร้อมใช้งาน → parse capabilities ทันที
                device_info = self._parse_node(node_data)
                self._cache[node_id] = device_info
                logger.info(
                    f"[DeviceManager] {node_id}: connected "
                    f"({len(device_info['available_capabilities'])} capabilities)"
                )
            else:
                # Device ยัง connecting → poll รอ
                logger.info(f"[DeviceManager] {node_id}: status={status}, starting poll...")
                device_info = self._poll_until_connected(node_id)
                self._cache[node_id] = device_info

        logger.info(f"[DeviceManager] Sync complete. {len(self._cache)} devices cached.")
        return self._cache

    def _poll_until_connected(self, node_id: str) -> Dict[str, Any]:
        """
        Polling loop: รอ device mount + schema load เสร็จ
        ตรวจสอบทุก poll_interval วินาที สูงสุด poll_max_retries รอบ

        Returns:
            device info dict (อาจมี status ≠ connected ถ้า timeout)
        """
        for attempt in range(1, self._poll_max_retries + 1):
            logger.info(
                f"[DeviceManager] Polling {node_id} "
                f"(attempt {attempt}/{self._poll_max_retries})..."
            )
            time.sleep(self._poll_interval)

            # ดึงข้อมูล node เดียว
            path = f"/network-topology:network-topology/topology=topology-netconf/node={node_id}"
            try:
                resp = self._request("GET", path)
            except Exception:
                continue

            if resp.status_code != 200:
                logger.warning(f"[DeviceManager] Poll {node_id}: HTTP {resp.status_code}")
                continue

            data = resp.json()
            node_list = data.get("network-topology:node", data.get("node", []))
            if isinstance(node_list, list) and len(node_list) > 0:
                node_data = node_list[0]
            else:
                continue

            status = self._get_connection_status(node_data)

            if status == "connected":
                device_info = self._parse_node(node_data)
                logger.info(
                    f"[DeviceManager] {node_id}: connected after {attempt} polls "
                    f"({len(device_info['available_capabilities'])} capabilities)"
                )
                return device_info

        # ── timeout: cache สิ่งที่มี (อาจยังไม่ connected) ──
        logger.warning(
            f"[DeviceManager] {node_id}: still not connected after "
            f"{self._poll_max_retries} polls. Caching current state."
        )
        return {
            "available_capabilities": [],
            "unavailable_capabilities": [],
            "connection_status": "timeout",
            "last_sync_time": datetime.now().isoformat(),
        }

    # ── Parse single node ───────────────────────────────────
    def _parse_node(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse node JSON จาก ODL → dict ที่พร้อม cache

        จัดการ:
        - available-capabilities → เก็บเฉพาะ module name
        - unavailable-capabilities → filter ออก, ไม่ include ใน available
        """
        # ── available capabilities ──
        available_raw: List[str] = node_data.get(
            "netconf-node-topology:available-capabilities", {}
        ).get("available-capability", [])

        # Extract module name จาก capability URI
        # format: "(urn:huawei:yang:huawei-ospfv2?revision=2021-03-09)huawei-ospfv2"
        #       หรือ "urn:ietf:params:netconf:base:1.0"
        available_modules = []
        for cap in available_raw:
            module_name = self._extract_module_name(cap)
            if module_name:
                available_modules.append(module_name)

        # ── unavailable capabilities (unable-to-resolve) ──
        unavailable_raw: List[Dict[str, str]] = node_data.get(
            "netconf-node-topology:unavailable-capabilities", {}
        ).get("unavailable-capability", [])

        unavailable_modules = []
        for entry in unavailable_raw:
            # entry อาจเป็น dict: {"capability": "...", "failure-reason": "unable-to-resolve"}
            # หรือเป็น str
            if isinstance(entry, dict):
                cap_str = entry.get("capability", "")
                reason = entry.get("failure-reason", "unknown")
                module = self._extract_module_name(cap_str)
                unavailable_modules.append(f"{module or cap_str} ({reason})")
            elif isinstance(entry, str):
                module = self._extract_module_name(entry)
                unavailable_modules.append(f"{module or entry} (unable-to-resolve)")

        # ── connection status ──
        status = self._get_connection_status(node_data)

        return {
            "available_capabilities": sorted(set(available_modules)),
            "unavailable_capabilities": unavailable_modules,
            "connection_status": status,
            "last_sync_time": datetime.now().isoformat(),
        }

    @staticmethod
    def _extract_module_name(capability_string: str) -> Optional[str]:
        """
        Extract module name จาก NETCONF capability URI

        Formats:
            "(namespace?revision=...)module-name"  →  "module-name"
            "urn:ietf:params:netconf:base:1.0"     →  "urn:ietf:params:netconf:base:1.0"
        """
        if not capability_string:
            return None

        # Format: "(...)module-name"
        if ")" in capability_string:
            return capability_string.rsplit(")", 1)[-1].strip()

        # Plain URN
        return capability_string.strip()

    @staticmethod
    def _get_connection_status(node_data: Dict[str, Any]) -> str:
        """ดึง connection-status จาก node data (lowercase)"""
        return node_data.get(
            "netconf-node-topology:connection-status", "unknown"
        ).lower()

    # ── Capability Guard ────────────────────────────────────
    def is_feature_supported(self, node_id: str, capability_string: str) -> Dict[str, Any]:
        """
        ตรวจสอบว่า device รองรับ module ที่ต้องการหรือไม่

        ตรวจ 3 สิ่ง:
            1. node_id อยู่ใน cache หรือไม่
            2. connection_status == "connected" หรือไม่
            3. capability_string อยู่ใน available_capabilities หรือไม่

        Args:
            node_id:            เช่น "NE40E-R1"
            capability_string:  เช่น "huawei-ospfv2", "huawei-ifm"

        Returns:
            {
                "supported": True/False,
                "reason": "...",         # เหตุผลถ้าไม่รองรับ
                "node_id": "...",
                "capability": "..."
            }
        """
        result = {
            "node_id": node_id,
            "capability": capability_string,
        }

        # 1. ตรวจว่า device อยู่ใน cache
        if node_id not in self._cache:
            result["supported"] = False
            result["reason"] = f"Device '{node_id}' not found in cache. Run sync_all() first."
            return result

        device = self._cache[node_id]

        # 2. ตรวจ connection status
        if device["connection_status"] != "connected":
            result["supported"] = False
            result["reason"] = (
                f"Device '{node_id}' is not connected "
                f"(status: {device['connection_status']}). "
                f"Cannot verify capabilities."
            )
            return result

        # 3. ตรวจว่า capability อยู่ใน available list
        # ค้นหาแบบ substring match (เช่น "huawei-ospfv2" จะ match กับ "huawei-ospfv2")
        found = any(
            capability_string.lower() in cap.lower()
            for cap in device["available_capabilities"]
        )

        if found:
            result["supported"] = True
            result["reason"] = f"Module '{capability_string}' is available on '{node_id}'."
        else:
            result["supported"] = False
            result["reason"] = (
                f"Module '{capability_string}' is NOT available on '{node_id}'. "
                f"Device has {len(device['available_capabilities'])} capabilities loaded."
            )

        return result

    # ── Query Methods ───────────────────────────────────────
    def get_device_status(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Return cached status ของ device

        Returns:
            device info dict หรือ None ถ้าไม่มีใน cache
        """
        return self._cache.get(node_id)

    def get_all_devices(self) -> Dict[str, Dict[str, Any]]:
        """Return cached data ทุก device"""
        return dict(self._cache)

    def get_connected_devices(self) -> List[str]:
        """Return list ของ node_id ที่ connected"""
        return [
            nid for nid, info in self._cache.items()
            if info["connection_status"] == "connected"
        ]

    # ── Refresh single device ───────────────────────────────
    def refresh(self, node_id: str) -> Dict[str, Any]:
        """
        Refresh single device จาก ODL แล้ว update cache

        Args:
            node_id: เช่น "NE40E-R1"

        Returns:
            device info dict (updated)

        Raises:
            ValueError: ถ้า node ไม่พบใน ODL
        """
        logger.info(f"[DeviceManager] Refreshing {node_id}...")

        path = f"/network-topology:network-topology/topology=topology-netconf/node={node_id}"
        resp = self._request("GET", path)

        if resp.status_code == 404:
            # ถ้า node ไม่มีใน ODL → ลบออกจาก cache
            self._cache.pop(node_id, None)
            raise ValueError(f"Node '{node_id}' not found in ODL topology")

        if resp.status_code != 200:
            raise ValueError(f"Failed to refresh '{node_id}': HTTP {resp.status_code}")

        data = resp.json()
        node_list = data.get("network-topology:node", data.get("node", []))
        if isinstance(node_list, list) and len(node_list) > 0:
            node_data = node_list[0]
        else:
            raise ValueError(f"Unexpected response format for '{node_id}'")

        status = self._get_connection_status(node_data)

        if status == "connected":
            device_info = self._parse_node(node_data)
        else:
            # ยัง connecting → poll
            device_info = self._poll_until_connected(node_id)

        self._cache[node_id] = device_info
        logger.info(
            f"[DeviceManager] {node_id} refreshed: "
            f"status={device_info['connection_status']}, "
            f"capabilities={len(device_info['available_capabilities'])}"
        )
        return device_info

    # ── Summary / Debug ─────────────────────────────────────
    def summary(self) -> str:
        """สรุปสถานะทุก device ใน cache (สำหรับ debug/logging)"""
        lines = [f"DeviceManager: {len(self._cache)} devices cached"]
        for nid, info in sorted(self._cache.items()):
            cap_count = len(info["available_capabilities"])
            unavail_count = len(info["unavailable_capabilities"])
            lines.append(
                f"  {nid}: status={info['connection_status']}, "
                f"caps={cap_count}, unavail={unavail_count}, "
                f"synced={info['last_sync_time']}"
            )
        return "\n".join(lines)

    # ── Intent → YANG Module Mapping ────────────────────────
    # Map intent prefix → list of required YANG modules per vendor
    # ใช้สำหรับ post-error diagnosis
    INTENT_MODULE_MAP: Dict[str, Dict[str, List[str]]] = {
        "interface": {
            "cisco":  ["Cisco-IOS-XE-native"],
            "huawei": ["huawei-ifm", "huawei-ip"],
        },
        "routing.ospf": {
            "cisco":  ["Cisco-IOS-XE-ospf"],
            "huawei": ["huawei-ospfv2"],
        },
        "routing.static": {
            "cisco":  ["Cisco-IOS-XE-native"],
            "huawei": ["huawei-staticrt"],
        },
        "routing.default": {
            "cisco":  ["Cisco-IOS-XE-native"],
            "huawei": ["huawei-staticrt"],
        },
        "system": {
            "cisco":  ["Cisco-IOS-XE-native"],
            "huawei": ["huawei-system"],
        },
        "vlan": {
            "cisco":  ["Cisco-IOS-XE-vlan"],
            "huawei": ["huawei-vlan"],
        },
        "dhcp": {
            "cisco":  [],
            "huawei": ["huawei-dhcps"],
        },
        "show": {
            "cisco":  ["Cisco-IOS-XE-native"],
            "huawei": ["huawei-ifm"],
        },
    }

    def _get_required_modules(self, intent: str, vendor: str) -> List[str]:
        """
        หา YANG modules ที่ intent ต้องการ จาก mapping

        ค้นหาจาก prefix ยาวสุดก่อน (เช่น "routing.ospf" ก่อน "routing")
        """
        vendor_key = vendor.lower()
        # สร้าง candidate prefixes จากยาวไปสั้น
        # "routing.ospf.enable" → ["routing.ospf.enable", "routing.ospf", "routing"]
        parts = intent.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if prefix in self.INTENT_MODULE_MAP:
                return self.INTENT_MODULE_MAP[prefix].get(vendor_key, [])
        return []

    # ── Post-Error Diagnosis ────────────────────────────────
    def diagnose_error(
        self, node_id: str, intent: str, vendor: str, odl_error: str = ""
    ) -> Dict[str, Any]:
        """
        Post-error diagnosis: เมื่อ ODL return error แล้ว ตรวจ capabilities
        เพื่อบอกสาเหตุที่ชัดเจนขึ้น

        Performance:
        - Single GET request (timeout 5s, no polling)
        - เฉพาะ error path เท่านั้น (ไม่กระทบ success flow)

        Args:
            node_id:   device ที่ error
            intent:    intent ที่ fail
            vendor:    vendor ของ device
            odl_error: error message จาก ODL

        Returns:
            {
                "diagnosed": True/False,
                "connection_status": "...",
                "missing_modules": [...],
                "suggestion": "...",
                "odl_error": "..."
            }
        """
        diagnosis: Dict[str, Any] = {
            "diagnosed": False,
            "intent": intent,
            "node_id": node_id,
            "odl_error": odl_error[:300],  # Trim error message
        }

        try:
            # ── Single lightweight GET (5s timeout, no polling) ──
            path = (
                "/network-topology:network-topology"
                f"/topology=topology-netconf/node={node_id}"
            )
            url = f"{self._base_url}/rests/data{path}"
            resp = requests.get(
                url,
                auth=self._auth,
                headers={"Accept": "application/yang-data+json"},
                timeout=5,
            )

            if resp.status_code != 200:
                diagnosis["suggestion"] = (
                    f"Cannot reach device '{node_id}' in ODL "
                    f"(HTTP {resp.status_code}). Check if device is mounted."
                )
                return diagnosis

            # Parse response
            data = resp.json()
            node_list = data.get("network-topology:node", data.get("node", []))
            if not isinstance(node_list, list) or len(node_list) == 0:
                diagnosis["suggestion"] = "Unexpected ODL response format."
                return diagnosis

            node_data = node_list[0]

            # Update cache ด้วย (ฟรี เพราะ GET มาแล้ว)
            device_info = self._parse_node(node_data)
            self._cache[node_id] = device_info

            diagnosis["diagnosed"] = True
            diagnosis["connection_status"] = device_info["connection_status"]

            # ── Check connection ──
            if device_info["connection_status"] != "connected":
                diagnosis["suggestion"] = (
                    f"Device '{node_id}' is not connected "
                    f"(status: {device_info['connection_status']}). "
                    f"The request could not be processed."
                )
                return diagnosis

            # ── Check required modules ──
            required = self._get_required_modules(intent, vendor)
            if not required:
                diagnosis["suggestion"] = (
                    f"Device is connected with "
                    f"{len(device_info['available_capabilities'])} capabilities, "
                    f"but no module mapping found for intent '{intent}'. "
                    f"The error may be caused by incorrect payload or path."
                )
                return diagnosis

            missing = []
            for module in required:
                found = any(
                    module.lower() in cap.lower()
                    for cap in device_info["available_capabilities"]
                )
                if not found:
                    missing.append(module)

            diagnosis["required_modules"] = required
            diagnosis["missing_modules"] = missing

            if missing:
                diagnosis["suggestion"] = (
                    f"Device '{node_id}' is missing YANG module(s): "
                    f"{', '.join(missing)}. "
                    f"This device may not support the '{intent}' operation, "
                    f"or the schema was not loaded by ODL."
                )
            else:
                diagnosis["suggestion"] = (
                    f"All required modules ({', '.join(required)}) are available. "
                    f"The error is likely caused by incorrect payload, "
                    f"path parameters, or device-side rejection."
                )

            return diagnosis

        except requests.exceptions.Timeout:
            diagnosis["suggestion"] = (
                f"Diagnosis timed out (5s). ODL may be overloaded."
            )
            return diagnosis
        except Exception as e:
            diagnosis["suggestion"] = f"Diagnosis failed: {str(e)[:200]}"
            return diagnosis
