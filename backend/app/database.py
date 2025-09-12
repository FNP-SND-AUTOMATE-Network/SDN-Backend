"""Database configuration and global client instance"""

# Global Prisma client instance
prisma_client = None


def get_prisma_client():
    """Get the global Prisma client instance"""
    global prisma_client
    return prisma_client


def set_prisma_client(client):
    """Set the global Prisma client instance"""
    global prisma_client
    prisma_client = client
