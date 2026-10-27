"""Opaque bearer sessions and administrator-issued one-time account tokens."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import get_engine

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
passwords = PasswordHasher()
DUMMY_HASH = passwords.hash("nonexistent-user-password")


def digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def issue_account_token(connection, user_id, kind: str, actor_id=None) -> str:
    token = secrets.token_urlsafe(32)
    connection.execute(text("""UPDATE zapara.account_tokens SET revoked_at=now()
        WHERE user_id=:user_id AND kind=:kind AND used_at IS NULL AND revoked_at IS NULL"""),
        {"user_id": user_id, "kind": kind})
    connection.execute(text("""INSERT INTO zapara.account_tokens
        (id,user_id,kind,token_hash,expires_at,created_by)
        VALUES (:id,:user_id,:kind,:token_hash,now()+interval '24 hours',:actor_id)"""),
        {"id": uuid4(), "user_id": user_id, "kind": kind, "token_hash": digest(token), "actor_id": actor_id})
    return token


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class TokenPassword(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=1024)


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Требуется вход")
    token = authorization[7:]
    if len(token) > 128:
        raise HTTPException(401, "Недействительная сессия")
    with get_engine().connect() as connection:
        user = connection.execute(text("""SELECT u.id,u.email,u.display_name,s.id AS session_id
            FROM zapara.sessions s JOIN zapara.users u ON u.id=s.user_id
            WHERE s.token_hash=:hash AND s.revoked_at IS NULL AND s.expires_at>now()
              AND u.disabled_at IS NULL AND u.activated_at IS NOT NULL
              AND (EXISTS (SELECT 1 FROM zapara.memberships m WHERE m.user_id=u.id AND m.status='active')
                   OR EXISTS (SELECT 1 FROM zapara.system_admins a WHERE a.user_id=u.id AND a.revoked_at IS NULL))"""),
            {"hash": digest(token)}).mappings().first()
    if user is None:
        raise HTTPException(401, "Недействительная сессия")
    return dict(user)


@router.post("/login")
def login(body: Login, request: Request) -> dict:
    email = body.email.strip().lower()
    # Both address and IP are limited, without trusting forwarded headers.
    ip = request.client.host if request.client else "unknown"
    keys = sorted([digest("email:" + email), digest("ip:" + ip)])
    blocked = False
    success = False
    session_token = None
    with get_engine().begin() as connection:
        for key in keys:
            connection.execute(text("INSERT INTO zapara.login_limits (key_hash) VALUES (:key) ON CONFLICT DO NOTHING"), {"key": key})
        limits = connection.execute(text("SELECT key_hash,blocked_until FROM zapara.login_limits WHERE key_hash IN (:a,:b) ORDER BY key_hash FOR UPDATE"), {"a": keys[0], "b": keys[1]}).mappings().all()
        blocked = any(x["blocked_until"] and x["blocked_until"] > datetime.now(timezone.utc) for x in limits)
        if not blocked:
            user = connection.execute(text("SELECT id,password_hash,activated_at,disabled_at FROM zapara.users WHERE lower(email)=:email"), {"email": email}).mappings().first()
            try:
                valid = passwords.verify(user["password_hash"] if user and user["password_hash"] else DUMMY_HASH, body.password)
            except (VerifyMismatchError, InvalidHashError):
                valid = False
            success = bool(valid and user and user["activated_at"] and not user["disabled_at"])
            if success:
                session_token = secrets.token_urlsafe(32)
                connection.execute(text("INSERT INTO zapara.sessions(id,user_id,token_hash,expires_at) VALUES (:id,:user_id,:hash,now()+interval '12 hours')"), {"id": uuid4(), "user_id": user["id"], "hash": digest(session_token)})
                connection.execute(text("UPDATE zapara.users SET last_login_at=now() WHERE id=:id"), {"id": user["id"]})
                connection.execute(text("UPDATE zapara.login_limits SET failures=0,blocked_until=NULL,last_attempt_at=now() WHERE key_hash IN (:a,:b)"), {"a": keys[0], "b": keys[1]})
            else:
                connection.execute(text("""UPDATE zapara.login_limits SET failures=CASE WHEN last_attempt_at < now()-interval '15 minutes' THEN 1 ELSE failures+1 END,
                    blocked_until=CASE WHEN last_attempt_at >= now()-interval '15 minutes' AND failures+1 >= 10 THEN now()+interval '15 minutes' ELSE NULL END,
                    last_attempt_at=now() WHERE key_hash IN (:a,:b)"""), {"a": keys[0], "b": keys[1]})
    if blocked:
        raise HTTPException(429, "Попробуйте позже")
    if not success:
        raise HTTPException(401, "Неверные учётные данные")
    return {"access_token": session_token, "token_type": "bearer", "expires_in": 43200}


@router.post("/activate")
def activate(body: TokenPassword) -> dict:
    # Hash outside the transaction to avoid holding DB locks during Argon2 work.
    new_hash = passwords.hash(body.password)
    with get_engine().begin() as connection:
        row = connection.execute(text("""SELECT t.id,t.user_id,t.kind FROM zapara.account_tokens t
            JOIN zapara.users u ON u.id=t.user_id WHERE t.token_hash=:hash AND t.used_at IS NULL
            AND t.revoked_at IS NULL AND t.expires_at>now() AND u.disabled_at IS NULL FOR UPDATE OF t,u"""), {"hash": digest(body.token)}).mappings().first()
        if row is None:
            raise HTTPException(400, "Ссылка недействительна или истекла")
        connection.execute(text("UPDATE zapara.users SET password_hash=:hash,activated_at=coalesce(activated_at,now()) WHERE id=:id"), {"hash": new_hash, "id": row["user_id"]})
        connection.execute(text("UPDATE zapara.account_tokens SET used_at=now() WHERE id=:id"), {"id": row["id"]})
        connection.execute(text("UPDATE zapara.account_tokens SET revoked_at=now() WHERE user_id=:id AND used_at IS NULL AND revoked_at IS NULL"), {"id": row["user_id"]})
        connection.execute(text("UPDATE zapara.sessions SET revoked_at=now() WHERE user_id=:id AND revoked_at IS NULL"), {"id": row["user_id"]})
        connection.execute(text("INSERT INTO zapara.account_audit(target_id,action) VALUES (:id,:action)"), {"id": row["user_id"], "action": "account_token_used"})
    return {"status": "ok"}


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}


@router.post("/logout")
def logout(user: dict = Depends(current_user)) -> dict:
    with get_engine().begin() as connection:
        connection.execute(text("UPDATE zapara.sessions SET revoked_at=now() WHERE id=:id"), {"id": user["session_id"]})
    return {"status": "ok"}
