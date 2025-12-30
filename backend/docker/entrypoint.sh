#!/usr/bin/env bash
set -e

# สร้าง client code จาก schema (ครั้งแรก/เมื่อ schema เปลี่ยน)
echo "Generating Prisma client..."
python -m prisma generate

# push schema ไป DB (สะดวกตอน dev; prod แนะนำ migrate deploy)
echo "Pushing database schema..."
python -m prisma db push --accept-data-loss

# รอสักครู่ให้ Prisma client พร้อม
sleep 2

# รัน API
echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000