import json
from datetime import date, time
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import current_user
from app.database import get_engine
from app.schedule_alerts import mark_checked_conflicts

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


class NewPlan(BaseModel):
    department_id: UUID
    kind: Literal['consultation','retake','meeting','substitution']
    title: str = Field(default='', max_length=300)


class Resource(BaseModel):
    kind: Literal['person','group','auditorium']
    external_id: str = Field(pattern=r'^[0-9]{1,20}$')
    display_name: str = Field(default='', max_length=200)


class NewSlot(BaseModel):
    version: int = Field(gt=0)
    event_date: date
    slot_number: int = Field(gt=0, le=20)
    starts_at: time
    ends_at: time
    resources: list[Resource] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_times(self):
        if self.starts_at.tzinfo or self.ends_at.tzinfo or self.ends_at <= self.starts_at:
            raise ValueError('Укажите корректное местное время пары')
        return self


class NewSubstitution(BaseModel):
    version: int = Field(gt=0)
    slot_id: UUID
    original_person_id: str = Field(pattern=r'^[0-9]{1,20}$')
    substitute_person_id: str = Field(pattern=r'^[0-9]{1,20}$')
    source_snapshot: dict


def get_plan(connection, plan_id, user_id, action='view', lock=False):
    row = connection.execute(text("""SELECT p.*,m.role,m.status AS membership_status,g.permission
        FROM zapara.plans p JOIN zapara.memberships m ON m.department_id=p.department_id AND m.user_id=:user
        LEFT JOIN zapara.plan_grants g ON g.plan_id=p.id AND g.user_id=:user
        WHERE p.id=:id AND m.status='active'""" + (" FOR UPDATE OF p FOR SHARE OF m" if lock else "")), {"id": plan_id, "user": user_id}).mappings().first()
    if not row:
        raise HTTPException(404, 'План не найден')
    if action != 'view':
        if row['role'] not in ('admin','planner') or (row['owner_id'] != user_id and row['permission'] not in (('edit','confirm') if action=='edit' else ('confirm',))):
            raise HTTPException(403, 'Нет прав на изменение плана')
    return row


def advance(connection, plan, version, actor_id, action, details=None):
    if plan['version'] != version:
        raise HTTPException(409, 'План изменился; обновите данные')
    connection.execute(text('UPDATE zapara.plans SET version=version+1,updated_at=now() WHERE id=:id'), {'id':plan['id']})
    connection.execute(text('INSERT INTO zapara.plan_activity(plan_id,actor_id,action,details) VALUES (:plan,:actor,:action,CAST(:details AS jsonb))'), {'plan':plan['id'],'actor':actor_id,'action':action,'details':json.dumps(details or {},ensure_ascii=False)})


@router.post('', status_code=201)
def create_plan(body: NewPlan, user: dict = Depends(current_user)) -> dict:
    plan_id = uuid4()
    with get_engine().begin() as connection:
        role = connection.execute(text("SELECT role FROM zapara.memberships WHERE user_id=:user AND department_id=:department AND status='active'"), {'user':user['id'],'department':body.department_id}).scalar_one_or_none()
        if role not in ('admin','planner'):
            raise HTTPException(403, 'Нет права создавать планы кафедры')
        connection.execute(text('INSERT INTO zapara.plans(id,department_id,owner_id,kind,title) VALUES (:id,:department,:owner,:kind,:title)'), {'id':plan_id,'department':body.department_id,'owner':user['id'],'kind':body.kind,'title':body.title})
        connection.execute(text("INSERT INTO zapara.plan_activity(plan_id,actor_id,action) VALUES (:id,:actor,'created')"), {'id':plan_id,'actor':user['id']})
    return {'id':plan_id,'version':1}


@router.get('')
def list_plans(department_id: UUID, user: dict = Depends(current_user)) -> list[dict]:
    with get_engine().connect() as connection:
        rows = connection.execute(text("""SELECT p.id,p.owner_id,p.kind,p.title,p.status,p.version,p.updated_at
            FROM zapara.plans p JOIN zapara.memberships m ON m.department_id=p.department_id
            WHERE p.department_id=:department AND m.user_id=:user AND m.status='active' AND p.status<>'archived'
            ORDER BY p.updated_at DESC LIMIT 500"""), {'department':department_id,'user':user['id']}).mappings().all()
    return [dict(row) for row in rows]


@router.get('/{plan_id}')
def read_plan(plan_id: UUID, user: dict = Depends(current_user)) -> dict:
    with get_engine().connect() as connection:
        plan = dict(get_plan(connection,plan_id,user['id']))
        slots = [dict(row) for row in connection.execute(text('SELECT * FROM zapara.plan_slots WHERE plan_id=:id ORDER BY event_date,slot_number'), {'id':plan_id}).mappings().all()]
        for slot in slots:
            slot['resources'] = [dict(r) for r in connection.execute(text('SELECT kind,external_id,display_name FROM zapara.slot_resources WHERE slot_id=:id ORDER BY kind,display_name'), {'id':slot['id']}).mappings().all()]
            slot['substitutions'] = [dict(r) for r in connection.execute(text('SELECT * FROM zapara.substitutions WHERE slot_id=:id ORDER BY created_at'), {'id':slot['id']}).mappings().all()]
    plan['slots']=slots
    return plan


@router.post('/{plan_id}/slots', status_code=201)
def add_slot(plan_id: UUID, body: NewSlot, user: dict = Depends(current_user)) -> dict:
    slot_id=uuid4()
    try:
        with get_engine().begin() as connection:
            plan=get_plan(connection,plan_id,user['id'],'edit',True)
            if plan['status'] != 'draft': raise HTTPException(409,'Изменять можно только черновик')
            advance(connection,plan,body.version,user['id'],'slot_added',{'slot_id':str(slot_id)})
            connection.execute(text('INSERT INTO zapara.plan_slots(id,plan_id,event_date,slot_number,starts_at,ends_at) VALUES (:id,:plan,:day,:number,:start,:end)'), {'id':slot_id,'plan':plan_id,'day':body.event_date,'number':body.slot_number,'start':body.starts_at,'end':body.ends_at})
            for resource in body.resources:
                connection.execute(text('INSERT INTO zapara.slot_resources(slot_id,kind,external_id,display_name) VALUES (:slot,:kind,:external_id,:display_name)'), {'slot':slot_id,**resource.model_dump()})
    except IntegrityError:
        raise HTTPException(409,'Пара или участник уже добавлены') from None
    return {'id':slot_id,'version':body.version+1}


@router.post('/{plan_id}/substitutions',status_code=201)
def add_substitution(plan_id: UUID, body: NewSubstitution, user: dict = Depends(current_user)) -> dict:
    if body.original_person_id == body.substitute_person_id: raise HTTPException(422,'Выберите другого преподавателя')
    if not body.source_snapshot: raise HTTPException(422,'Нужны сведения об исходном занятии')
    sub_id=uuid4()
    with get_engine().begin() as connection:
        plan=get_plan(connection,plan_id,user['id'],'edit',True)
        if plan['kind']!='substitution' or plan['status']!='draft': raise HTTPException(409,'Нужен черновик плана замен')
        if not connection.execute(text('SELECT 1 FROM zapara.plan_slots WHERE id=:slot AND plan_id=:plan'), {'slot':body.slot_id,'plan':plan_id}).first(): raise HTTPException(404,'Пара не найдена')
        advance(connection,plan,body.version,user['id'],'substitution_selected',{'substitution_id':str(sub_id)})
        connection.execute(text('INSERT INTO zapara.substitutions(id,slot_id,original_person_id,substitute_person_id,source_snapshot) VALUES (:id,:slot,:original,:substitute,CAST(:snapshot AS jsonb))'), {'id':sub_id,'slot':body.slot_id,'original':body.original_person_id,'substitute':body.substitute_person_id,'snapshot':json.dumps(body.source_snapshot,ensure_ascii=False)})
    return {'id':sub_id,'version':body.version+1}


class Grant(BaseModel):
    version: int = Field(gt=0)
    user_id: UUID
    permission: Literal['edit','confirm']


@router.put('/{plan_id}/grants')
def grant_access(plan_id: UUID, body: Grant, user: dict = Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        plan=get_plan(connection,plan_id,user['id'],'edit',True)
        if plan['owner_id'] != user['id']: raise HTTPException(403,'Доступ назначает автор плана')
        target=connection.execute(text("SELECT 1 FROM zapara.memberships WHERE user_id=:user AND department_id=:department AND status='active' AND role IN ('admin','planner')"), {'user':body.user_id,'department':plan['department_id']}).first()
        if not target: raise HTTPException(422,'Сотрудник не может изменять планы этой кафедры')
        advance(connection,plan,body.version,user['id'],'grant_changed',{'user_id':str(body.user_id),'permission':body.permission})
        connection.execute(text("""INSERT INTO zapara.plan_grants(plan_id,user_id,permission,granted_by) VALUES (:plan,:target,:permission,:actor)
            ON CONFLICT(plan_id,user_id) DO UPDATE SET permission=excluded.permission,granted_by=excluded.granted_by"""), {'plan':plan_id,'target':body.user_id,'permission':body.permission,'actor':user['id']})
    return {'version':body.version+1}


class ConfirmSubstitution(BaseModel):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)
    expected_conflict_hash: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


def check_substitution(connection, plan, slot, assignment):
    from datetime import datetime, timedelta, timezone
    import hashlib

    person=assignment['substitute_person_id']
    start=slot['event_date']-timedelta(days=slot['event_date'].weekday())
    window=connection.execute(text("""SELECT payload,last_success_at FROM zapara.schedule_windows
        WHERE entity_kind='person' AND external_id=:person AND range_start=:start"""), {'person':person,'start':start}).mappings().first()
    issues=[]
    if not window or window['last_success_at'] is None or window['last_success_at'] <= datetime.now(timezone.utc)-timedelta(hours=24):
        issues.append({'kind':'unknown_schedule'})
    else:
        for event in window['payload']:
            if event.get('date','').replace('.','-') != slot['event_date'].isoformat(): continue
            begin=datetime.strptime(event['beginLesson'],'%H:%M').time(); end=datetime.strptime(event['endLesson'],'%H:%M').time()
            if begin < slot['ends_at'] and end > slot['starts_at']:
                issues.append({'kind':'source_conflict','lesson':event.get('discipline',''), 'start':event['beginLesson'],'end':event['endLesson']})
    other=connection.execute(text("""SELECT p.id AS plan_id,s.id AS substitution_id,p.title
        FROM zapara.substitutions s JOIN zapara.plan_slots sl ON sl.id=s.slot_id
        JOIN zapara.plans p ON p.id=sl.plan_id
        WHERE s.substitute_person_id=:person AND s.status='confirmed' AND p.status<>'archived'
          AND p.department_id=:department AND sl.event_date=:day
          AND sl.starts_at<:end AND sl.ends_at>:start AND s.id<>:id
        ORDER BY s.id"""), {'person':person,'department':plan['department_id'],'day':slot['event_date'],
               'start':slot['starts_at'],'end':slot['ends_at'],'id':assignment['id']}).mappings().all()
    for row in other:
        issues.append({'kind':'same_plan_conflict' if row['plan_id']==plan['id'] else 'plan_conflict',
                       'plan_id':str(row['plan_id']),'substitution_id':str(row['substitution_id']),'title':row['title']})
    planned=connection.execute(text("""SELECT p.id AS plan_id,p.title,sl.id AS slot_id FROM zapara.slot_resources r
        JOIN zapara.plan_slots sl ON sl.id=r.slot_id JOIN zapara.plans p ON p.id=sl.plan_id
        WHERE r.kind='person' AND r.external_id=:person AND sl.status='confirmed' AND p.status<>'archived'
          AND p.department_id=:department AND sl.event_date=:day AND sl.starts_at<:end AND sl.ends_at>:start
        ORDER BY sl.id"""), {'person':person,'department':plan['department_id'],'day':slot['event_date'],'start':slot['starts_at'],'end':slot['ends_at']}).mappings().all()
    for row in planned:
        issues.append({'kind':'same_plan_conflict' if row['plan_id']==plan['id'] else 'plan_conflict',
                       'plan_id':str(row['plan_id']),'slot_id':str(row['slot_id']),'title':row['title']})
    encoded=json.dumps(issues,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return issues,hashlib.sha256(encoded).hexdigest()


@router.post('/{plan_id}/substitutions/{sub_id}/confirm')
def confirm_substitution(plan_id: UUID, sub_id: UUID, body: ConfirmSubstitution, user: dict = Depends(current_user)) -> dict:
    from app.resource_locks import lock_resource
    with get_engine().begin() as connection:
        get_plan(connection,plan_id,user['id'],'confirm')
        initial=connection.execute(text("""SELECT s.substitute_person_id,sl.event_date FROM zapara.substitutions s
            JOIN zapara.plan_slots sl ON sl.id=s.slot_id WHERE s.id=:sub AND sl.plan_id=:plan"""), {'sub':sub_id,'plan':plan_id}).mappings().first()
        if not initial: raise HTTPException(404,'Замена не найдена')
        lock_resource(connection,'person',initial['substitute_person_id'],initial['event_date'])
        plan=get_plan(connection,plan_id,user['id'],'confirm',True)
        assignment=connection.execute(text('SELECT * FROM zapara.substitutions WHERE id=:id FOR UPDATE'), {'id':sub_id}).mappings().one()
        slot=connection.execute(text('SELECT * FROM zapara.plan_slots WHERE id=:id AND plan_id=:plan'), {'id':assignment['slot_id'],'plan':plan_id}).mappings().one()
        if plan['version']!=body.version: raise HTTPException(409,'План изменился; обновите данные')
        if plan['status']=='archived' or assignment['status']!='selected': raise HTTPException(409,'Замена недоступна для подтверждения')
        issues,fingerprint=check_substitution(connection,plan,slot,assignment)
        if any(issue['kind']=='same_plan_conflict' for issue in issues):
            raise HTTPException(409,{'message':'Преподаватель уже назначен в этом плане','issues':issues})
        can_override=connection.execute(text("SELECT role='admin' OR can_override_source_conflict FROM zapara.memberships WHERE user_id=:user AND department_id=:department AND status='active'"), {'user':user['id'],'department':plan['department_id']}).scalar_one()
        if any(issue['kind']=='source_conflict' for issue in issues) and not can_override:
            raise HTTPException(403,{'message':'Преподаватель занят; необходимо право обхода','issues':issues})
        if issues and (not body.reason or not body.reason.strip() or body.expected_conflict_hash!=fingerprint):
            raise HTTPException(409,{'message':'Проверьте конфликты и укажите причину','issues':issues,'conflict_hash':fingerprint})
        advance(connection,plan,body.version,user['id'],'substitution_confirmed',{'substitution_id':str(sub_id),'reason':body.reason,'issues':issues})
        connection.execute(text("UPDATE zapara.substitutions SET status='confirmed',confirmed_by=:actor,confirmed_at=now() WHERE id=:id"), {'actor':user['id'],'id':sub_id})
        mark_checked_conflicts(connection,'substitution',sub_id,issues,assignment['substitute_person_id'])
        recipient=connection.execute(text("SELECT user_id FROM zapara.teacher_links WHERE person_id=:person"), {'person':assignment['substitute_person_id']}).scalar_one_or_none()
        if recipient:
            connection.execute(text("INSERT INTO zapara.notifications(id,user_id,plan_id,kind,payload) VALUES (:id,:user,:plan,'substitution_confirmed',CAST(:payload AS jsonb))"), {'id':uuid4(),'user':recipient,'plan':plan_id,'payload':json.dumps({'event_date':slot['event_date'].isoformat(),'slot_number':slot['slot_number']})})
    return {'status':'confirmed','version':body.version+1}


class VersionBody(BaseModel):
    version: int = Field(gt=0)


@router.post('/{plan_id}/substitutions/{sub_id}/cancel')
def cancel_substitution(plan_id: UUID, sub_id: UUID, body: VersionBody, user: dict = Depends(current_user)) -> dict:
    from app.resource_locks import lock_resource
    with get_engine().begin() as connection:
        get_plan(connection,plan_id,user['id'],'confirm')
        initial=connection.execute(text("SELECT s.substitute_person_id,sl.event_date FROM zapara.substitutions s JOIN zapara.plan_slots sl ON sl.id=s.slot_id WHERE s.id=:id AND sl.plan_id=:plan"), {'id':sub_id,'plan':plan_id}).mappings().first()
        if not initial: raise HTTPException(404,'Замена не найдена')
        lock_resource(connection,'person',initial['substitute_person_id'],initial['event_date'])
        plan=get_plan(connection,plan_id,user['id'],'confirm',True)
        assignment=connection.execute(text('SELECT * FROM zapara.substitutions WHERE id=:id FOR UPDATE'), {'id':sub_id}).mappings().one()
        if plan['status']=='archived' or assignment['status']=='cancelled': raise HTTPException(409,'Замена уже отменена или план архивирован')
        advance(connection,plan,body.version,user['id'],'substitution_cancelled',{'substitution_id':str(sub_id)})
        connection.execute(text("UPDATE zapara.substitutions SET status='cancelled' WHERE id=:id"), {'id':sub_id})
        if assignment['status']=='confirmed':
            recipient=connection.execute(text('SELECT user_id FROM zapara.teacher_links WHERE person_id=:person'), {'person':assignment['substitute_person_id']}).scalar_one_or_none()
            if recipient:
                connection.execute(text("INSERT INTO zapara.notifications(id,user_id,plan_id,kind,payload) VALUES (:id,:user,:plan,'substitution_cancelled',CAST(:payload AS jsonb))"), {'id':uuid4(),'user':recipient,'plan':plan_id,'payload':json.dumps({'substitution_id':str(sub_id)})})
    return {'status':'cancelled','version':body.version+1}


@router.post('/{plan_id}/archive')
def archive_plan(plan_id: UUID, body: VersionBody, user: dict = Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        plan=get_plan(connection,plan_id,user['id'],'edit',True)
        if plan['status']=='archived': raise HTTPException(409,'План уже архивирован')
        future=connection.execute(text("""SELECT EXISTS(SELECT 1 FROM zapara.substitutions s JOIN zapara.plan_slots sl ON sl.id=s.slot_id
            WHERE sl.plan_id=:id AND s.status='confirmed' AND ((sl.event_date+sl.ends_at) AT TIME ZONE sl.timezone)>now())"""), {'id':plan_id}).scalar_one()
        if future: raise HTTPException(409,'Сначала отмените или перенесите будущие подтверждённые замены')
        advance(connection,plan,body.version,user['id'],'archived')
        connection.execute(text("UPDATE zapara.plans SET status='archived' WHERE id=:id"), {'id':plan_id})
    return {'status':'archived','version':body.version+1}


@router.post('/{plan_id}/slots/{slot_id}/confirm')
def confirm_slot(plan_id: UUID, slot_id: UUID, body: ConfirmSubstitution, user: dict = Depends(current_user)) -> dict:
    import hashlib
    from datetime import datetime, timedelta, timezone
    from app.resource_locks import lock_resource

    with get_engine().begin() as connection:
        get_plan(connection,plan_id,user['id'],'confirm')
        slot=connection.execute(text('SELECT * FROM zapara.plan_slots WHERE id=:id AND plan_id=:plan'), {'id':slot_id,'plan':plan_id}).mappings().first()
        if not slot: raise HTTPException(404,'Пара не найдена')
        initial=[(r.kind,r.external_id) for r in connection.execute(text('SELECT kind,external_id FROM zapara.slot_resources WHERE slot_id=:id ORDER BY kind,external_id'), {'id':slot_id})]
        if not initial: raise HTTPException(422,'Укажите участников или аудиторию')
        for kind, external_id in initial: lock_resource(connection,kind,external_id,slot['event_date'])
        plan=get_plan(connection,plan_id,user['id'],'confirm',True)
        slot=connection.execute(text('SELECT * FROM zapara.plan_slots WHERE id=:id AND plan_id=:plan FOR UPDATE'), {'id':slot_id,'plan':plan_id}).mappings().one()
        current=[(r.kind,r.external_id) for r in connection.execute(text('SELECT kind,external_id FROM zapara.slot_resources WHERE slot_id=:id ORDER BY kind,external_id'), {'id':slot_id})]
        if initial!=current or plan['version']!=body.version: raise HTTPException(409,'План изменился; обновите данные')
        if plan['kind']=='substitution' or plan['status']=='archived' or slot['status']!='selected': raise HTTPException(409,'Эту пару нельзя подтвердить')
        week=slot['event_date']-timedelta(days=slot['event_date'].weekday())
        issues=[]
        for kind,external_id in current:
            window=connection.execute(text('SELECT payload,last_success_at FROM zapara.schedule_windows WHERE entity_kind=:kind AND external_id=:id AND range_start=:start'), {'kind':kind,'id':external_id,'start':week}).mappings().first()
            if not window or not window['last_success_at'] or window['last_success_at']<=datetime.now(timezone.utc)-timedelta(hours=24):
                issues.append({'kind':'unknown_schedule','resource_kind':kind,'resource_id':external_id})
            else:
                for event in window['payload']:
                    if event.get('date','').replace('.','-') != slot['event_date'].isoformat(): continue
                    if datetime.strptime(event['beginLesson'],'%H:%M').time()<slot['ends_at'] and datetime.strptime(event['endLesson'],'%H:%M').time()>slot['starts_at']:
                        issues.append({'kind':'source_conflict','resource_kind':kind,'resource_id':external_id,'lesson':event.get('discipline',''),'start':event['beginLesson'],'end':event['endLesson']})
            rows=connection.execute(text("""SELECT p.id AS plan_id,p.title,s.id AS slot_id FROM zapara.slot_resources r
                JOIN zapara.plan_slots s ON s.id=r.slot_id JOIN zapara.plans p ON p.id=s.plan_id
                WHERE r.kind=:kind AND r.external_id=:resource AND s.status='confirmed' AND p.status<>'archived'
                  AND p.department_id=:department AND s.event_date=:day AND s.starts_at<:end AND s.ends_at>:start AND s.id<>:slot
                ORDER BY s.id"""), {'kind':kind,'resource':external_id,'department':plan['department_id'],'day':slot['event_date'],'start':slot['starts_at'],'end':slot['ends_at'],'slot':slot_id}).mappings().all()
            for row in rows:
                issues.append({'kind':'same_plan_conflict' if row['plan_id']==plan_id else 'plan_conflict','resource_kind':kind,'resource_id':external_id,'plan_id':str(row['plan_id']),'slot_id':str(row['slot_id']),'title':row['title']})
        for kind,external_id in current:
            if kind != 'person': continue
            assignments=connection.execute(text("""SELECT p.id AS plan_id,p.title,s.id AS substitution_id FROM zapara.substitutions s
                JOIN zapara.plan_slots sl ON sl.id=s.slot_id JOIN zapara.plans p ON p.id=sl.plan_id
                WHERE s.substitute_person_id=:person AND s.status='confirmed' AND p.status<>'archived'
                  AND p.department_id=:department AND sl.event_date=:day AND sl.starts_at<:end AND sl.ends_at>:start
                ORDER BY s.id"""), {'person':external_id,'department':plan['department_id'],'day':slot['event_date'],'start':slot['starts_at'],'end':slot['ends_at']}).mappings().all()
            for row in assignments:
                issues.append({'kind':'same_plan_conflict' if row['plan_id']==plan_id else 'plan_conflict','resource_kind':'person','resource_id':external_id,'plan_id':str(row['plan_id']),'substitution_id':str(row['substitution_id']),'title':row['title']})
        if any(issue['kind']=='same_plan_conflict' for issue in issues): raise HTTPException(409,{'message':'Участник уже назначен в этом плане','issues':issues})
        can_override=connection.execute(text("SELECT role='admin' OR can_override_source_conflict FROM zapara.memberships WHERE user_id=:user AND department_id=:department AND status='active'"), {'user':user['id'],'department':plan['department_id']}).scalar_one()
        if any(issue['kind']=='source_conflict' for issue in issues) and not can_override:
            raise HTTPException(403,{'message':'Участник или аудитория заняты; необходимо право обхода','issues':issues})
        fingerprint=hashlib.sha256(json.dumps(issues,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if issues and (not body.reason or not body.reason.strip() or body.expected_conflict_hash!=fingerprint): raise HTTPException(409,{'message':'Проверьте конфликты и укажите причину','issues':issues,'conflict_hash':fingerprint})
        advance(connection,plan,body.version,user['id'],'slot_confirmed',{'slot_id':str(slot_id),'reason':body.reason,'issues':issues})
        connection.execute(text("UPDATE zapara.plan_slots SET status='confirmed' WHERE id=:id"), {'id':slot_id})
        mark_checked_conflicts(connection,'slot',slot_id,issues)
    return {'status':'confirmed','version':body.version+1}
