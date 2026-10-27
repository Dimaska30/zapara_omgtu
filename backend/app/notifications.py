from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.auth import current_user
from app.database import get_engine

router=APIRouter(prefix='/api/v1/notifications',tags=['notifications'])


@router.get('')
def notifications(user: dict=Depends(current_user)) -> list[dict]:
    with get_engine().connect() as connection:
        rows=connection.execute(text('SELECT id,kind,payload,created_at,read_at FROM zapara.notifications WHERE user_id=:user ORDER BY created_at DESC LIMIT 200'), {'user':user['id']}).mappings().all()
    return [dict(row) for row in rows]


@router.post('/{notification_id}/read')
def read_notification(notification_id: UUID,user: dict=Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        result=connection.execute(text('UPDATE zapara.notifications SET read_at=coalesce(read_at,now()) WHERE id=:id AND user_id=:user'), {'id':notification_id,'user':user['id']})
        if result.rowcount==0: raise HTTPException(404,'Уведомление не найдено')
    return {'status':'ok'}
