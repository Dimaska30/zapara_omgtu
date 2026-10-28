from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text

from app.database import get_engine
from app.auth import current_user

router = APIRouter(prefix="/api/v1/schedule", tags=["schedule"], dependencies=[Depends(current_user)])
Kind = Literal["person", "group", "auditorium", "building"]


@router.get("/{kind}/{external_id}")
def get_schedule(
    kind: Kind,
    external_id: str = Path(pattern=r"^[0-9]{1,20}$"),
    start: date = Query(),
    finish: date = Query(),
    include_events: bool = Query(default=True),
) -> dict:
    if finish < start or (finish - start).days > 90:
        raise HTTPException(status_code=422, detail="Период должен быть от 1 до 91 дня")

    week = start - timedelta(days=start.weekday())
    coverage = []
    events = []
    now = datetime.now(timezone.utc)
    with get_engine().begin() as connection:
        while week <= finish:
            payload_select = ", payload" if include_events else ""
            row = connection.execute(text(f"""
                INSERT INTO zapara.schedule_windows
                    (entity_kind, external_id, range_start, range_end)
                VALUES (:kind, :external_id, :start, :end)
                ON CONFLICT (entity_kind, external_id, range_start)
                DO UPDATE SET last_accessed_at = now()
                RETURNING id{payload_select}, last_success_at, last_error
            """), {"kind": kind, "external_id": external_id, "start": week,
                   "end": week + timedelta(days=6)}).mappings().one()
            fresh = row["last_success_at"] is not None and now - row["last_success_at"] < timedelta(hours=24)
            if not fresh:
                connection.execute(text("""
                    INSERT INTO zapara.schedule_jobs (window_id) VALUES (:window_id)
                    ON CONFLICT (window_id) DO NOTHING
                """), {"window_id": row["id"]})
            job = connection.execute(text("SELECT status FROM zapara.schedule_jobs WHERE window_id = :id"), {"id": row["id"]}).scalar_one_or_none()
            if fresh:
                state = "fresh"
            elif row["last_success_at"] is not None:
                state = "stale"
            elif row["last_error"] is not None:
                state = "unknown"
            else:
                state = "loading" if job else "unknown"
            coverage.append({"start": week, "end": week + timedelta(days=6),
                             "state": state, "last_success_at": row["last_success_at"],
                             "error": row["last_error"] if not fresh else None})
            if include_events and row["payload"] is not None:
                for event in row["payload"]:
                    event_date = date.fromisoformat(event["date"].replace(".", "-"))
                    if start <= event_date <= finish:
                        events.append(event)
            week += timedelta(days=7)
    return {"kind": kind, "external_id": external_id, "start": start, "finish": finish,
            "coverage": coverage, "events": events if include_events else [],
            "complete": all(item["state"] == "fresh" for item in coverage)}
