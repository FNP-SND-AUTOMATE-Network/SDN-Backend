"""
Logging Configuration
ตั้งค่าระบบ Logging มาตรฐานสำหรับทั้งแอปพลิเคชัน

หน้าที่หลัก:
- สร้าง Logger ชื่อ "sdn-hybrid" เป็น Logger กลางของระบบ
- กำหนด Log Level เป็น INFO (แสดง INFO, WARNING, ERROR, CRITICAL)
- กำหนดรูปแบบ Log: [LEVEL] timestamp - message
- ป้องกันการเพิ่ม Handler ซ้ำ (เมื่อ module ถูก import หลายครั้ง)

วิธีใช้ในไฟล์อื่น:
    from app.core.logging import logger
    logger.info("ข้อความ")
"""

import logging

logger = logging.getLogger("sdn-hybrid")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s")
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)
