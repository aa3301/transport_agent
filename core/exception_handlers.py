from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from .response import error as resp_error

def register_exception_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content=resp_error(code=str(exc.status_code), message=str(exc.detail)))

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        # server-side log here if you want
        # print("Unhandled exception:", exc)
        return JSONResponse(status_code=500, content=resp_error(code="internal_error", message="Internal server error"))
