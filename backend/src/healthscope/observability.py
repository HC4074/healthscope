"""Request correlation and structured API access logging."""

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUEST_ID_HEADER = "X-Request-ID"

# A child of Uvicorn's error logger inherits its configured INFO handler in
# production while remaining capturable through the standard logging tree in tests.
access_logger = logging.getLogger("uvicorn.error.healthscope_access")


def _request_id(request: Request) -> str:
    """Return a safe caller correlation ID or generate a new UUID."""

    candidate = request.headers.get(_REQUEST_ID_HEADER, "")
    if _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def _access_event(
    *,
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: float,
    environment: str,
    release_sha: str,
    version: str,
) -> str:
    """Serialize a stable, query-free access event for log processors."""

    return json.dumps(
        {
            "event": "http_request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "release_sha": release_sha,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 3),
            "environment": environment,
            "service_version": version,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach correlation IDs and emit one structured event per API request."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        environment: str,
        release_sha: str,
        version: str,
    ) -> None:
        super().__init__(app)
        self._environment = environment
        self._release_sha = release_sha
        self._version = version

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request)
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            access_logger.exception(
                _access_event(
                    request=request,
                    request_id=request_id,
                    status_code=500,
                    duration_ms=duration_ms,
                    environment=self._environment,
                    release_sha=self._release_sha,
                    version=self._version,
                )
            )
            raise

        response.headers[_REQUEST_ID_HEADER] = request_id
        duration_ms = (time.perf_counter() - started_at) * 1000
        access_logger.info(
            _access_event(
                request=request,
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=duration_ms,
                environment=self._environment,
                release_sha=self._release_sha,
                version=self._version,
            )
        )
        return response
