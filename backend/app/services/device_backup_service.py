"""
Device Backup Service
บริการสำรอง Configuration จริงของอุปกรณ์ผ่าน Scrapli (SSH/Telnet)

หน้าที่หลัก:
- เชื่อมต่อ SSH/Telnet ไปยังอุปกรณ์และดึง Running Config
- สร้าง Diff ระหว่าง Config เก่าและใหม่ (ใช้ difflib)
- สร้าง Content Hash เพื่อตรวจสอบการเปลี่ยนแปลง
- บันทึกผลลง Database (เนื้อหา Config, Hash, Diff, สถานะ)
- รองรับทั้ง Cisco และ Huawei ผ่าน Scrapli async driver
"""

from typing import List, Optional, Tuple, Dict, Any
import asyncio
import hashlib
import re
import time
from datetime import datetime
import difflib

from scrapli import AsyncScrapli
from scrapli.exceptions import ScrapliException

import logging

# ====== Add Scrapli Logging ======
scrapli_logger = logging.getLogger("scrapli")
scrapli_logger.setLevel(logging.DEBUG)
if scrapli_logger.hasHandlers():
    scrapli_logger.handlers.clear()
file_handler = logging.FileHandler("scrapli_backup_debug.log")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
scrapli_logger.addHandler(file_handler)
# =================================

# Import Prisma client and Enums based on your schema
from prisma.enums import ConfigType, ConfigFormat, BackupJobStatus, DeviceVendor

from app.services.device_credentials_service import DeviceCredentialsService

# Huawei prompt line matcher used by manual asyncssh shell fallback.
HUAWEI_PROMPT_LINE_PATTERN = (
    r"(?im)^(?:"
    r"(?:hrp_[ams])?<[a-z0-9.\-_@()/:]{1,64}>"
    r"|"
    r"(?!\[V\d{3}R\d{3}C\d{2,3}.*\])(?:hrp_[ams])?\[~?\*?[a-z0-9.\-_@/:]{1,64}\]"
    r")\s*$"
)

async def huawei_bypass_on_open(conn: Any) -> None:
    """
    Scrapli on_open callback for Huawei VRP devices.

    Huawei devices often greet the user with a password-change prompt right
    after a successful SSH login, before the normal shell prompt appears:

        The password needs to be changed. Change now? [Y/N]:

    This callback reads all buffered output after the SSH handshake and, if
    that prompt is detected, sends "n<Enter>" to skip the change.

    Additionally, terminal paging is disabled with "screen-length 0 temporary"
    so that long outputs (e.g. display current-configuration) are not cut off.
    """
    def _safe_write(payload: str) -> bool:
        """Write to channel and suppress early-open channel state errors."""
        try:
            conn.channel.write(payload)
            return True
        except Exception:
            return False

    async def _drain_channel(max_reads: int = 6, timeout: float = 0.8) -> str:
        """Read pending channel output without relying on read_until_prompt()."""
        chunks: List[str] = []
        for _ in range(max_reads):
            try:
                raw = await asyncio.wait_for(conn.channel.read(65535), timeout=timeout)
            except (asyncio.TimeoutError, Exception):
                break

            if not raw:
                break

            if isinstance(raw, bytes):
                chunks.append(raw.decode("utf-8", errors="ignore"))
            else:
                chunks.append(str(raw))

        return "".join(chunks)

    # Give the device a moment to flush its post-login banner / prompts
    await asyncio.sleep(1.0)
    buffered = await _drain_channel(max_reads=4, timeout=1.0)

    # Detect the Huawei password-change prompt (several known variants)
    change_triggers = [
        "change now?",
        "change password",
        "[y/n]:",
        "[y/n] :",
        "password needs to be changed",
        "old password",
    ]
    needs_bypass = any(t in buffered.lower() for t in change_triggers)

    if needs_bypass:
        # Send "n" + Enter to decline the password change
        if not _safe_write("n\n"):
            return
        await asyncio.sleep(0.4)
        # Drain any follow-up output the device sends after our answer
        await _drain_channel(max_reads=6, timeout=0.8)

    # Nudge the device to present a fresh prompt and clear pending output
    if not _safe_write("\n"):
        return
    await asyncio.sleep(0.2)
    await _drain_channel(max_reads=3, timeout=0.5)

    # Disable terminal paging so long outputs are not truncated
    if not _safe_write("screen-length 0 temporary\n"):
        return
    await asyncio.sleep(0.2)
    await _drain_channel(max_reads=4, timeout=0.6)


class DeviceBackupService:
    """
    Service for executing configuration backups from network devices using Scrapli.
    Handles SSH connection, command execution, diffs, and saving DeviceBackupRecords.
    """
    # Process-wide cache for Huawei strategy per host to avoid repeated timeout-heavy attempts.
    _huawei_strategy_cache: Dict[str, str] = {}

    def __init__(self, prisma_client):
        self.prisma = prisma_client
        self.credential_service = DeviceCredentialsService(prisma_client)

    def map_vendor_to_scrapli_driver(self, vendor: DeviceVendor) -> str:
        """Map generic DeviceVendor enum to Scrapli's specific driver names."""
        mapping = {
            DeviceVendor.CISCO: "cisco_iosxe", # Default to iosxe, could expand logic later
            DeviceVendor.HUAWEI: "huawei_vrp",
            # DeviceVendor.JUNIPER: "juniper_junos",
            # DeviceVendor.ARISTA: "arista_eos",
        }
        return mapping.get(vendor, "cisco_iosxe")

    def _build_asyncssh_options(self, request_pty: Optional[bool] = None) -> Dict[str, Any]:
        """Build asyncssh transport options shared by Scrapli and raw asyncssh fallback."""
        options: Dict[str, Any] = {
            "server_host_key_algs": [
                "ssh-rsa",
                "ssh-dss",
                "rsa-sha2-256",
                "rsa-sha2-512",
                "ecdsa-sha2-nistp256",
                "ecdsa-sha2-nistp384",
                "ecdsa-sha2-nistp521",
                "ssh-ed25519"
            ],
            "kex_algs": [
                "diffie-hellman-group1-sha1",
                "diffie-hellman-group14-sha1",
                "diffie-hellman-group-exchange-sha1",
                "diffie-hellman-group-exchange-sha256",
                "curve25519-sha256",
                "curve25519-sha256@libssh.org"
            ]
        }
        if request_pty is not None:
            options["request_pty"] = request_pty
        return options

    def _build_connection_attempts(
        self,
        device: Any,
        username: str,
        password: str,
        timeout_socket: float,
        timeout_transport: float,
        timeout_ops: float
    ) -> List[Dict[str, Any]]:
        """Build ordered connection attempts; Huawei gets extra fallbacks."""
        scrapli_driver = self.map_vendor_to_scrapli_driver(device.vendor)

        base_device_dict: Dict[str, Any] = {
            "host": device.netconf_host,
            "platform": scrapli_driver,
            "port": 22,
            "auth_username": username,
            "auth_password": password,
            "auth_strict_key": False,
            "transport": "asyncssh",
            "timeout_socket": timeout_socket,
            "timeout_transport": timeout_transport,
            "timeout_ops": timeout_ops,
        }

        def _make_attempt(
            label: str,
            *,
            request_pty: Optional[bool] = None,
            auth_bypass: Optional[bool] = None,
        ) -> Dict[str, Any]:
            asyncssh_options = self._build_asyncssh_options(request_pty=request_pty)

            device_dict = dict(base_device_dict)
            device_dict["transport_options"] = {
                "asyncssh": asyncssh_options
            }

            if auth_bypass is not None:
                device_dict["auth_bypass"] = auth_bypass

            return {
                "label": label,
                "device_dict": device_dict
            }

        if device.vendor == DeviceVendor.HUAWEI:
            return [
                _make_attempt("huawei-default"),
                _make_attempt("huawei-no-pty", request_pty=False),
                _make_attempt("huawei-auth-bypass", auth_bypass=True),
                _make_attempt(
                    "huawei-auth-bypass-no-pty",
                    request_pty=False,
                    auth_bypass=True,
                ),
            ]

        return [_make_attempt("default")]

    @staticmethod
    def _decode_shell_chunk(chunk: Any) -> str:
        if isinstance(chunk, bytes):
            return chunk.decode("utf-8", errors="ignore")
        return str(chunk)

    @staticmethod
    async def _write_shell_input(process: Any, payload: str) -> None:
        process.stdin.write(payload)
        drain = getattr(process.stdin, "drain", None)
        if callable(drain):
            await drain()

    @classmethod
    async def _read_shell_output(cls, process: Any, timeout: float = 0.8, max_reads: int = 3) -> str:
        chunks: List[str] = []
        for _ in range(max_reads):
            try:
                chunk = await asyncio.wait_for(process.stdout.read(4096), timeout=timeout)
            except asyncio.TimeoutError:
                break

            if not chunk:
                break

            chunks.append(cls._decode_shell_chunk(chunk))

        return "".join(chunks)

    async def _read_until_huawei_prompt(
        self,
        process: Any,
        timeout_seconds: float,
        initial_buffer: str = ""
    ) -> str:
        """Read shell output until a Huawei prompt line is observed."""
        prompt_re = re.compile(HUAWEI_PROMPT_LINE_PATTERN)
        buffer = initial_buffer
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            if prompt_re.search(buffer):
                return buffer

            chunk = await self._read_shell_output(process, timeout=1.0, max_reads=1)
            if chunk:
                buffer += chunk
                continue

            await asyncio.sleep(0.05)

        raise TimeoutError("timed out waiting for Huawei prompt")

    async def _read_huawei_command_until_prompt(
        self,
        process: Any,
        command: str,
        timeout_seconds: float,
    ) -> str:
        """Read until prompt, but only after the target command appears in output."""
        prompt_re = re.compile(HUAWEI_PROMPT_LINE_PATTERN)
        command_lc = command.strip().lower()
        buffer = ""
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            chunk = await self._read_shell_output(process, timeout=1.0, max_reads=1)
            if chunk:
                buffer += chunk

            lower_buffer = buffer.lower()
            command_pos = lower_buffer.find(command_lc)

            if command_pos != -1:
                tail = buffer[command_pos + len(command_lc):]
                if prompt_re.search(tail):
                    return buffer

            await asyncio.sleep(0.05)

        raise TimeoutError("timed out waiting for command output and prompt")

    @staticmethod
    def _extract_huawei_command_output(raw_output: str, command: str) -> str:
        """Trim command echo and trailing prompt from raw Huawei shell output."""
        output = raw_output.replace("\r", "")

        lower_output = output.lower()
        lower_command = command.lower()
        command_pos = lower_output.find(lower_command)

        if command_pos != -1:
            output = output[command_pos + len(command):]
        else:
            # In this fallback path we expect to see command echo.
            # If absent, avoid returning stale output from previous commands.
            if not re.search(r"(?im)^\s*sysname\s+\S+", output):
                return ""

        lines = output.splitlines()
        while lines and not lines[-1].strip():
            lines.pop()

        if lines and re.search(HUAWEI_PROMPT_LINE_PATTERN, lines[-1]):
            lines.pop()

        return "\n".join(lines).strip()

    async def _send_huawei_command_via_asyncssh(
        self,
        host: str,
        username: str,
        password: str,
        command: str,
        timeout_socket: float,
        timeout_ops: float,
    ) -> str:
        """Last-resort Huawei shell execution that bypasses Scrapli prompt negotiation."""
        try:
            import asyncssh
        except Exception as e:
            raise Exception(f"asyncssh unavailable: {str(e)}")

        prompt_ready_timeout = max(8.0, min(timeout_ops, 20.0))
        command_timeout = max(20.0, timeout_ops)

        errors: List[str] = []
        for use_pty in (True, False):
            attempt_label = "huawei-asyncssh-pty" if use_pty else "huawei-asyncssh-no-pty"
            try:
                asyncssh_options = self._build_asyncssh_options()
                connect_kwargs = {
                    "host": host,
                    "username": username,
                    "password": password,
                    "known_hosts": None,
                    "server_host_key_algs": asyncssh_options["server_host_key_algs"],
                    "kex_algs": asyncssh_options["kex_algs"],
                    "connect_timeout": timeout_socket,
                }

                async with asyncssh.connect(**connect_kwargs) as conn:
                    if use_pty:
                        process = await conn.create_process(term_type="vt100", term_size=(200, 50))
                    else:
                        process = await conn.create_process()

                    await asyncio.sleep(0.5)
                    buffered = await self._read_shell_output(process, timeout=0.8, max_reads=5)

                    if re.search(r"(?im)change\s+now\?\s*\[y/n\]:", buffered):
                        await self._write_shell_input(process, "n\n")
                        await asyncio.sleep(0.3)
                        buffered += await self._read_shell_output(process, timeout=0.8, max_reads=5)

                    await self._write_shell_input(process, "\n")
                    await self._read_until_huawei_prompt(
                        process,
                        timeout_seconds=prompt_ready_timeout,
                        initial_buffer=buffered,
                    )

                    await self._write_shell_input(process, "screen-length 0 temporary\n")
                    await self._read_until_huawei_prompt(
                        process,
                        timeout_seconds=prompt_ready_timeout,
                    )

                    # Clear any residual output so next read is tied to target command.
                    await self._write_shell_input(process, "\n")
                    await self._read_until_huawei_prompt(
                        process,
                        timeout_seconds=prompt_ready_timeout,
                    )
                    await self._read_shell_output(process, timeout=0.2, max_reads=2)

                    await self._write_shell_input(process, f"{command}\n")
                    raw_command_output = await self._read_huawei_command_until_prompt(
                        process,
                        command=command,
                        timeout_seconds=command_timeout,
                    )

                    cleaned_output = self._extract_huawei_command_output(raw_command_output, command)
                    if not cleaned_output:
                        raise Exception("command completed but output is empty")

                    await self._write_shell_input(process, "quit\n")
                    return cleaned_output
            except Exception as e:
                errors.append(f"{attempt_label}: {str(e)}")

        raise Exception("; ".join(errors) if errors else "asyncssh shell fallback failed")

    async def _send_command_with_fallback(
        self,
        device: Any,
        username: str,
        password: str,
        command: str,
        timeout_socket: float,
        timeout_transport: float,
        timeout_ops: float,
    ) -> str:
        """Try command execution with ordered connection fallbacks."""
        host = getattr(device, "netconf_host", "")
        preferred_strategy = self._huawei_strategy_cache.get(host) if device.vendor == DeviceVendor.HUAWEI else None

        attempts = self._build_connection_attempts(
            device=device,
            username=username,
            password=password,
            timeout_socket=timeout_socket,
            timeout_transport=timeout_transport,
            timeout_ops=timeout_ops,
        )

        if preferred_strategy and preferred_strategy != "huawei-asyncssh-shell":
            attempts = sorted(
                attempts,
                key=lambda a: 0 if a["label"] == preferred_strategy else 1,
            )

        errors: List[str] = []

        async def _run_scrapli_attempt(attempt: Dict[str, Any]) -> Optional[str]:
            try:
                async with AsyncScrapli(**attempt["device_dict"]) as conn:
                    response = await conn.send_command(command)
                    if device.vendor == DeviceVendor.HUAWEI and host:
                        self._huawei_strategy_cache[host] = attempt["label"]
                    return response.result
            except Exception as e:
                errors.append(f"{attempt['label']}: {str(e)}")
                return None

        if device.vendor == DeviceVendor.HUAWEI and preferred_strategy == "huawei-asyncssh-shell":
            try:
                result = await self._send_huawei_command_via_asyncssh(
                    host=device.netconf_host,
                    username=username,
                    password=password,
                    command=command,
                    timeout_socket=timeout_socket,
                    timeout_ops=timeout_ops,
                )
                if host:
                    self._huawei_strategy_cache[host] = "huawei-asyncssh-shell"
                return result
            except Exception as e:
                errors.append(f"huawei-asyncssh-shell: {str(e)}")

        if device.vendor == DeviceVendor.HUAWEI and not preferred_strategy and attempts:
            # Fast path: try one Scrapli profile, then asyncssh shell before exhausting all profiles.
            first_attempt = attempts[0]
            first_result = await _run_scrapli_attempt(first_attempt)
            if first_result is not None:
                return first_result

            try:
                result = await self._send_huawei_command_via_asyncssh(
                    host=device.netconf_host,
                    username=username,
                    password=password,
                    command=command,
                    timeout_socket=timeout_socket,
                    timeout_ops=timeout_ops,
                )
                if host:
                    self._huawei_strategy_cache[host] = "huawei-asyncssh-shell"
                return result
            except Exception as e:
                errors.append(f"huawei-asyncssh-shell: {str(e)}")

            # Continue remaining Scrapli attempts only if shell fast-path failed.
            attempts = attempts[1:]

        for attempt in attempts:
            result = await _run_scrapli_attempt(attempt)
            if result is not None:
                return result

        if device.vendor == DeviceVendor.HUAWEI:
            try:
                result = await self._send_huawei_command_via_asyncssh(
                    host=device.netconf_host,
                    username=username,
                    password=password,
                    command=command,
                    timeout_socket=timeout_socket,
                    timeout_ops=timeout_ops,
                )
                if host:
                    self._huawei_strategy_cache[host] = "huawei-asyncssh-shell"
                return result
            except Exception as e:
                errors.append(f"huawei-asyncssh-shell: {str(e)}")

        raise ScrapliException("; ".join(errors) if errors else "Unable to open Scrapli connection")

    def _get_backup_command(self, vendor: DeviceVendor, config_type: ConfigType) -> str:
        """Get the correct CLI command to fetch configuration based on vendor."""
        is_startup = (config_type == ConfigType.STARTUP)
        
        if vendor == DeviceVendor.HUAWEI:
            return "display saved-configuration" if is_startup else "display current-configuration"
        # elif vendor == DeviceVendor.JUNIPER:
        #     return "show configuration"
        
        return "show startup-config" if is_startup else "show running-config"

    async def execute_single_backup_async(
        self, 
        record_id: str, 
        device_id: str, 
        user_id: Optional[str] = None,
        config_type: ConfigType = ConfigType.RUNNING,
        semaphore: Optional[asyncio.Semaphore] = None
    ) -> Any:
        """
        Executes backup for an already created IN_PROGRESS record.
        """
        async def _execute():
            err_msg = ""
            config_content = ""
            status = BackupJobStatus.IN_PROGRESS
            hash_val = ""

            device = await self.prisma.devicenetwork.find_unique(where={"id": device_id})

            try:
                if not device:
                    raise Exception("Device not found in database")
                if not device.netconf_host:
                    raise Exception("Device does not have a management IP (netconf_host) configured")

                if not user_id:
                    raise Exception("Require user_id to fetch credentials")

                creds = await self.prisma.devicecredentials.find_unique(where={"userId": user_id})
                if not creds:
                     raise Exception("No Device Credentials found for this user")

                username = creds.deviceUsername
                password = self.credential_service.decrypt_password(creds.devicePasswordHash)
                command = self._get_backup_command(device.vendor, config_type)

                config_content = await self._send_command_with_fallback(
                    device=device,
                    username=username,
                    password=password,
                    command=command,
                    timeout_socket=30.0,
                    timeout_transport=30.0,
                    timeout_ops=30.0,
                )
                status = BackupJobStatus.SUCCESS
                hash_val = hashlib.sha256(config_content.encode('utf-8')).hexdigest()

            except ScrapliException as e:
                 status = BackupJobStatus.FAILED
                 err_msg = f"SSH/Scrapli connection error: {str(e)}"
            except Exception as e:
                 status = BackupJobStatus.FAILED
                 err_msg = f"Unexpected error: {str(e)}"

            update_data = {
                "status": status,
            }

            if status == BackupJobStatus.SUCCESS:
                update_data["config_content"] = config_content
                update_data["file_size"] = len(config_content)
                update_data["file_hash"] = hash_val
            else:
                update_data["error_message"] = err_msg

            updated_record = await self.prisma.devicebackuprecord.update(
                where={"id": record_id},
                data=update_data
            )
            return updated_record

        if semaphore:
            async with semaphore:
                return await _execute()
        return await _execute()

    async def create_pending_records(
        self,
        device_ids: List[str],
        user_id: Optional[str] = None,
        backup_profile_id: Optional[str] = None,
        config_type: ConfigType = ConfigType.RUNNING
    ) -> List[Any]:
        """Creates IN_PROGRESS backup records for tracking before bulk execution."""
        records = []
        for dev_id in device_ids:
            record_data = {
                "device_id": dev_id,
                "config_type": config_type,
                "config_format": ConfigFormat.CLI_TEXT,
                "status": BackupJobStatus.IN_PROGRESS,
            }
            if user_id: record_data["triggered_by_user"] = user_id
            if backup_profile_id: record_data["backup_profile_id"] = backup_profile_id
            
            record = await self.prisma.devicebackuprecord.create(data=record_data)
            records.append(record)
        return records

    async def execute_bulk_backups_background(
        self, 
        records: List[Any], 
        user_id: Optional[str] = None,
        config_type: ConfigType = ConfigType.RUNNING,
        max_concurrent: int = 50
    ) -> List[Any]:
        """
        Executes backups for multiple pre-created records concurrently with rate limiting.
        """
        sem = asyncio.Semaphore(max_concurrent)

        tasks = [
            self.execute_single_backup_async(
                record_id=rec.id,
                device_id=rec.device_id, 
                user_id=user_id, 
                config_type=config_type,
                semaphore=sem
            ) 
            for rec in records
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        finished_records = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Update record to FAILED if python threw unhandled exception 
                try:
                    failed_rec = await self.prisma.devicebackuprecord.update(
                        where={"id": records[i].id},
                        data={
                            "status": BackupJobStatus.FAILED,
                            "error_message": f"Task crashed unhandled: {str(result)}"
                        }
                    )
                    finished_records.append(failed_rec)
                except Exception as db_err:
                    print(f"Failed to update broken record {records[i].id}: {str(db_err)}")
            else:
                finished_records.append(result)

        return finished_records



    @staticmethod
    def compare_backups(record1_content: str, record2_content: str, name1: str = "Old", name2: str = "New") -> str:
        """
        Compares two configuration strings and returns a unified diff string.
        """
        lines1 = record1_content.splitlines() if record1_content else []
        lines2 = record2_content.splitlines() if record2_content else []

        diff_lines = list(difflib.unified_diff(
            lines1, 
            lines2, 
            fromfile=name1, 
            tofile=name2,
            lineterm=""
        ))

        return "\n".join(diff_lines)

    async def get_live_running_config(
        self,
        device_id: str,
        user_id: str
    ) -> str:
        """
        Fetches the live running config from the device WITHOUT saving to the database.
        Used for previewing configuration in the UI.
        """
        device = await self.prisma.devicenetwork.find_unique(where={"id": device_id})

        if not device:
            raise ValueError(f"Device {device_id} not found in database")
        if not device.netconf_host:
            raise ValueError("Device does not have a management IP (netconf_host) configured")

        creds = await self.prisma.devicecredentials.find_unique(where={"userId": user_id})
        if not creds:
             raise ValueError("No Device Credentials found for this user")

        username = creds.deviceUsername
        password = self.credential_service.decrypt_password(creds.devicePasswordHash)
        command = self._get_backup_command(device.vendor, ConfigType.RUNNING)

        return await self._send_command_with_fallback(
            device=device,
            username=username,
            password=password,
            command=command,
            timeout_socket=20.0,
            timeout_transport=20.0,
            timeout_ops=20.0,
        )

