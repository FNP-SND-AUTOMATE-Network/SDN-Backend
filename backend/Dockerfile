FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Prisma schema and generate client
COPY prisma ./prisma
COPY pyproject.toml .

# Copy application code
COPY app ./app
COPY prisma_client.py .

# Copy .env file and entrypoint script
COPY .env .
COPY entrypoint.sh .

# Make entrypoint script executable
RUN chmod +x entrypoint.sh

EXPOSE 8000
CMD ["./entrypoint.sh"]