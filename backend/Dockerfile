FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# (ออปชัน) ใช้ curl ตอนดาวน์โหลด Prisma engines
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอก schema ก่อน เพื่อให้ build cache ใช้ได้
COPY prisma ./prisma
# สร้าง client ตอน build ได้เลย (ถ้าอยากทำล่วงหน้า)
RUN python -m prisma generate || true

# คัดลอกโค้ดแอปและ entrypoint
COPY app ./app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
CMD ["/entrypoint.sh"]
