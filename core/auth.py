import logging
import json
from fastapi import Header, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from typing import Optional
from config.settings import settings

logger = logging.getLogger(__name__)

# Define security scheme for Swagger UI (auto_error=False allows us to handle missing tokens gracefully)
security = HTTPBearer(auto_error=False)

def _extract_token(header_val: str) -> Optional[str]:
    """Helper to strip 'Bearer ' prefix if present."""
    if not header_val:
        return None
    hv = header_val.strip()
    if hv.lower().startswith("bearer "):
        return hv.split(None, 1)[1].strip()
    return hv  # accept raw token

async def get_current_user_noauth(request: Request = None):
    """
    TEMP NO-AUTH: always returns a dummy user.
    """
    return {"user_id": "demo", "role": "admin"}

# TEMP: override any previous implementation
get_current_user = get_current_user_noauth  # type: ignore

async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    authorization: Optional[str] = Header(None)
):
    """
    Async JWT auth dependency.
    Robust parsing to handle various Swagger/Client formats.
    """
    token_value = None
    
    # 1. Try HTTPBearer (Standard Swagger/FastAPI way)
    if creds and creds.credentials:
        token_value = creds.credentials

    # 2. Try the argument injected by FastAPI Header (Manual)
    if not token_value and authorization:
        token_value = _extract_token(authorization)
    
    # 3. If not found, try manual header lookup (case-insensitive)
    if not token_value:
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header:
            token_value = _extract_token(auth_header)

    # 4. Check Query Params (fallback)
    if not token_value:
        token_value = request.query_params.get("token") or request.query_params.get("authorization")

    # 5. Check Body (fallback - mostly for dev/debug)
    if not token_value:
        try:
            # We use request.body() which is cached by Starlette/FastAPI
            body_bytes = await request.body()
            if body_bytes:
                try:
                    body_json = json.loads(body_bytes.decode("utf-8"))
                    for key in ("token", "authorization", "bearer"):
                        if key in body_json and body_json[key]:
                            token_value = _extract_token(body_json[key])
                            break
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

    if not token_value:
        logger.warning("Authentication failed: No token found in headers, query, or body.")
        raise HTTPException(status_code=401, detail="Missing Authorization token")

    # Decode
    try:
        payload = jwt.decode(token_value, settings.JWT_SECRET, algorithms=["HS256"])
        user_data = {"user_id": payload.get("sub"), "role": payload.get("role", "user")}
        return user_data
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.DecodeError as e:
        logger.warning(f"Token decode error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")
