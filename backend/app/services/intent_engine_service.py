import asyncio
import json
from typing import Dict, Any, List, Optional
from jinja2 import Template
from textfsm import TextFSM
import textfsm
from scrapli import AsyncScrapli
from scrapli.exceptions import ScrapliException
from ntc_templates.parse import parse_output

from app.models.configuration_template import TemplateType
from prisma.enums import DeviceVendor
from app.services.device_credentials_service import DeviceCredentialsService

class IntentEngineService:
    def __init__(self, prisma_client):
        self.prisma = prisma_client
        self.credential_service = DeviceCredentialsService(prisma_client)

    def map_vendor_to_scrapli_driver(self, vendor: DeviceVendor) -> str:
        mapping = {
            DeviceVendor.CISCO: "cisco_iosxe",
            DeviceVendor.HUAWEI: "huawei_vrp",
        }
        return mapping.get(vendor, "cisco_iosxe")
        
    def map_platform_to_ntc(self, vendor: DeviceVendor) -> str:
        mapping = {
            DeviceVendor.CISCO: "cisco_ios",
            DeviceVendor.HUAWEI: "huawei_vrp",
        }
        return mapping.get(vendor, "cisco_ios")

    def render_template(self, template_text: str, variables: Dict[str, Any], device_dict: Dict[str, Any], state_dict: Dict[str, Any]) -> str:
        """
        Render a Jinja2 template using the provided intent variables and device state.
        """
        jinja_template = Template(template_text)
        rendered_text = jinja_template.render(
            intent=variables,
            device=device_dict,
            current_state=state_dict
        )
        return rendered_text.strip()

    async def execute_deployment_background(self, job_id: str, template_id: str, device_ids: List[str], variables: Dict[str, Any], user_id: str):
        """
        Background task to deploy the configuration template to multiple devices.
        """
        job = await self.prisma.deploymentjob.find_unique(where={"id": job_id})
        template = await self.prisma.configurationtemplate.find_unique(
            where={"id": template_id},
            include={"detail": True}
        )
        
        if not template or not template.detail or not template.detail.config_content:
            await self.prisma.deploymentjob.update(
                where={"id": job_id},
                data={"status": "FAILED", "error_message": "Template content not found"}
            )
            return

        template_text = template.detail.config_content
        
        success_count = 0
        failed_count = 0

        # Execute devices concurrently or sequentially (using a semaphore to rate limit)
        sem = asyncio.Semaphore(10)
        
        async def deploy_to_device(device_id: str):
            nonlocal success_count, failed_count
            
            # Create a record for this device
            record = await self.prisma.deploymentrecord.create(
                data={
                    "job_id": job_id,
                    "device_id": device_id,
                    "status": "IN_PROGRESS"
                }
            )
            
            error_msg = None
            rendered_config = ""
            device_state_json = ""
            status = "FAILED"

            try:
                device = await self.prisma.devicenetwork.find_unique(where={"id": device_id})
                if not device or not device.netconf_host:
                    raise Exception("Device not found or missing IP Address")
                    
                creds = await self.prisma.devicecredentials.find_unique(where={"userId": user_id})
                if not creds:
                    raise Exception("Credentials not found for current user")
                    
                username = creds.deviceUsername
                password = self.credential_service.decrypt_password(creds.devicePasswordHash)
                scrapli_driver = self.map_vendor_to_scrapli_driver(device.vendor)
                ntc_platform = self.map_platform_to_ntc(device.vendor)

                # Connect via Scrapli
                device_conn = {
                    "host": device.netconf_host,
                    "platform": scrapli_driver,
                    "port": 22, 
                    "auth_username": username,
                    "auth_password": password,
                    "auth_strict_key": False,
                    "transport": "asyncssh",
                }

                device_dict = {
                    "id": device.id,
                    "name": device.device_name,
                    "vendor": device.vendor,
                    "platform": ntc_platform,
                    "ip": device.netconf_host
                }

                current_state = {}

                async with sem:
                    async with AsyncScrapli(**device_conn) as conn:
                        # Optional: Pull state if the template implies it.
                        # For now, we will pull basic interfaces state to expose to Jinja2
                        try:
                            show_cmd = "show ip interface brief" if device.vendor == DeviceVendor.CISCO else "display ip interface brief"
                            response = await conn.send_command(show_cmd)
                            # Parse with ntc-templates
                            parsed = parse_output(platform=ntc_platform, command=show_cmd, data=response.result)
                            current_state["interfaces"] = parsed
                            device_state_json = json.dumps(current_state, indent=2)
                        except Exception as e:
                            print(f"Failed to parse state for {device.netconf_host}: {e}")
                            # Non-fatal, just means no state available
                            current_state["error"] = str(e)

                        # Render Template
                        rendered_config = self.render_template(template_text, variables, device_dict, current_state)
                        
                        if not rendered_config:
                            raise Exception("Rendered configuration is empty")

                        # We have the rendered multi-line string. Send to device
                        # We split and send configs so scrapli handles config mode
                        cmds = rendered_config.splitlines()
                        push_resp = await conn.send_configs(cmds)
                        
                        if push_resp.failed:
                            raise Exception(f"Failed to apply config: {push_resp.result}")
                        
                        status = "SUCCESS"
                        success_count += 1
                        
            except Exception as e:
                error_msg = str(e)
                failed_count += 1
                
            # Update the DeploymentRecord
            await self.prisma.deploymentrecord.update(
                where={"id": record.id},
                data={
                    "status": status,
                    "rendered_config": rendered_config,
                    "device_state": device_state_json,
                    "error_message": error_msg
                }
            )
            
            # If successful, trigger a backup snapshot
            if status == "SUCCESS":
                try:
                    from app.services.device_backup_service import DeviceBackupService
                    backup_svc = DeviceBackupService(self.prisma)
                    # We create a pending backup record and run it sequentially for safety here
                    backup_recs = await backup_svc.create_pending_records([device_id], user_id=user_id)
                    if backup_recs:
                        await backup_svc.execute_single_backup_async(record_id=backup_recs[0].id, device_id=device_id, user_id=user_id)
                except Exception as backup_e:
                    print(f"Automatic backup after deployment failed: {backup_e}")

        # Execute all device deployments
        tasks = [deploy_to_device(did) for did in device_ids]
        await asyncio.gather(*tasks)
        
        # Conclude Job Status
        final_status = "SUCCESS"
        if failed_count == len(device_ids):
            final_status = "FAILED"
        elif failed_count > 0:
            final_status = "PARTIAL_SUCCESS"
            
        await self.prisma.deploymentjob.update(
            where={"id": job_id},
            data={
                "status": final_status,
                "success_devices": success_count,
                "failed_devices": failed_count
            }
        )

    async def trigger_deployment(self, template_id: str, device_ids: List[str], variables: Dict[str, Any], user_id: str, background_tasks) -> str:
        """
        Creates the job and triggers it in the background.
        """
        job = await self.prisma.deploymentjob.create(
            data={
                "template_id": template_id,
                "triggered_by_user": user_id,
                "total_devices": len(device_ids),
                "variables_json": json.dumps(variables),
                "status": "IN_PROGRESS"
            }
        )
        
        background_tasks.add_task(
            self.execute_deployment_background,
            job.id, template_id, device_ids, variables, user_id
        )
        
        return job.id
