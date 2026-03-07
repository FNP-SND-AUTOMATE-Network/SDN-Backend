import asyncio
from prisma import Prisma
from app.services.device_backup_service import DeviceBackupService
from prisma.enums import ConfigType

async def main():
    prisma = Prisma()
    await prisma.connect()
    
    try:
        # Get first user
        user = await prisma.user.find_first()
        if not user:
            print("No user found in DB")
            return
            
        # Get a device
        device = await prisma.devicenetwork.find_first(where={"odl_mounted": True})
        if not device:
            device = await prisma.devicenetwork.find_first()
            if not device:
                print("No device found in DB")
                return

        print(f"Testing backup for device: {device.device_name} ({device.netconf_host}) as user: {user.email}")
        
        service = DeviceBackupService(prisma)
        
        print("\n1. Creating pending records...")
        records = await service.create_pending_records(
            device_ids=[device.id],
            user_id=user.id,
            config_type=ConfigType.RUNNING
        )
        print(f"Created {len(records)} pending records:")
        for r in records:
            print(f" - ID: {r.id}, Status: {r.status}")
            
        print("\n2. Executing background backup task...")
        results = await service.execute_bulk_backups_background(
            records=records,
            user_id=user.id,
            config_type=ConfigType.RUNNING
        )
        
        print("\n3. Results:")
        for r in results:
            print(f" - ID: {r.id}, Status: {r.status}")
            if r.error_message:
                print(f"   Error: {r.error_message}")
            if hasattr(r, 'status') and r.status == "SUCCESS":
                print(f"   File hash: {r.file_hash}")
                print(f"   Content preview:\n {r.config_content[:200] if r.config_content else ''}...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
