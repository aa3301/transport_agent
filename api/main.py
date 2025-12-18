# api/main.py

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from core.auth import get_current_user
from core.response import ok

# ...existing code...

app = FastAPI()

# Replace / modify the proxy helper and proxied routes to explicitly forward Authorization.

async def proxy_to_http(service_url: str, path: str, method: str, request: Request | None = None, body: bytes | None = None) -> JSONResponse:
    """
    Proxy helper that explicitly forwards Authorization (case-insensitive) and Content-Type.
    """
    import httpx, traceback
    try:
        outgoing = {}
        if request is not None:
            # extract Authorization in a case-insensitive manner
            auth_val = None
            for k in ("authorization", "Authorization"):
                auth_val = request.headers.get(k)
                if auth_val:
                    break
            if auth_val:
                # forward both variants to be safe across layers
                outgoing["Authorization"] = str(auth_val)
                outgoing["authorization"] = str(auth_val)
            # forward content-type if provided
            ct = request.headers.get("content-type") or request.headers.get("Content-Type")
            if ct:
                outgoing["Content-Type"] = str(ct)

        # Log presence for debugging (avoid printing token in shared logs in production)
        logger.info("Gateway forwarding Authorization to %s%s: %s", service_url, path, "[present]" if outgoing.get("Authorization") else "[none]")

        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{service_url}{path}"
            # use client.request with explicit headers
            resp = await client.request(method=method, url=url, headers=outgoing, content=body)
            if not (200 <= resp.status_code < 300):
                try:
                    logger.error("Proxy to %s returned %s: %s", url, resp.status_code, resp.text)
                except Exception:
                    logger.error("Proxy to %s returned %s (body unreadable)", url, resp.status_code)
            return JSONResponse(status_code=resp.status_code, content=resp.json() if resp.text else {})
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("HTTP proxy error: %s\n%s", str(e), tb)
        return JSONResponse(status_code=503, content={"ok": False, "data": None, "error": {"message": str(e)}})

# Update proxied endpoints to accept Request and pass it into proxy_to_http (apply to each proxied route)
# Example for /subscribe:
@app.post("/subscribe")
async def subscribe(request: Request, payload: SubscribeRequest, user: dict = Depends(get_current_user)):
    # log incoming header presence
    incoming_auth = request.headers.get("authorization") or request.headers.get("Authorization")
    logger.info("Gateway received Authorization for /subscribe: %s", "[present]" if incoming_auth else "[none]")
    return await proxy_to_http(NOTIFICATION_SERVICE_URL, "/subscribe", "POST", request=request, body=payload.json().encode("utf-8"))

# ...existing code...