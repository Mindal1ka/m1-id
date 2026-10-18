"""Системні ендпоінти: здоров'я сервісу та діагностика SpecRegistry.

Відповіді — в єдиному конверті {ok, data, meta} (README: Normalizer).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.responses import ApiError
from app.db.models import User
from app.deps import get_current_user, get_registry
from app.spec.registry import SpecRegistry

router = APIRouter(prefix="/api")


@router.get("/health")
def health(settings=Depends(get_settings)) -> dict:
    """Живість бекенда. Фронт пінгує це на картці статусу."""
    from app.core.responses import ok

    return ok({
        "service": settings.project_name,
        "version": settings.version,
        "time": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/system/spec/stats")
def spec_stats(registry: SpecRegistry = Depends(get_registry)) -> dict:
    """Статистика завантаженої OpenAPI-спеки."""
    from app.core.responses import ok

    return ok(registry.stats())


@router.get("/system/spec/operations")
def spec_operations(
    tag: str | None = Query(None, description="фільтр за тегом, напр. Homework"),
    q: str | None = Query(None, description="підрядок в operationId або шляху"),
    limit: int = Query(50, ge=1, le=500),
    registry: SpecRegistry = Depends(get_registry),
) -> dict:
    """Довідник операцій — фронт малює з цього розділ «Про API»."""
    from app.core.responses import ok

    ops = registry.operations(tag=tag, q=q)[:limit]
    return ok(
        [
            {
                "method": o.method,
                "path": o.path_template,
                "operation_id": o.operation_id,
                "tag": o.tag,
                "summary": o.summary,
                "params": list(o.params),
                "secured": o.secured,
            }
            for o in ops
        ],
        meta={"count": len(ops)},
    )


@router.get("/system/openapi.json")
def serve_spec(registry: SpecRegistry = Depends(get_registry)):
    """Віддаємо спеку як є — майбутній SPEC_URL для інших інстансів."""
    from fastapi.responses import JSONResponse

    return JSONResponse(content=registry.raw)


def _admin_ids() -> set[int]:
    """Адмін-id: {1} + M1ID_ADMIN_USER_IDS (через кому/крапку з комою).
    Сміття в env ігноруємо. Та сама семантика, що в routers/plugins.py."""
    ids = {1}
    extra = getattr(get_settings(), "admin_user_ids", "") or ""
    for part in str(extra).replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return ids


@router.post("/system/spec/reload")
def spec_reload(registry: SpecRegistry = Depends(get_registry),
                user: User = Depends(get_current_user)) -> dict:
    """Перечитати спеку без рестарту (URL → кеш → файл).

    Лише для адміністраторів: ендпоінт перебудовує індекс операцій
    (fetch SPEC_URL + перебудова) — звичайний користувач не повинен
    його смикати."""
    from app.core.responses import ApiError, ok

    if user.id not in _admin_ids():
        raise ApiError(403, "forbidden", "__all__", "admin_only")

    settings = get_settings()
    try:
        source = registry.load_chain(
            spec_url=settings.spec_url,
            cache_dir=settings.spec_cache_dir,
            primary_file=Path(settings.spec_file),
            # B7: __file__ = backend/app/routers/system.py → parents[3] = m1-id/,
            # узгоджено з main.py (там parents[2] = m1-id/, бо __file__ на рівень
            # вище). Спільний снапшот у корені m1-id/ для обох.
            fallback_files=[
                Path(__file__).resolve().parents[3] / "openapi.json",
            ],
        )
    except RuntimeError as exc:
        # в єдиному конверті, а не {"detail": ...} повз Normalizer
        raise ApiError(503, "spec_unavailable", "__all__", str(exc)) from exc
    return ok({"source": source, "stats": registry.stats()})
