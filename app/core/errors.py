'''Structured error response payload helper.'''
def format_error_response(message: str, code: str = "GENERIC_ERROR", status_code: int = 400) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "status_code": status_code,
        }
    }
