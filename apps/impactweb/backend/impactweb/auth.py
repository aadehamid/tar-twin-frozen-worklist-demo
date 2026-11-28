"""Authentication and token isolation for IMPACT Web (AUTH_MODE=local | exe + machine tokens)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlmodel import Session, select

from impactweb.models import ExerciseMembership, UserAccount


def hash_password(password: str, salt: str = "tar-twin-demo-salt") -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return base64.urlsafe_b64encode(dk).decode("ascii")


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or stored_hash.startswith("!"):
        return False
    return hmac.compare_digest(hash_password(password), stored_hash)


def issue_jwt(user_id: str, email: str, secret: str, ttl_seconds: int = 86_400) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_dict = {"sub": user_id, "email": email, "exp": int(time.time()) + ttl_seconds}
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode()).decode().rstrip("=")
    sig_bytes = hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")
    return f"{header}.{payload}.{sig}"


def decode_jwt(token: str, secret: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header, payload, sig = parts
    expected = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    ).decode().rstrip("=")
    if not hmac.compare_digest(sig, expected):
        return None
    pad = "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + pad).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < int(time.time()):
        return None
    return data


@dataclass(frozen=True)
class Caller:
    kind: str  # "user" | "twin_sync" | "twin_raise"
    user: UserAccount | None = None
    token_id: str | None = None


def resolve_caller(
    request: Request,
    session: Session,
    *,
    auth_mode: str,
    jwt_secret: str,
    edge_auth_secret: str,
    twin_sync_token: str,
    twin_raise_token: str,
) -> Caller:
    auth_hdr = request.headers.get("Authorization", "")
    if auth_hdr.startswith("Bearer "):
        token = auth_hdr[len("Bearer ") :].strip()
        if twin_sync_token and hmac.compare_digest(token, twin_sync_token):
            return Caller(kind="twin_sync", token_id="twin_sync_ro")
        if twin_raise_token and hmac.compare_digest(token, twin_raise_token):
            return Caller(kind="twin_raise", token_id="twin_delegate_raise")
        if auth_mode == "local":
            claims = decode_jwt(token, jwt_secret)
            if claims and claims.get("sub"):
                user = session.get(UserAccount, claims["sub"])
                if user is not None:
                    return Caller(kind="user", user=user)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if auth_mode == "exe":
        edge_secret = request.headers.get("X-Edge-Auth", "")
        email = request.headers.get("X-ExeDev-Email", "").strip().lower()
        if not edge_secret or not edge_auth_secret or not hmac.compare_digest(edge_secret, edge_auth_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid edge auth header")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-ExeDev-Email header")
        user = session.exec(select(UserAccount).where(UserAccount.email == email)).first()
        if user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No membership for this exe.dev account")
        return Caller(kind="user", user=user)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def get_membership(session: Session, exercise_id: str, user_id: str) -> ExerciseMembership | None:
    return session.exec(
        select(ExerciseMembership).where(
            ExerciseMembership.exercise_id == exercise_id,
            ExerciseMembership.user_id == user_id,
        )
    ).first()
