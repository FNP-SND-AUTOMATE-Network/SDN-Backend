from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.logging import logger

class BackupSchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        
    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("[Scheduler] BackupSchedulerManager started")
            
    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("[Scheduler] BackupSchedulerManager stopped")
            
    def add_or_update_backup_job(self, backup_id: str, cron_expression: str):
        job_id = f"backup_{backup_id}"
        
        # Remove existing if any
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            
        try:
            self.scheduler.add_job(
                _execute_scheduled_backup,
                CronTrigger.from_crontab(cron_expression),
                id=job_id,
                args=[backup_id],
                replace_existing=True
            )
            logger.info(f"[Scheduler] Added/Updated job for backup {backup_id} with cron {cron_expression}")
        except ValueError as e:
            logger.error(f"[Scheduler] Invalid cron expression for backup {backup_id}: {e}")
            raise e

    def remove_backup_job(self, backup_id: str):
        job_id = f"backup_{backup_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"[Scheduler] Removed job for backup {backup_id}")

        
# Global instance
scheduler_manager = BackupSchedulerManager()

async def _execute_scheduled_backup(backup_id: str):
    logger.info(f"[Scheduler] Triggering scheduled backup job for Profile ID: {backup_id}")
    try:
        from app.database import get_prisma_client
        prisma = get_prisma_client()
        
        # 1. Fetch profile and related devices
        profile = await prisma.backup.find_unique(
            where={"id": backup_id},
            include={"deviceNetworks": True}
        )
        if not profile or not profile.deviceNetworks:
            logger.info(f"[Scheduler] No active devices found for Profile ID: {backup_id}")
            return

        # Safety check: skip execution if profile is paused
        if str(profile.status) == "PAUSED":
            logger.info(f"[Scheduler] Skipping backup for Profile ID: {backup_id} — status is PAUSED")
            return
            
        device_ids = [d.id for d in profile.deviceNetworks if str(d.status) == "ONLINE"]
        if not device_ids:
            logger.info(f"[Scheduler] No ONLINE devices found for Profile ID: {backup_id}")
            return
            
        from app.services.device_backup_service import DeviceBackupService
        service = DeviceBackupService(prisma)
        
        # ดึง user_id ออกมาจาก profile ที่ถูกตั้งค่าไว้ เพื่อให้ระบบสามารถรู้ credentials ที่จะใช้ดึง config
        user_id = profile.createdBy # This should be the UUID of the user who created it
        if not user_id:
            logger.warning(f"[Scheduler] No creator found for Profile ID: {backup_id}. This might cause credential errors.")
        
        logger.info(f"[Scheduler] Initiating background bulk backup for {len(device_ids)} devices with user_id: {user_id}")
        
        pending_records = await service.create_pending_records(
            device_ids=device_ids,
            user_id=user_id,
            backup_profile_id=backup_id,
            config_type="RUNNING"
        )
        
        # We can directly await the background task logic since the APScheduler runs this in an asyncio task
        await service.execute_bulk_backups_background(
            records=pending_records,
            user_id=user_id,
            config_type="RUNNING"
        )
        
        logger.info(f"[Scheduler] Successfully completed bulk backup triggered by Profile ID: {backup_id}")
    except Exception as e:
        logger.error(f"[Scheduler] Failed to execute scheduled backup {backup_id}: {str(e)}")
