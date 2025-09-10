#!/bin/bash

# Clean up any corrupted Prisma client
echo "Cleaning up Prisma client..."
python -m prisma_cleanup || true

# Use DIRECT_URL for database operations in production
export DATABASE_URL="$DIRECT_URL"

# Generate Prisma client using db push method
echo "Generating Prisma client with db push..."
python -m prisma db push

# Start the application with hot reload
echo "Starting FastAPI application with hot reload..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
