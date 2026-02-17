import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.driver_factory import DriverFactory

print("DriverFactory loaded:", DriverFactory)
print("Attributes:", dir(DriverFactory))

if hasattr(DriverFactory, 'get_supported_vendors'):
    print("get_supported_vendors exists")
    print("Vendors:", DriverFactory.get_supported_vendors())
else:
    print("ERROR: get_supported_vendors MISSING")
