"""Єдиний конверт відповідей і помилок (README: Normalizer).

Кожна відповідь API M1 ID:
    { "ok": bool, "data": ..., "meta": ...|null,
      "error": null | [{field, message, code?}] }
Помилки — масивом {field,message}, як у справжньому MyStat.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def envelope(ok: bool, data: Any = None, meta: Any = None,
             error: list[dict] | None = None) -> dict:
    return {"ok": ok, "data": data, "meta": meta, "error": error}


def ok(data: Any = None, meta: Any = None) -> dict:
    return envelope(True, data=data, meta=meta)


class ApiError(Exception):
    """Бізнес-помилка → конверт з масивом [{field,message}]."""

    def __init__(self, status_code: int, code: str,
                 field: str = "__all__", message: str | None = None):
        self.status_code = status_code
        self.code = code
        self.field = field
        self.message = message or code
        super().__init__(code)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(False, error=[{
                "field": exc.field,
                "message": exc.message,
                "code": exc.code,
            }]),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = ".".join(str(part) for part in e.get("loc", ()) if part != "body")
            errors.append({
                "field": loc or "__all__",
                "message": e.get("msg", "validation_error"),
            })
        return JSONResponse(status_code=422, content=envelope(False, error=errors))

    @app.exception_handler(Exception)
    async def unhandled_handler(request, exc: Exception):
        """Будь-яка непіймана помилка — в єдиному конверті, без стека назовні."""
        import logging

        logging.getLogger("m1id").error(
            "unhandled_error %s %s: %r", request.method, request.url.path, exc
        )
        return JSONResponse(
            status_code=500,
            content=envelope(False, error=[{
                "field": "__all__",
                "message": "internal_error",
                "code": "internal_error",
            }]),
        )
