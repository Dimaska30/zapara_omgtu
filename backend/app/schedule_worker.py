"""Conservative schedule cache worker; disabled until an interval is configured."""
import json
import http.client
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from uuid import uuid4

from sqlalchemy import text

from app.database import get_engine

LOG = logging.getLogger("zapara.schedule_worker")
BASE_URL = "https://rasp.omgtu.ru/api/schedule"
MAX_BYTES = 8 * 1024 * 1024
LEASE_SECONDS = 180


class FetchError(Exception):
    def __init__(self, code: str, retry_seconds: int = 0):
        self.code = code
        self.retry_seconds = retry_seconds


def retry_after(value: str | None) -> int:
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return max(0, int((parsed - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return 0


def fetch_window(job: dict) -> list:
    query = urllib.parse.urlencode({"start": job["range_start"].isoformat(),
                                    "finish": job["range_end"].isoformat(), "lng": 1})
    url = f'{BASE_URL}/{job["entity_kind"]}/{job["external_id"]}?{query}'
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Zapara-schedule-cache/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise FetchError("response_too_large")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"http_{exc.code}", retry_after(exc.headers.get("Retry-After"))) from exc
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        raise FetchError("upstream_unavailable") from exc
    try:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("not a list")
        for event in payload:
            if not isinstance(event, dict) or not isinstance(event.get("date"), str):
                raise ValueError("invalid event")
            event_date = date.fromisoformat(event["date"].replace(".", "-"))
            if not job["range_start"] <= event_date <= job["range_end"]:
                raise ValueError("event outside window")
            # Without usable time an event cannot be used to assert availability.
            start, end = event.get("beginLesson"), event.get("endLesson")
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("missing time")
            start_time = datetime.strptime(start, "%H:%M").time()
            end_time = datetime.strptime(end, "%H:%M").time()
            if end_time <= start_time:
                raise ValueError("invalid interval")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise FetchError("partial_or_invalid_response") from exc
    return payload


def run_once(interval: int) -> bool:
    engine = get_engine()
    with engine.connect() as connection:
        # Session lock covers the HTTP request as well; it is released on connection loss.
        locked = connection.execute(text("SELECT pg_try_advisory_lock(hashtext('zapara.omgtu.schedule'))")).scalar_one()
        connection.commit()
        if not locked:
            return False
        try:
            with connection.begin():
                source = connection.execute(text("""
                    SELECT next_allowed_at, locked_until FROM zapara.schedule_source_limit
                    WHERE source = 'omgtu' FOR UPDATE
                """)).mappings().one()
                now = datetime.now(timezone.utc)
                if source["next_allowed_at"] > now or (source["locked_until"] and source["locked_until"] > now):
                    return False
                # Refresh previously requested windows in the current and next four
                # weeks while they have been used recently. Department discovery
                # and creation of new windows are a later stage.
                connection.execute(text("""
                    INSERT INTO zapara.schedule_jobs (window_id)
                    SELECT w.id FROM zapara.schedule_windows w
                    WHERE w.last_accessed_at >= now() - interval '30 days'
                      AND w.range_start >= date_trunc('week', now() AT TIME ZONE 'Asia/Omsk')::date
                      AND w.range_start < date_trunc('week', now() AT TIME ZONE 'Asia/Omsk')::date + 35
                      AND (w.last_success_at IS NULL OR w.last_success_at <= now() - interval '24 hours')
                    ON CONFLICT (window_id) DO NOTHING
                """))
                job = connection.execute(text("""
                    SELECT j.window_id, j.failures, w.entity_kind, w.external_id, w.range_start, w.range_end
                    FROM zapara.schedule_jobs j JOIN zapara.schedule_windows w ON w.id = j.window_id
                    WHERE (j.status = 'pending' AND j.due_at <= now())
                       OR (j.status = 'running' AND j.locked_until <= now())
                    ORDER BY j.due_at, j.window_id FOR UPDATE OF j SKIP LOCKED LIMIT 1
                """)).mappings().first()
                if job is None:
                    return False
                job = dict(job)
                token = str(uuid4())
                connection.execute(text("""
                    UPDATE zapara.schedule_jobs SET status = 'running', lease_token = :token,
                        locked_until = now() + (:lease * interval '1 second') WHERE window_id = :id
                """), {"token": token, "lease": LEASE_SECONDS, "id": job["window_id"]})
                connection.execute(text("""
                    UPDATE zapara.schedule_source_limit SET lease_token = :token,
                        locked_until = now() + (:lease * interval '1 second'),
                        next_allowed_at = now() + (:delay * interval '1 second') WHERE source = 'omgtu'
                """), {"token": token, "lease": LEASE_SECONDS, "delay": interval})
            try:
                payload = fetch_window(job)
                error = None
            except FetchError as exc:
                payload = None
                error = exc
            with connection.begin():
                active = connection.execute(text("""
                    SELECT 1 FROM zapara.schedule_jobs j JOIN zapara.schedule_source_limit s ON s.source = 'omgtu'
                    WHERE j.window_id = :id AND j.lease_token = :token AND j.locked_until > now()
                      AND s.lease_token = :token AND s.locked_until > now() FOR UPDATE OF j, s
                """), {"id": job["window_id"], "token": token}).scalar_one_or_none()
                if active is None:
                    LOG.warning("Discarded response after lease expired")
                    return False
                if error is None:
                    connection.execute(text("""
                        UPDATE zapara.schedule_windows SET payload = CAST(:payload AS jsonb),
                            last_success_at = now(), last_attempt_at = now(), last_error = NULL WHERE id = :id
                    """), {"payload": json.dumps(payload, ensure_ascii=False), "id": job["window_id"]})
                    connection.execute(text("DELETE FROM zapara.schedule_jobs WHERE window_id = :id"), {"id": job["window_id"]})
                else:
                    delay = max(error.retry_seconds, min(3600, 30 * (2 ** min(job["failures"], 7))) + random.randint(0, 15))
                    connection.execute(text("UPDATE zapara.schedule_windows SET last_attempt_at = now(), last_error = :error WHERE id = :id"), {"id": job["window_id"], "error": error.code})
                    connection.execute(text("""
                        UPDATE zapara.schedule_jobs SET status = 'pending', lease_token = NULL, locked_until = NULL,
                            failures = failures + 1, due_at = now() + (:delay * interval '1 second') WHERE window_id = :id
                    """), {"delay": delay, "id": job["window_id"]})
                    if error.code == "http_429":
                        connection.execute(text("""
                            UPDATE zapara.schedule_source_limit SET next_allowed_at = greatest(next_allowed_at, now() + (:delay * interval '1 second'))
                            WHERE source = 'omgtu'
                        """), {"delay": delay})
                    LOG.warning("Schedule request failed: %s", error.code)
                connection.execute(text("""
                    UPDATE zapara.schedule_source_limit SET lease_token = NULL, locked_until = NULL
                    WHERE source = 'omgtu' AND lease_token = :token
                """), {"token": token})
            return True
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtext('zapara.omgtu.schedule'))"))
            connection.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    value = os.environ.get("ZAPARA_UPSTREAM_INTERVAL_SECONDS", "")
    if not value.isdecimal() or int(value) < 10:
        raise SystemExit("Set ZAPARA_UPSTREAM_INTERVAL_SECONDS to an agreed value of at least 10 seconds")
    interval = int(value)
    LOG.info("Schedule worker started")
    while True:
        try:
            if not run_once(interval):
                time.sleep(2)
        except Exception:
            LOG.exception("Worker iteration failed")
            time.sleep(10)


if __name__ == "__main__":
    main()
