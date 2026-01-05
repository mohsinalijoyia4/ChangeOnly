from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request, Response
from itsdangerous import URLSafeSerializer, BadSignature
from sqlmodel import Session, select

from .config import settings
from .models import User, MagicLink

SESSION_COOKIE = "changeonly_session"
SESSION_TTL_DAYS = 30

def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt="changeonly-session")

def _magic_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt="changeonly-magic")

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def make_unsubscribe_token(user: User) -> str:
    msg = f"{user.id}:{user.email}:{user.unsub_token_salt}".encode("utf-8")
    digest = hmac.new(settings.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return digest

def verify_unsubscribe_token(s: Session, token: str) -> Optional[User]:
    users = s.exec(select(User)).all()
    for u in users:
        if make_unsubscribe_token(u) == token:
            return u
    return None

def set_session(response: Response, user_id: int) -> None:
    payload = {"uid": user_id, "exp": int((datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)).timestamp())}
    cookie_val = _serializer().dumps(payload)
    response.set_cookie(
        SESSION_COOKIE,
        cookie_val,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 86400,
        path="/",
    )

def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")

def get_current_user(s: Session, request: Request) -> Optional[User]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
    except BadSignature:
        return None
    exp = int(data.get("exp", 0))
    if exp <= int(datetime.utcnow().timestamp()):
        return None
    uid = data.get("uid")
    if not uid:
        return None
    return s.get(User, uid)

def issue_magic_link(s: Session, email: str, minutes: int = 15) -> str:
    raw = _magic_serializer().dumps({"e": email, "n": os.urandom(16).hex(), "t": int(datetime.utcnow().timestamp())})
    token_hash = _hash_token(raw)
    ml = MagicLink(email=email, token_hash=token_hash, expires_at=datetime.utcnow() + timedelta(minutes=minutes))
    s.add(ml)
    s.commit()
    return raw

def consume_magic_link(s: Session, token: str) -> Optional[User]:
    token_hash = _hash_token(token)
    ml = s.exec(select(MagicLink).where(MagicLink.token_hash == token_hash)).first()
    if not ml or ml.used_at is not None or ml.expires_at < datetime.utcnow():
        return None
    ml.used_at = datetime.utcnow()
    s.add(ml)

    user = s.exec(select(User).where(User.email == ml.email)).first()
    if not user:
        user = User(email=ml.email, unsub_token_salt=os.urandom(16).hex())
        s.add(user)
        s.commit()
        s.refresh(user)

    user.last_login_at = datetime.utcnow()
    s.add(user)
    s.commit()
    return user
