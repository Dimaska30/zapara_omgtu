"""Public, read-only schedule views backed by the shared database cache."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query

from app.dictionaries import get_dictionary
from app.database import get_engine
from app.schedule import get_schedule
from sqlalchemy import text

router = APIRouter(prefix="/api/v1/public", tags=["public schedule"])


@router.get("/dictionaries/{kind}")
def public_dictionary(
    kind: Literal["groups", "lecturers", "buildings", "auditoriums"],
    building_oid: str | None = Query(default=None, alias="buildingOid", pattern=r"^[0-9]{1,20}$"),
    chair_oid: str | None = Query(default=None, alias="chairOid", pattern=r"^[0-9]{1,20}$"),
) -> dict:
    if building_oid is not None and chair_oid is not None:
        raise HTTPException(status_code=422, detail="Укажите только один фильтр справочника")
    return get_dictionary(kind, building_oid, chair_oid)


@router.get("/schedule/{kind}/{external_id}")
def public_schedule(
    kind: Literal["person", "group", "auditorium", "building"],
    external_id: str = Path(pattern=r"^[0-9]{1,20}$"),
    start: date = Query(),
    finish: date = Query(),
    include_events: bool = Query(default=True),
) -> dict:
    return get_schedule(kind, external_id, start, finish, include_events)


@router.get("/planned-events")
def public_planned_events(start: date = Query(), finish: date = Query()) -> dict:
    """Sanitized calendar overlay for saved departmental plans.

    Draft selections are shared as well as confirmed entries, so the calendar
    can show the same state to every viewer. Cancellation and archived plans
    are omitted; plan settings and account data are never exposed.
    """
    if finish < start or (finish - start).days > 90:
        raise HTTPException(status_code=422, detail="Период должен быть от 1 до 91 дня")

    with get_engine().connect() as connection:
        slots = connection.execute(text("""
            SELECT p.id AS plan_id, p.kind, p.title AS plan_title, p.status AS plan_status,
                   sl.id AS slot_id, sl.event_date, sl.slot_number, sl.starts_at, sl.ends_at, sl.status AS slot_status,
                   r.kind AS resource_kind, r.external_id, r.display_name,
                   s.original_person_id, s.substitute_person_id, s.source_snapshot, s.status AS substitution_status
            FROM zapara.plans p
            JOIN zapara.departments d ON d.id=p.department_id AND d.source_chair_oid='46'
            JOIN zapara.plan_slots sl ON sl.plan_id=p.id
            LEFT JOIN zapara.slot_resources r ON r.slot_id=sl.id
            LEFT JOIN zapara.substitutions s ON s.slot_id=sl.id AND s.status<>'cancelled'
            WHERE p.status NOT IN ('archived','cancelled') AND sl.status<>'cancelled'
              AND sl.event_date BETWEEN :start AND :finish
            ORDER BY sl.event_date, sl.slot_number, p.created_at
        """), {"start": start, "finish": finish}).mappings().all()
        group_dictionary = connection.execute(text("""
            SELECT payload FROM zapara.dictionary_cache WHERE kind='groups' AND scope=''
        """)).scalar_one_or_none()

    groups = group_dictionary if isinstance(group_dictionary, list) else []
    resources_by_slot: dict[str, list[tuple[str, str, str]]] = {}
    for row in slots:
        if row["resource_kind"] and row["external_id"]:
            resource = (str(row["resource_kind"]), str(row["external_id"]), str(row["display_name"] or ""))
            bucket = resources_by_slot.setdefault(str(row["slot_id"]), [])
            if resource not in bucket:
                bucket.append(resource)
    def matching_group_id(label: str) -> str | None:
        normalized = "".join(char for char in label.casefold().replace("ё", "е") if char.isalnum())
        candidates = []
        for item in groups:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("number") or "")
            compact = "".join(char for char in name.casefold().replace("ё", "е") if char.isalnum())
            oid = item.get("groupOid") or item.get("id") or item.get("oid")
            if oid and compact and compact in normalized:
                candidates.append((len(compact), str(oid)))
        return max(candidates)[1] if candidates else None

    events: list[dict] = []
    seen: set[tuple] = set()
    kind_labels = {"consultation": "Консультация", "retake": "Пересдача", "meeting": "Встреча", "substitution": "Замена"}
    for row in slots:
        day = row["event_date"].isoformat()
        begin = row["starts_at"].strftime("%H:%M")
        end = row["ends_at"].strftime("%H:%M")
        kind = row["kind"]
        is_substitution = kind == "substitution" and row["substitute_person_id"] is not None
        if is_substitution:
            snapshot = row["source_snapshot"] if isinstance(row["source_snapshot"], dict) else {}
            lesson = snapshot.get("lesson") if isinstance(snapshot.get("lesson"), dict) else {}
            raw = lesson.get("rawEvent") if isinstance(lesson.get("rawEvent"), dict) else {}
            title = str(lesson.get("discipline") or "Занятие")
            original = str(snapshot.get("original_label") or row["original_person_id"])
            substitute = str(snapshot.get("replacement_label") or row["substitute_person_id"])
            resources = [("person", str(row["substitute_person_id"]), substitute),
                         ("person", str(row["original_person_id"]), original)]
            group_label = str(lesson.get("group") or raw.get("group") or "")
            group_id = str(raw.get("groupOid") or raw.get("groupId") or raw.get("group_id") or "") or (matching_group_id(group_label) if group_label else None)
            if group_id:
                resources.append(("group", group_id, group_label))
            room_id = raw.get("auditoriumOid")
            if room_id:
                resources.append(("auditorium", str(room_id), str(lesson.get("auditorium") or raw.get("auditorium") or "")))
            for target_kind, target_id, target_name in resources:
                marker = (row["slot_id"], target_kind, target_id)
                if marker in seen:
                    continue
                seen.add(marker)
                events.append({"plan_event_id": f"{row['plan_id']}:{row['slot_id']}:{target_kind}:{target_id}", "target_kind": target_kind, "target_id": target_id, "target_name": target_name,
                    "date": day, "beginLesson": begin, "endLesson": end, "discipline": title,
                    "lecturer": substitute if target_kind != "person" or target_id != str(row["original_person_id"]) else f"Замена: {original} → {substitute}",
                    "group": group_label or None, "subgroup": lesson.get("subgroup"),
                    "auditorium": lesson.get("auditorium"), "building": lesson.get("building"),
                    "source_lesson_oid": raw.get("lessonOid"),
                    "plan_kind": kind, "plan_status": row["substitution_status"]})
            continue

        title = str(row["plan_title"] or kind_labels.get(kind, "План кафедры"))
        slot_resources = resources_by_slot.get(str(row["slot_id"]), [])
        people = [name for resource_kind, _, name in slot_resources if resource_kind == "person" and name]
        group_names = [name for resource_kind, _, name in slot_resources if resource_kind == "group" and name]
        room_names = [name for resource_kind, _, name in slot_resources if resource_kind == "auditorium" and name]
        for resource_kind, external_id, display_name in slot_resources:
            marker = (row["slot_id"], resource_kind, str(external_id))
            if marker in seen:
                continue
            seen.add(marker)
            events.append({"plan_event_id": f"{row['plan_id']}:{row['slot_id']}:{resource_kind}:{external_id}", "target_kind": resource_kind, "target_id": str(external_id), "target_name": str(display_name or ""),
                "date": day, "beginLesson": begin, "endLesson": end, "discipline": title,
                "lecturer": str(display_name) if resource_kind == "person" else (people[0] if people else None),
                "group": str(display_name) if resource_kind == "group" else (group_names[0] if group_names else None),
                "auditorium": str(display_name) if resource_kind == "auditorium" else (room_names[0] if room_names else None),
                "source_lesson_oid": None,
                "plan_kind": kind, "plan_status": row["slot_status"] if row["slot_status"] == "confirmed" else "selected"})
    return {"events": events}
