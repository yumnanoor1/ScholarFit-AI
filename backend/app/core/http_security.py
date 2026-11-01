"""Security headers, and error replies that never carry internal details or submitted values."""
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import is_production

logger = logging.getLogger("fitscholar.api")

GENERIC_ERROR = "Something went wrong on our side. Please try again."
BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"
# FastAPI's documentation pages need scripts, and exist only outside production
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def install_http_security(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # FastAPI's default reply repeats what was submitted, which can be a password
        details = [{"type": item["type"], "loc": item["loc"], "msg": item["msg"]} for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(details)})

    @app.middleware("http")
    async def secure_responses(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as error:
            # Answered here, inside CORS, so the browser can read the reply
            if is_production():
                logger.error("Unhandled %s on %s %s", type(error).__name__, request.method, request.url.path)
            else:
                logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            response = JSONResponse(status_code=500, content={"detail": GENERIC_ERROR})
        response.headers.update(BASE_HEADERS)
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers["Content-Security-Policy"] = API_CSP
        if is_production():
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
