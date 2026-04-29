"""
Password Validation Utilities
Shared password strength validation for all auth-related models.

Used by RegisterRequest, ResetPasswordRequest, and UserChangePasswordRequest
to enforce consistent password policies.
"""

import re


def validate_password_strength(password: str) -> str:
    """
    Validate password strength with the following rules:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit

    Args:
        password: The password string to validate.

    Returns:
        The password if valid.

    Raises:
        ValueError: If the password does not meet requirements.
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")

    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit")

    return password
