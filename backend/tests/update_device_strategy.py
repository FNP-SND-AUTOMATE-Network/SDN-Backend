"""
Update Device Strategy Script
เปลี่ยน strategy ของ devices เป็น OPERATION_BASED

Usage:
    python update_device_strategy.py --device CSR1000vT
    python update_device_strategy.py --all  # Update all devices
"""
import asyncio
import argparse
import sys
import os

# Set DATABASE_URL from .env if not already set
from dotenv import load_dotenv
load_dotenv()

from prisma import Prisma


async def update_device_strategy(node_id: str = None, update_all: bool = False):
    """Update device default_strategy to OPERATION_BASED"""
    prisma = Prisma()
    await prisma.connect()
    
    try:
        if update_all:
            # Update all devices
            result = await prisma.devicenetwork.update_many(
                where={},
                data={"default_strategy": "OPERATION_BASED"}
            )
            print(f"✅ Updated {result.count} devices to OPERATION_BASED strategy")
        
        elif node_id:
            # Update specific device
            device = await prisma.devicenetwork.find_first(
                where={"node_id": node_id}
            )
            
            if not device:
                print(f"❌ Device {node_id} not found")
                return
            
            # Show current strategy
            print(f"Current strategy for {node_id}: {device.default_strategy}")
            
            # Update
            updated = await prisma.devicenetwork.update(
                where={"id": device.id},
                data={"default_strategy": "OPERATION_BASED"}
            )
            print(f"✅ Updated {node_id} to OPERATION_BASED strategy")
        
        else:
            print("Please specify --device or --all")
    
    finally:
        await prisma.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Update device strategy")
    parser.add_argument("--device", "-d", help="Device node_id to update")
    parser.add_argument("--all", "-a", action="store_true", help="Update all devices")
    args = parser.parse_args()
    
    asyncio.run(update_device_strategy(
        node_id=args.device,
        update_all=args.all
    ))


if __name__ == "__main__":
    main()

