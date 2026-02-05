import httpx
import asyncio

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Mount device (สง credentials ผาน body)
        print("=== Mounting CSR1000vT ===")
        
        # ลอง mount โดยตรง - แตตอง update DB กอน
        # ใชวธ SQL โดยตรง
        
        response = await client.post(
            "http://localhost:8000/api/v1/nbi/devices/CSR1000vT/mount",
            json={"wait_for_connection": True, "max_wait_seconds": 30}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")

asyncio.run(main())
