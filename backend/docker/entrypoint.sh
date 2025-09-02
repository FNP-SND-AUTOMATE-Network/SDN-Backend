#!/usr/bin/env bash
set -e

# รอ Postgres พร้อม (เช็ค TCP)
until (echo > /dev/tcp/db/5432) >/dev/null 2>&1; do
  echo "Waiting for Postgres on db:5432..."
  sleep 1
done

# สร้าง client code จาก schema (ครั้งแรก/เมื่อ schema เปลี่ยน)
python -m prisma generate

# push schema ไป DB (สะดวกตอน dev; prod แนะนำ migrate deploy)
python -m prisma db push --accept-data-loss

# รัน API
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
