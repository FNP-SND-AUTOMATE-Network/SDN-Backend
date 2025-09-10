import os
import subprocess
import sys
from pathlib import Path

def ensure_prisma_client():
    """Ensure Prisma client is generated"""
    try:
        from prisma import Prisma
        return Prisma()
    except RuntimeError as e:
        if "hasn't been generated yet" in str(e):
            print("Generating Prisma client...")
            try:
                # Run prisma generate
                result = subprocess.run([
                    sys.executable, "-m", "prisma", "generate"
                ], capture_output=True, text=True, cwd=Path(__file__).parent)
                
                if result.returncode == 0:
                    print("Prisma client generated successfully")
                    # Import again after generation
                    import importlib
                    import prisma
                    importlib.reload(prisma)
                    from prisma import Prisma
                    return Prisma()
                else:
                    print(f"Error generating Prisma client: {result.stderr}")
                    raise RuntimeError(f"Failed to generate Prisma client: {result.stderr}")
            except Exception as ex:
                print(f"Error running prisma generate: {ex}")
                raise RuntimeError(f"Failed to generate Prisma client: {ex}")
        else:
            raise e

# Create a global instance
prisma_client = ensure_prisma_client()
