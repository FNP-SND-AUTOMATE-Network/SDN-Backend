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

async def huawei_bypass_on_open(conn: Any) -> None:
    """
    Scrapli on_open callback for Huawei VRP devices.

    Huawei devices often greet the user with a password-change prompt right
    after a successful SSH login, before the normal shell prompt appears:

        The password needs to be changed. Change now? [Y/N]:

    This callback reads all buffered output after the SSH handshake and, if
    that prompt is detected, sends "n<Enter>" to skip the change.  It then
    waits for the actual command prompt so Scrapli's normal send_command
    logic can take over from a clean state.

    Additionally, terminal paging is disabled with "screen-length 0 temporary"
    so that long outputs (e.g. display current-configuration) are not cut off.
    """
    import asyncio

    # Give the device a moment to flush its post-login banner / prompts
    await asyncio.sleep(2.0)

    # Read whatever the device has sent so far (may or may not be the prompt)
    try:
        raw = await asyncio.wait_for(conn.channel.read(65535), timeout=3.0)
        buffered = raw.decode("utf-8", errors="ignore")
    except (asyncio.TimeoutError, Exception):
        buffered = ""

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
        await conn.channel.write(b"n\n")
        await asyncio.sleep(0.5)
        # Drain any follow-up output the device sends after our answer
        try:
            await asyncio.wait_for(conn.channel.read(65535), timeout=3.0)
        except (asyncio.TimeoutError, Exception):
            pass

    # Wait until the device presents its normal command prompt
    await conn.channel.read_until_prompt()

    # Disable terminal paging so long outputs are not truncated
    await conn.channel.write(b"screen-length 0 temporary\n")
    await conn.channel.read_until_prompt()


class DeviceBackupService:
    """
    Service for executing configuration backups from network devices using Scrapli.
    Handles SSH connection, command execution, diffs, and saving DeviceBackupRecords.
    """
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
                scrapli_driver = self.map_vendor_to_scrapli_driver(device.vendor)
                command = self._get_backup_command(device.vendor, config_type)

                asyncssh_options = {
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
                
                if device.vendor == DeviceVendor.HUAWEI:
                    asyncssh_options["request_pty"] = False

                device_dict = {
                    "host": device.netconf_host,
                    "platform": scrapli_driver,
                    "port": 22, 
                    "auth_username": username,
                    "auth_password": password,
                    "auth_strict_key": False,
                    "transport": "asyncssh",
                    "timeout_socket": 30.0,
                    "timeout_transport": 30.0,
                    "timeout_ops": 30.0,
                    "transport_options": {
                        "asyncssh": asyncssh_options
                    }
                }

                if device.vendor == DeviceVendor.HUAWEI:
                    device_dict["auth_bypass"] = True
                    device_dict["on_open"] = huawei_bypass_on_open

                async with AsyncScrapli(**device_dict) as conn:
                    response = await conn.send_command(command)
                    config_content = response.result
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
        scrapli_driver = self.map_vendor_to_scrapli_driver(device.vendor)
        command = self._get_backup_command(device.vendor, ConfigType.RUNNING)

        asyncssh_options = {
            "server_host_key_algs": [
                "ssh-rsa", "ssh-dss", "rsa-sha2-256", "rsa-sha2-512",
                "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                "ssh-ed25519"
            ],
            "kex_algs": [
                "diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1",
                "diffie-hellman-group-exchange-sha1", "diffie-hellman-group-exchange-sha256",
                "curve25519-sha256", "curve25519-sha256@libssh.org"
            ]
        }
        
        if device.vendor == DeviceVendor.HUAWEI:
            asyncssh_options["request_pty"] = False

        device_dict = {
            "host": device.netconf_host,
            "platform": scrapli_driver,
            "port": 22, 
            "auth_username": username,
            "auth_password": password,
            "auth_strict_key": False,
            "transport": "asyncssh",
            "timeout_socket": 20.0,
            "timeout_transport": 20.0,
            "timeout_ops": 20.0,
            "transport_options": {
                "asyncssh": asyncssh_options
            }
        }
        
        if device.vendor == DeviceVendor.HUAWEI:
            device_dict["auth_bypass"] = True
            device_dict["on_open"] = huawei_bypass_on_open

        async with AsyncScrapli(**device_dict) as conn:
            response = await conn.send_command(command)
            return response.result

