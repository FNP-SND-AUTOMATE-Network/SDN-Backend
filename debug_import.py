import sys
import os
import traceback

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

print("Attempting to import app.main...")
try:
    from app import main
    print("✅ Successfully imported app.main")
except Exception:
    print("❌ Failed to import app.main")
    traceback.print_exc()
