"""Correlation-ID validation and propagation for the independent demo services"""

import re
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def install_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        supplied_id = request.headers.get("X-Correlation-ID")
        if supplied_id is not None and not CORRELATION_ID_PATTERN.fullmatch(supplied_id):
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "invalid_correlation_id",
                        "message": "X-Correlation-ID must contain 1-64 safe ASCII characters.",
                    }
                },
            )

        correlation_id = supplied_id or uuid4().hex
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
