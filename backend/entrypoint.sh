#!/bin/bash
set -e

# Clean up any corrupted Prisma client
echo "Cleaning up Prisma client..."
python -m prisma_cleanup || true

# Generate Prisma client first (doesn't need DB connection)
echo "Force removing old Prisma client and cache..."
rm -rf /usr/local/lib/python3.12/site-packages/prisma
rm -rf /app/prisma_client
rm -rf /root/.cache/prisma-python
rm -rf /root/.cache/prisma

# Generate Prisma client first (doesn't need DB connection)
echo "Force removing old Prisma client and cache..."
rm -rf /usr/local/lib/python3.12/site-packages/prisma
rm -rf /app/prisma_client
rm -rf /root/.cache/prisma-python
rm -rf /root/.cache/prisma

echo "Re-installing prisma to ensure clean state..."
pip install --force-reinstall "prisma>=0.15.0"

echo "Generating Prisma client..."
python -m prisma generate

# Wait a moment for client generation to complete
sleep 2

# Use DIRECT_URL for database operations in production
if [ -n "$DIRECT_URL" ]; then
    export DATABASE_URL="$DIRECT_URL"
fi

# Push database schema (only if DATABASE_URL is set)
if [ -n "$DATABASE_URL" ]; then
    echo "Pushing database schema..."
    python -m prisma db push --skip-generate || {
        echo "Warning: Database push failed. Check your DATABASE_URL and DIRECT_URL credentials."
        echo "Application will start but database operations may fail."
    }
else
    echo "Warning: DATABASE_URL not set. Skipping database push."
fi

# Start the application with hot reload
echo "Cleaning __pycache__..."
find . -type d -name "__pycache__" -exec rm -rf {} +

echo "Starting FastAPI application with hot reload..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
