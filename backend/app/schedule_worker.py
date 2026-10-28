"""Conservative schedule cache worker; disabled until an interval is configured."""
import json
import http.client
from html.parser import HTMLParser
import logging
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from uuid import uuid4

from sqlalchemy import text

from app.database import get_engine
from app.resource_locks import lock_resource
from app.schedule_alerts import update_schedule_alerts

LOG = logging.getLogger("zapara.schedule_worker")
BASE_URL = "https://rasp.omgtu.ru/api/schedule"
TEACHING_COMPOSITION_URL = "https://omgtu.ru/general_information/faculties/faculty_of_information_technology_and_computer_systems/department_of_applied_mathematics_and_basic_science_quot/teaching_composition.php"
PFI_CHAIR_OID = "46"
MAX_BYTES = 8 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
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


def fetch_json(url: str) -> list:
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
    except (ValueError, TypeError, UnicodeError) as exc:
        raise FetchError("partial_or_invalid_response") from exc
    return payload


class TeachingCompositionParser(HTMLParser):
    """Extract public staff names, profile IDs, and job titles from the chair page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self.anchor: dict | None = None
        self.in_paragraph = False
        self.paragraph_has_profile = False
        self.paragraph_text: list[str] = []
        self.pending_position: int | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "p":
            self.in_paragraph = True
            self.paragraph_has_profile = False
            self.paragraph_text = []
        if tag == "a":
            match = re.search(r"/ecab/persons/\?f=(\d+)", attrs.get("href", ""))
            if match:
                self.anchor = {"profile_oid": match.group(1), "name_parts": []}
                self.paragraph_has_profile = True

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["name_parts"].append(data)
        if self.in_paragraph:
            self.paragraph_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            item = {"profile_oid": self.anchor["profile_oid"], "name": " ".join("".join(self.anchor["name_parts"]).split())}
            self.anchor = None
            self.items.append(item)
            self.paragraph_has_profile = True
        if tag == "p" and self.in_paragraph:
            text = " ".join("".join(self.paragraph_text).split())
            if self.paragraph_has_profile:
                self.pending_position = len(self.items) - 1 if self.items else None
            elif self.pending_position is not None and text:
                self.items[self.pending_position]["position"] = text
                self.pending_position = None
            self.in_paragraph = False


def fetch_teaching_composition() -> list[dict]:
    request = urllib.request.Request(TEACHING_COMPOSITION_URL, headers={
        "Accept": "text/html", "User-Agent": "Mozilla/5.0 (compatible; Zapara-schedule-cache/1.0)"
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_HTML_BYTES + 1)
            charset = response.headers.get_content_charset() or "windows-1251"
            if len(raw) > MAX_HTML_BYTES:
                raise FetchError("response_too_large")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"http_{exc.code}", retry_after(exc.headers.get("Retry-After"))) from exc
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        raise FetchError("upstream_unavailable") from exc
    try:
        document = raw.decode(charset, "strict")
        if "Состав кафедры" not in document:
            raise ValueError("unexpected page")
        parser = TeachingCompositionParser()
        parser.feed(document)
        items = [item for item in parser.items if item["name"] and item["profile_oid"].isdigit()]
    except (LookupError, UnicodeError, ValueError) as exc:
        raise FetchError("partial_or_invalid_response") from exc
    if not items:
        raise FetchError("empty_unverified_department_roster")
    return items


def staff_name_key(value: str) -> str:
    tokens = re.findall(r"[а-яё]+", value.casefold().replace("ё", "е"))
    if len(tokens) >= 3:
        return tokens[0] + "".join(token[0] for token in tokens[1:])
    if len(tokens) == 2:
        return tokens[0] + tokens[1][0]
    return ""


def link_roster_to_schedule(roster: list[dict], lecturers: list[dict], chair_oid: str) -> list[dict]:
    by_key: dict[str, list[dict]] = {}
    for lecturer in lecturers:
        name = str(lecturer.get("shortFIO") or lecturer.get("fio") or "")
        key = staff_name_key(name)
        if key and str(lecturer.get("person", "")).isdigit():
            by_key.setdefault(key, []).append(lecturer)
    linked = []
    for person in roster:
        matches = by_key.get(staff_name_key(person["name"]), [])
        department_matches = [item for item in matches if str(item.get("chairOid", "")) == chair_oid]
        candidates = department_matches or matches
        schedule_person = candidates[0] if len(candidates) == 1 else None
        linked.append({
            **person,
            "person": str(schedule_person["person"]) if schedule_person else None,
            "lecturer_oid": str(schedule_person["lecturerOid"]) if schedule_person and schedule_person.get("lecturerOid") else None,
            "chair_oid": str(schedule_person["chairOid"]) if schedule_person and schedule_person.get("chairOid") else None,
            "schedule_name": str(schedule_person.get("shortFIO") or schedule_person.get("fio") or "") if schedule_person else "",
        })
    return linked


def refresh_cached_roster_links(connection) -> None:
    directory = connection.execute(text("""
        SELECT payload FROM zapara.dictionary_cache WHERE kind='lecturers' AND scope=''
          AND payload IS NOT NULL
    """)).scalar_one_or_none()
    if not isinstance(directory, list):
        return
    rosters = connection.execute(text("""
        SELECT id, scope, payload FROM zapara.dictionary_cache
        WHERE kind='lecturers' AND scope=:chair_oid AND payload IS NOT NULL
    """), {"chair_oid": PFI_CHAIR_OID}).mappings().all()
    for roster in rosters:
        linked = link_roster_to_schedule(roster["payload"], directory, roster["scope"])
        if linked != roster["payload"]:
            connection.execute(text("UPDATE zapara.dictionary_cache SET payload=CAST(:payload AS jsonb) WHERE id=:id"), {
                "payload": json.dumps(linked, ensure_ascii=False), "id": roster["id"]
            })


def fetch_window(job: dict) -> list:
    query = urllib.parse.urlencode({"start": job["range_start"].isoformat(),
                                    "finish": job["range_end"].isoformat(), "lng": 1})
    url = f'{BASE_URL}/{job["entity_kind"]}/{job["external_id"]}?{query}'
    payload = fetch_json(url)
    try:
        for event in payload:
            if not isinstance(event, dict) or not isinstance(event.get("date"), str):
                raise ValueError("invalid event")
            event_date = date.fromisoformat(event["date"].replace(".", "-"))
            if not job["range_start"] <= event_date <= job["range_end"]:
                raise ValueError("event outside window")
            start, end = event.get("beginLesson"), event.get("endLesson")
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError("missing time")
            if datetime.strptime(end, "%H:%M").time() <= datetime.strptime(start, "%H:%M").time():
                raise ValueError("invalid interval")
    except (ValueError, TypeError) as exc:
        raise FetchError("partial_or_invalid_response") from exc
    return payload


def fetch_dictionary(job: dict) -> list:
    kind = job["kind"]
    if kind == "lecturers" and job["scope"]:
        return fetch_teaching_composition()
    query = "?" + urllib.parse.urlencode({"buildingOid": job["scope"]}) if job["scope"] else ""
    payload = fetch_json(f"https://rasp.omgtu.ru/api/dictionary/{kind}{query}")
    # A 200 with an empty catalog has been observed for buildings; it is not
    # enough evidence to erase a previously populated dictionary.
    if not payload:
        raise FetchError("empty_unverified_dictionary")
    id_key = {"groups": "groupOid", "lecturers": "lecturerOid", "buildings": "buildingOid", "auditoriums": "auditoriumOid"}[kind]
    if any(not isinstance(item, dict) or not str(item.get(id_key, "")).isdigit() or int(item[id_key]) <= 0 for item in payload):
        raise FetchError("partial_or_invalid_response")
    if kind == "auditoriums" and job["scope"] and any(str(item.get("buildingOid")) != job["scope"] for item in payload):
        raise FetchError("partial_or_invalid_response")
    if kind == "lecturers":
        # Do not persist email addresses, HR identifiers, or other unused PII.
        fields = {"lecturerOid", "person", "fio", "shortFIO", "chair", "chairOid", "lecturer_rank"}
        return [{key: value for key, value in item.items() if key in fields} for item in payload]
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
                    SELECT next_allowed_at, locked_until, last_job_kind FROM zapara.schedule_source_limit
                    WHERE source = 'omgtu' FOR UPDATE
                """)).mappings().one()
                now = datetime.now(timezone.utc)
                if source["next_allowed_at"] > now or (source["locked_until"] and source["locked_until"] > now):
                    return False
                # Public schedule caches are maintained independently of whether
                # an admin account or department membership has been created.
                connection.execute(text("""
                    INSERT INTO zapara.dictionary_cache (kind, scope)
                    VALUES ('lecturers', '')
                    ON CONFLICT (kind, scope) DO NOTHING
                """))
                connection.execute(text("""
                    INSERT INTO zapara.dictionary_cache (kind, scope)
                    VALUES ('lecturers', :chair_oid)
                    ON CONFLICT (kind, scope) DO NOTHING
                """), {"chair_oid": PFI_CHAIR_OID})
                connection.execute(text("""
                    INSERT INTO zapara.dictionary_cache (kind, scope)
                    VALUES ('groups', '')
                    ON CONFLICT (kind, scope) DO NOTHING
                """))
                connection.execute(text("""
                    INSERT INTO zapara.dictionary_jobs (cache_id)
                    SELECT c.id FROM zapara.dictionary_cache c
                    WHERE c.kind IN ('groups', 'lecturers') AND c.scope='' AND
                        (c.last_success_at IS NULL OR c.last_success_at <= now()-interval '24 hours')
                    ON CONFLICT (cache_id) DO NOTHING
                """))
                refresh_cached_roster_links(connection)
                connection.execute(text("""
                    INSERT INTO zapara.dictionary_jobs (cache_id)
                    SELECT c.id FROM zapara.dictionary_cache c
                    WHERE c.kind='lecturers' AND c.scope=:chair_oid AND
                        (c.last_success_at IS NULL OR c.last_success_at <= now()-interval '24 hours')
                    ON CONFLICT (cache_id) DO NOTHING
                """), {"chair_oid": PFI_CHAIR_OID})
                # Keep all PMFI groups and the public staff roster's mapped IDs warm.
                connection.execute(text("""
                    INSERT INTO zapara.schedule_windows(entity_kind,external_id,range_start,range_end)
                    SELECT DISTINCT source.entity_kind,source.external_id,
                        (date_trunc('week',now() AT TIME ZONE 'Asia/Omsk')::date + n*7),
                        (date_trunc('week',now() AT TIME ZONE 'Asia/Omsk')::date + n*7 + 6)
                    FROM (
                      SELECT 'group'::text AS entity_kind, item->>'groupOid' AS external_id
                      FROM zapara.dictionary_cache c CROSS JOIN LATERAL jsonb_array_elements(c.payload) item
                      WHERE c.kind='groups' AND c.scope='' AND c.last_success_at>now()-interval '24 hours'
                        AND item->>'name' ~* '^(МО|ФИТ)м?-[0-9]+'
                        AND item->>'faculty' ILIKE '%Факультет информационных технологий и компьютерных систем%'
                      UNION ALL
                      SELECT 'person'::text, item->>'person'
                      FROM zapara.dictionary_cache c CROSS JOIN LATERAL jsonb_array_elements(c.payload) item
                      WHERE c.kind='lecturers' AND c.scope=:chair_oid AND c.last_success_at>now()-interval '24 hours'
                        AND item->>'person' ~ '^[0-9]{1,20}$'
                    ) source
                    CROSS JOIN generate_series(0,4) AS n
                    WHERE source.external_id ~ '^[0-9]{1,20}$'
                    ON CONFLICT (entity_kind,external_id,range_start) DO NOTHING
                """), {"chair_oid": PFI_CHAIR_OID})
                connection.execute(text("""
                    INSERT INTO zapara.schedule_jobs (window_id)
                    SELECT w.id FROM zapara.schedule_windows w
                    WHERE w.entity_kind IN ('person','group')
                      AND w.range_start>=date_trunc('week',now() AT TIME ZONE 'Asia/Omsk')::date
                      AND w.range_start<date_trunc('week',now() AT TIME ZONE 'Asia/Omsk')::date + 35
                      AND (w.last_success_at IS NULL OR w.last_success_at<=now()-interval '24 hours')
                      AND EXISTS (
                          SELECT 1 FROM zapara.dictionary_cache c
                          CROSS JOIN LATERAL jsonb_array_elements(c.payload) AS item
                          WHERE c.last_success_at>now()-interval '24 hours' AND (
                            (w.entity_kind='group' AND c.kind='groups' AND c.scope='' AND item->>'groupOid'=w.external_id
                              AND item->>'name' ~* '^(МО|ФИТ)м?-[0-9]+'
                              AND item->>'faculty' ILIKE '%Факультет информационных технологий и компьютерных систем%')
                            OR (w.entity_kind='person' AND c.kind='lecturers' AND c.scope=:chair_oid
                              AND item->>'person'=w.external_id)))
                    ON CONFLICT (window_id) DO NOTHING
                """), {"chair_oid": PFI_CHAIR_OID})
                # Also keep recently requested windows warm, in addition to the
                # department's baseline groups and staff schedules above.
                connection.execute(text("""
                    INSERT INTO zapara.schedule_jobs (window_id)
                    SELECT w.id FROM zapara.schedule_windows w
                    WHERE w.last_accessed_at >= now() - interval '30 days'
                      AND w.range_start >= date_trunc('week', now() AT TIME ZONE 'Asia/Omsk')::date
                      AND w.range_start < date_trunc('week', now() AT TIME ZONE 'Asia/Omsk')::date + 35
                      AND (w.last_success_at IS NULL OR w.last_success_at <= now() - interval '24 hours')
                    ON CONFLICT (window_id) DO NOTHING
                """))
                candidates = {
                    "schedule": """SELECT j.window_id AS id, j.failures, w.entity_kind, w.external_id,
                        w.range_start, w.range_end FROM zapara.schedule_jobs j
                        JOIN zapara.schedule_windows w ON w.id = j.window_id
                        WHERE (j.status = 'pending' AND j.due_at <= now()) OR
                              (j.status = 'running' AND j.locked_until <= now())
                        ORDER BY j.due_at, j.window_id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
                    "dictionary": """SELECT j.cache_id AS id, j.failures, c.kind, c.scope
                        FROM zapara.dictionary_jobs j JOIN zapara.dictionary_cache c ON c.id = j.cache_id
                        WHERE (j.status = 'pending' AND j.due_at <= now()) OR
                              (j.status = 'running' AND j.locked_until <= now())
                        ORDER BY j.due_at, j.cache_id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
                }
                order = ("dictionary", "schedule") if source["last_job_kind"] == "schedule" else ("schedule", "dictionary")
                job = None
                for job_kind in order:
                    job = connection.execute(text(candidates[job_kind])).mappings().first()
                    if job is not None:
                        break
                if job is None:
                    return False
                job = dict(job)
                job["job_kind"] = job_kind
                tables = {
                    "schedule": ("schedule_jobs", "window_id", "schedule_windows"),
                    "dictionary": ("dictionary_jobs", "cache_id", "dictionary_cache"),
                }
                job_table, job_key, cache_table = tables[job_kind]
                token = str(uuid4())
                connection.execute(text(f"""
                    UPDATE zapara.{job_table} SET status = 'running', lease_token = :token,
                        locked_until = now() + (:lease * interval '1 second') WHERE {job_key} = :id
                """), {"token": token, "lease": LEASE_SECONDS, "id": job["id"]})
                connection.execute(text("""
                    UPDATE zapara.schedule_source_limit SET lease_token = :token,
                        locked_until = now() + (:lease * interval '1 second'),
                        next_allowed_at = now() + (:delay * interval '1 second'), last_job_kind = :kind
                    WHERE source = 'omgtu'
                """), {"token": token, "lease": LEASE_SECONDS, "delay": interval, "kind": job_kind})
            try:
                payload = fetch_window(job) if job_kind == "schedule" else fetch_dictionary(job)
                error = None
            except FetchError as exc:
                payload = None
                error = exc
            with connection.begin():
                active = connection.execute(text(f"""
                    SELECT 1 FROM zapara.{job_table} j JOIN zapara.schedule_source_limit s ON s.source = 'omgtu'
                    WHERE j.{job_key} = :id AND j.lease_token = :token AND j.locked_until > now()
                      AND s.lease_token = :token AND s.locked_until > now() FOR UPDATE OF j, s
                """), {"id": job["id"], "token": token}).scalar_one_or_none()
                if active is None:
                    LOG.warning("Discarded response after lease expired")
                    return False
                if error is None:
                    if job_kind == "schedule":
                        for day in range(7):
                            lock_resource(connection, job["entity_kind"], job["external_id"], job["range_start"] + timedelta(days=day))
                    elif job["kind"] == "lecturers" and job["scope"]:
                        lecturer_directory = connection.execute(text("""
                            SELECT payload FROM zapara.dictionary_cache WHERE kind='lecturers' AND scope=''
                        """)).scalar_one_or_none()
                        if isinstance(lecturer_directory, list):
                            payload = link_roster_to_schedule(payload, lecturer_directory, job["scope"])
                    connection.execute(text(f"""
                        UPDATE zapara.{cache_table} SET payload = CAST(:payload AS jsonb),
                            last_success_at = now(), last_attempt_at = now(), last_error = NULL WHERE id = :id
                    """), {"payload": json.dumps(payload, ensure_ascii=False), "id": job["id"]})
                    if job_kind == "schedule":
                        update_schedule_alerts(connection, job, payload)
                    connection.execute(text(f"DELETE FROM zapara.{job_table} WHERE {job_key} = :id"), {"id": job["id"]})
                else:
                    delay = max(error.retry_seconds, min(3600, 30 * (2 ** min(job["failures"], 7))) + random.randint(0, 15))
                    connection.execute(text(f"UPDATE zapara.{cache_table} SET last_attempt_at = now(), last_error = :error WHERE id = :id"), {"id": job["id"], "error": error.code})
                    connection.execute(text(f"""
                        UPDATE zapara.{job_table} SET status = 'pending', lease_token = NULL, locked_until = NULL,
                            failures = failures + 1, due_at = now() + (:delay * interval '1 second') WHERE {job_key} = :id
                    """), {"delay": delay, "id": job["id"]})
                    if error.code == "http_429":
                        connection.execute(text("""
                            UPDATE zapara.schedule_source_limit SET next_allowed_at = greatest(next_allowed_at, now() + (:delay * interval '1 second'))
                            WHERE source = 'omgtu'
                        """), {"delay": delay})
                    LOG.warning("Upstream request failed: %s", error.code)
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
