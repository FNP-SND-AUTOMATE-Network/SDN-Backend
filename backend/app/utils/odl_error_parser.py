import json
from typing import Optional

def parse_odl_error(status_code: int, raw_body: str) -> str:
    """
    Parses OpenDaylight HTTP errors into human-readable English messages 
    so the frontend can display them directly.
    """
    odl_msg: Optional[str] = None
    error_tag: Optional[str] = None
    
    # Try to extract the specific error message from ODL's JSON structure
    if raw_body:
        try:
            body_json = json.loads(raw_body)
            # ODL RFC-8040 error structure typically:
            # { "errors": { "error": [ { "error-type": "...", "error-tag": "...", "error-message": "..." } ] } }
            if "errors" in body_json and "error" in body_json["errors"]:
                errors = body_json["errors"]["error"]
                if isinstance(errors, list) and len(errors) > 0:
                    first_error = errors[0]
                    odl_msg = first_error.get("error-message")
                    error_tag = first_error.get("error-tag")
        except json.JSONDecodeError:
            pass
            
    # Priority 1: Map based on recognized string from ODL error-message or error-tag
    if odl_msg or error_tag:
        if odl_msg and "data model content does not exist" in odl_msg.lower():
            return "The requested device or data does not exist in the OpenDaylight controller."
        if error_tag == "data-missing":
            return "The requested device or data does not exist in the OpenDaylight controller."
        if error_tag == "in-use" or (odl_msg and "lock denied" in odl_msg.lower()):
            return "The device configuration is currently locked or in use by another process."
        if error_tag == "data-exists":
            return "The data or configuration you are trying to create already exists."
        if error_tag == "operation-failed":
            return f"The operation failed on the device: {odl_msg}" if odl_msg else "The operation failed on the device."
        if error_tag == "access-denied":
            return "Access denied to the requested data or operation."

    # Priority 2: General mapping based on HTTP status code
    category = status_code // 100
    
    if status_code == 401:
        return "Authentication failed. Please verify the credentials for OpenDaylight or the device."
    elif status_code == 404:
        return "The requested device or information was not found in OpenDaylight."
    elif status_code == 408:
        return "Request timeout. The device is taking too long to respond."
    elif status_code == 409:
        return "There's a conflict with the existing data. The resource might already exist."
    elif status_code == 400:
        return "Invalid request format. The data sent to OpenDaylight is incorrect."
    elif status_code in (503, 504):
        return "Connection timeout. OpenDaylight or the device is unresponsive."
    elif category == 5:
        return "OpenDaylight encountered an internal system status error."
        
    # If no specific mapping was hit but we have an ODL specific message from JSON
    if odl_msg:
        # Standardize the text by returning it properly formatted
        return odl_msg.capitalize() if not odl_msg[0].isupper() else odl_msg
        
    return f"An unknown error occurred while communicating with OpenDaylight (HTTP {status_code})."
