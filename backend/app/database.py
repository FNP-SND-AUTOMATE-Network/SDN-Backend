"""Database configuration and global client instance"""

from fastapi import HTTPException

# Global Prisma client instance
prisma_client = None


def get_prisma_client():
    """Get the global Prisma client instance"""
    global prisma_client
    if prisma_client is None:
        raise HTTPException(
            status_code=500, 
            detail="Database connection not available. Server is starting up."
        )
    return prisma_client


def set_prisma_client(client):
    """Set the global Prisma client instance"""
    global prisma_client
    prisma_client = client


def is_prisma_client_ready():
    """Check if Prisma client is ready"""
    global prisma_client
    return prisma_client is not None


def get_db():
    """FastAPI dependency to get database client"""
    return get_prisma_client()
