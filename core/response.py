def ok(data=None):
    """Standard success envelope."""
    return {"ok": True, "data": data, "error": None}


def error(code: str = "internal_error", message: str = "An internal error occurred"):
    """Standard error envelope."""
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}
