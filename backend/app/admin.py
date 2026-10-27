from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import current_user, issue_account_token
from app.database import get_engine

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_admin(connection, actor_id, department_id) -> None:
    allowed = connection.execute(text("""SELECT EXISTS (
        SELECT 1 FROM zapara.system_admins WHERE user_id=:actor AND revoked_at IS NULL
        UNION ALL SELECT 1 FROM zapara.memberships WHERE user_id=:actor AND department_id=:department
          AND role='admin' AND status='active')"""), {"actor": actor_id, "department": department_id}).scalar_one()
    if not allowed:
        raise HTTPException(403, "Нет прав администратора кафедры")


class NewAccount(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=200)
    department_id: UUID
    role: str = Field(pattern="^(planner|viewer)$")
    lecturer_oid: str = Field(pattern=r"^[0-9]{1,20}$")
    person_id: str = Field(pattern=r"^[0-9]{1,20}$")


@router.get("/departments")
def departments(user: dict = Depends(current_user)) -> list[dict]:
    with get_engine().connect() as connection:
        rows = connection.execute(text("""SELECT DISTINCT d.id,d.name,d.source_chair_oid,m.role
            FROM zapara.departments d JOIN zapara.memberships m ON m.department_id=d.id
            WHERE m.user_id=:user AND m.status='active' ORDER BY d.name"""), {"user": user["id"]}).mappings().all()
    return [dict(row) for row in rows]


@router.get("/departments/{department_id}/users")
def list_users(department_id: UUID, user: dict = Depends(current_user)) -> list[dict]:
    with get_engine().connect() as connection:
        require_admin(connection, user["id"], department_id)
        rows = connection.execute(text("""SELECT u.id,u.email,u.display_name,u.activated_at,u.disabled_at,
            m.role,m.status,m.version,m.can_override_source_conflict FROM zapara.memberships m JOIN zapara.users u ON u.id=m.user_id
            WHERE m.department_id=:department ORDER BY u.display_name LIMIT 500"""), {"department": department_id}).mappings().all()
    return [dict(row) for row in rows]


@router.post("/users", status_code=201)
def create_user(body: NewAccount, actor: dict = Depends(current_user)) -> dict:
    email, name = body.email.strip().lower(), body.display_name.strip()
    if '@' not in email or not name:
        raise HTTPException(422, "Укажите имя и email")
    user_id = uuid4()
    try:
        with get_engine().begin() as connection:
            require_admin(connection, actor["id"], body.department_id)
            # The person and lecturer ID are separate namespaces. Require an
            # exact pair in the last cached dictionary for the requested chair.
            matches = connection.execute(text("""SELECT item FROM zapara.dictionary_cache c,
                jsonb_array_elements(c.payload) AS item JOIN zapara.departments d ON d.id=:department
                WHERE c.kind='lecturers' AND c.scope='' AND c.last_success_at > now()-interval '24 hours'
                  AND item->>'lecturerOid'=:lecturer AND item->>'person'=:person
                  AND item->>'chairOid'=d.source_chair_oid"""), {"department": body.department_id, "lecturer": body.lecturer_oid, "person": body.person_id}).all()
            if len(matches) != 1:
                raise HTTPException(409, "Не удалось однозначно проверить преподавателя в актуальном справочнике")
            connection.execute(text("INSERT INTO zapara.users(id,email,display_name) VALUES (:id,:email,:name)"), {"id": user_id, "email": email, "name": name})
            connection.execute(text("INSERT INTO zapara.memberships(id,user_id,department_id,role) VALUES (:id,:user,:department,:role)"), {"id": uuid4(), "user": user_id, "department": body.department_id, "role": body.role})
            connection.execute(text("INSERT INTO zapara.teacher_links(user_id,person_id,lecturer_oid,verified_by) VALUES (:user,:person,:lecturer,:actor)"), {"user": user_id, "person": body.person_id, "lecturer": body.lecturer_oid, "actor": actor["id"]})
            token = issue_account_token(connection, user_id, "invitation", actor["id"])
            connection.execute(text("INSERT INTO zapara.account_audit(actor_id,target_id,department_id,action) VALUES (:actor,:target,:department,'invite')"), {"actor": actor["id"], "target": user_id, "department": body.department_id})
    except IntegrityError:
        raise HTTPException(409, "Аккаунт или привязка преподавателя уже существуют") from None
    return {"user_id": user_id, "activation_token": token, "expires_in": 86400}


@router.post("/departments/{department_id}/users/{target_id}/password-reset")
def password_reset(department_id: UUID, target_id: UUID, actor: dict = Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        require_admin(connection, actor["id"], department_id)
        target = connection.execute(text("""SELECT u.id,m.role,
            EXISTS (SELECT 1 FROM zapara.system_admins s WHERE s.user_id=u.id AND s.revoked_at IS NULL) AS is_system_admin
            FROM zapara.users u JOIN zapara.memberships m ON m.user_id=u.id
            WHERE u.id=:user AND m.department_id=:department AND m.status='active' AND u.disabled_at IS NULL FOR UPDATE OF u"""), {"user": target_id, "department": department_id}).mappings().first()
        if not target:
            raise HTTPException(404, "Пользователь не найден")
        is_system_admin = connection.execute(text("SELECT EXISTS (SELECT 1 FROM zapara.system_admins WHERE user_id=:id AND revoked_at IS NULL)"), {"id": actor["id"]}).scalar_one()
        if not is_system_admin and (target["role"] == "admin" or target["is_system_admin"]):
            raise HTTPException(403, "Сброс пароля администратора доступен системному администратору")
        token = issue_account_token(connection, target_id, "password_reset", actor["id"])
        connection.execute(text("INSERT INTO zapara.account_audit(actor_id,target_id,department_id,action) VALUES (:actor,:target,:department,'password_reset_issued')"), {"actor": actor["id"], "target": target_id, "department": department_id})
    return {"reset_token": token, "expires_in": 86400}


class OverridePermission(BaseModel):
    enabled: bool


@router.put('/departments/{department_id}/users/{target_id}/override-permission')
def set_override_permission(department_id: UUID, target_id: UUID, body: OverridePermission, actor: dict = Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        require_admin(connection,actor['id'],department_id)
        result=connection.execute(text("""UPDATE zapara.memberships SET can_override_source_conflict=:enabled,version=version+1
            WHERE department_id=:department AND user_id=:target AND status='active'"""), {'enabled':body.enabled,'department':department_id,'target':target_id})
        if result.rowcount==0: raise HTTPException(404,'Сотрудник не найден')
        connection.execute(text("INSERT INTO zapara.account_audit(actor_id,target_id,department_id,action,details) VALUES (:actor,:target,:department,'override_permission_changed',jsonb_build_object('enabled',CAST(:enabled AS boolean)))"), {'actor':actor['id'],'target':target_id,'department':department_id,'enabled':body.enabled})
    return {'enabled':body.enabled}


class MembershipUpdate(BaseModel):
    version: int = Field(gt=0)
    status: str = Field(pattern='^(active|suspended|revoked)$')


@router.patch('/departments/{department_id}/users/{target_id}/membership')
def update_membership(department_id: UUID, target_id: UUID, body: MembershipUpdate, actor: dict = Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        require_admin(connection,actor['id'],department_id)
        membership=connection.execute(text("SELECT role,status,version FROM zapara.memberships WHERE department_id=:department AND user_id=:target FOR UPDATE"), {'department':department_id,'target':target_id}).mappings().first()
        if not membership: raise HTTPException(404,'Членство не найдено')
        system_admin=connection.execute(text("SELECT EXISTS(SELECT 1 FROM zapara.system_admins WHERE user_id=:actor AND revoked_at IS NULL)"), {'actor':actor['id']}).scalar_one()
        if membership['role']=='admin' and not system_admin: raise HTTPException(403,'Управление администраторами доступно системному администратору')
        if actor['id']==target_id and body.status!='active': raise HTTPException(409,'Нельзя приостановить собственное членство')
        if membership['version']!=body.version: raise HTTPException(409,'Членство изменилось; обновите данные')
        connection.execute(text('UPDATE zapara.memberships SET status=:status,version=version+1 WHERE department_id=:department AND user_id=:target'), {'status':body.status,'department':department_id,'target':target_id})
        connection.execute(text("INSERT INTO zapara.account_audit(actor_id,target_id,department_id,action,details) VALUES (:actor,:target,:department,'membership_status_changed',jsonb_build_object('status',CAST(:status AS text)))"), {'actor':actor['id'],'target':target_id,'department':department_id,'status':body.status})
    return {'status':body.status,'version':body.version+1}


class TeacherLink(BaseModel):
    lecturer_oid: str = Field(pattern=r'^[0-9]{1,20}$')
    person_id: str = Field(pattern=r'^[0-9]{1,20}$')


@router.put('/departments/{department_id}/users/{target_id}/teacher-link')
def replace_teacher_link(department_id: UUID, target_id: UUID, body: TeacherLink, actor: dict = Depends(current_user)) -> dict:
    try:
        with get_engine().begin() as connection:
            require_admin(connection,actor['id'],department_id)
            target=connection.execute(text("SELECT 1 FROM zapara.users u JOIN zapara.memberships m ON m.user_id=u.id WHERE u.id=:id AND m.department_id=:department AND m.status='active' FOR UPDATE OF u"), {'id':target_id,'department':department_id}).first()
            if not target: raise HTTPException(404,'Сотрудник не найден')
            matches=connection.execute(text("""SELECT item FROM zapara.dictionary_cache c,
                jsonb_array_elements(c.payload) AS item JOIN zapara.departments d ON d.id=:department
                WHERE c.kind='lecturers' AND c.scope='' AND c.last_success_at>now()-interval '24 hours'
                  AND item->>'lecturerOid'=:lecturer AND item->>'person'=:person AND item->>'chairOid'=d.source_chair_oid"""), {'department':department_id,'lecturer':body.lecturer_oid,'person':body.person_id}).all()
            if len(matches)!=1: raise HTTPException(409,'Не удалось однозначно проверить преподавателя в актуальном справочнике')
            connection.execute(text('DELETE FROM zapara.teacher_links WHERE user_id=:user'), {'user':target_id})
            connection.execute(text('INSERT INTO zapara.teacher_links(user_id,person_id,lecturer_oid,verified_by) VALUES (:user,:person,:lecturer,:actor)'), {'user':target_id,'person':body.person_id,'lecturer':body.lecturer_oid,'actor':actor['id']})
            connection.execute(text("INSERT INTO zapara.account_audit(actor_id,target_id,department_id,action,details) VALUES (:actor,:target,:department,'teacher_link_changed',jsonb_build_object('person_id',CAST(:person AS text),'lecturer_oid',CAST(:lecturer AS text)))"), {'actor':actor['id'],'target':target_id,'department':department_id,'person':body.person_id,'lecturer':body.lecturer_oid})
    except IntegrityError:
        raise HTTPException(409,'Преподаватель уже привязан к другому аккаунту') from None
    return {'status':'ok'}
