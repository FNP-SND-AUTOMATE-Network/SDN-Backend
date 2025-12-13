import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add the backend directory to sys.path so we can import app modules
sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    import pyotp
    from app.services.totp_service import TotpService
except ImportError as e:
    print(f"Import Error: {e}")
    print("Please ensure dependencies are installed.")
    sys.exit(1)

async def test_totp_flow():
    print("--- Starting TOTP Service Verification ---")

    # 1. Mock Prisma Client
    mock_prisma = MagicMock()
    mock_prisma.usertotp = MagicMock()
    mock_prisma.usertotp.find_unique = AsyncMock(return_value=None)
    mock_prisma.usertotp.create = AsyncMock(return_value=True)
    mock_prisma.usertotp.update = AsyncMock(return_value=True)
    mock_prisma.user = MagicMock()
    mock_prisma.user.update = AsyncMock(return_value=True)

    # 2. Initialize Service
    service = TotpService(mock_prisma)
    print("✅ TotpService Initialized")

    # 3. Test Generate Secret
    secret = service.generate_secret()
    print(f"✅ Generated Secret: {secret}")
    if not secret or len(secret) < 16:
        print("❌ Secret generation failed")
        return

    # 4. Test Provisioning URI
    email = "test@example.com"
    uri = service.get_provisioning_uri(secret, email)
    print(f"✅ Provisioning URI: {uri}")
    if "otpauth://totp/" not in uri or secret not in uri:
        print("❌ Provisioning URI generation failed")
        return

    # 5. Test Verify TOTP (Valid Case)
    # Generate a valid code using pyotp directly
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()
    is_valid = service.verify_totp(secret, valid_code)
    print(f"✅ Verification with valid code ({valid_code}): {is_valid}")
    if not is_valid:
        print("❌ Verification failed for valid code")
        return

    # 6. Test Verify TOTP (Invalid Case)
    invalid_code = "000000"
    is_invalid = service.verify_totp(secret, invalid_code)
    print(f"✅ Verification with invalid code ({invalid_code}): {not is_invalid}")
    if is_invalid:
        print("❌ Verification passed for invalid code (should fail)")
        return

    # 7. Test Enable TOTP
    user_id = "user-123"
    success = await service.enable_totp(user_id, secret)
    print(f"✅ Enable TOTP: {success}")
    
    # Verify DB calls
    mock_prisma.usertotp.create.assert_called_once()
    mock_prisma.user.update.assert_called_once()
    print("✅ Database calls verified (Mocked)")

    print("\n🎉 All TOTP Service logic tests passed!")

if __name__ == "__main__":
    asyncio.run(test_totp_flow())
