from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database import get_engine

router = APIRouter(prefix="/api/v1/dictionaries", tags=["dictionaries"])
Kind = Literal["groups", "lecturers", "buildings", "auditoriums"]


@router.get("/{kind}")
def get_dictionary(
    kind: Kind,
    building_oid: str | None = Query(default=None, alias="buildingOid", pattern=r"^[0-9]{1,20}$"),
) -> dict:
    if building_oid is not None and kind != "auditoriums":
        raise HTTPException(status_code=422, detail="buildingOid применим только к аудиториям")
    scope = building_oid or ""
    now = datetime.now(timezone.utc)
    with get_engine().begin() as connection:
        row = connection.execute(text("""
            INSERT INTO zapara.dictionary_cache (kind, scope) VALUES (:kind, :scope)
            ON CONFLICT (kind, scope) DO UPDATE SET last_accessed_at = now()
            RETURNING id, payload, last_success_at, last_error
        """), {"kind": kind, "scope": scope}).mappings().one()
        fresh = row["last_success_at"] is not None and now - row["last_success_at"] < timedelta(hours=24)
        if not fresh:
            connection.execute(text("""
                INSERT INTO zapara.dictionary_jobs (cache_id) VALUES (:id)
                ON CONFLICT (cache_id) DO NOTHING
            """), {"id": row["id"]})
        if fresh:
            state = "fresh"
        elif row["payload"] is not None:
            state = "stale"
        elif row["last_error"] is not None:
            state = "unknown"
        else:
            state = "loading"
    return {"kind": kind, "building_oid": building_oid, "state": state,
            "last_success_at": row["last_success_at"],
            "error": row["last_error"] if not fresh else None,
            "items": row["payload"] if row["payload"] is not None else []}
