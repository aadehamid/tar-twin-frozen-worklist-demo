"""Authentication and exercise-membership verification for the Digital Twin API (AUTH_MODE=local | exe)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from twin.clients import ImpactWebClient

# Fallback demo membership directory used ONLY when Twin runs standalone without an IMPACT Web client.
STANDALONE_DEMO_USERS: dict[str, dict[str, Any]] = {
    "usr-facilitator": {"id": "usr-facilitator", "email": "facilitator@demo.local", "full_name": "A. Facilitator", "role": "facilitator"},
    "usr-ta-manager": {"id": "usr-ta-manager", "email": "ta.manager@demo.local", "full_name": "M. Turnaround", "role": "ta_manager"},
    "usr-planner": {"id": "usr-planner", "email": "j.planner@demo.local", "full_name": "J. Planner", "role": "planner"},
    "usr-fixed": {"id": "usr-fixed", "email": "fixed.lead@demo.local", "full_name": "R. Fixed-Equip", "role": "source_group"},
    "usr-rotating": {"id": "usr-rotating", "email": "rotating.lead@demo.local", "full_name": "S. Rotating", "role": "source_group"},
    "usr-drb": {"id": "usr-drb", "email": "drb.member@demo.local", "full_name": "P. Review-Board", "role": "drb_member"},
    "usr-viewer": {"id": "usr-viewer", "email": "viewer@demo.local", "full_name": "V. Observer", "role": "viewer"},
}


def decode_jwt(token: str, secret: str) -> dict[str, Any] | None:
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
class AuthenticatedMember:
    user_id: str
    email: str
    full_name: str
    role: str
    exercise_id: str


def resolve_authenticated_member(
    request: Request,
    *,
    exercise_id: str,
    auth_mode: str,
    jwt_secret: str,
    edge_auth_secret: str,
    impactweb_client: ImpactWebClient | None,
) -> AuthenticatedMember:
    """Authenticate caller (JWT in local mode or X-Edge-Auth + X-ExeDev-Email in exe mode) and resolve exercise role."""
    user_id: str | None = None
    email: str | None = None

    auth_hdr = request.headers.get("Authorization", "")
    if auth_mode == "local":
        if not auth_hdr.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        token = auth_hdr[len("Bearer ") :].strip()
        claims = decode_jwt(token, jwt_secret)
        if not claims or not claims.get("sub"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
        user_id = str(claims["sub"])
        email = str(claims.get("email", "")).strip().lower()
    elif auth_mode == "exe":
        edge_secret = request.headers.get("X-Edge-Auth", "")
        raw_email = request.headers.get("X-ExeDev-Email", "").strip().lower()
        if not edge_secret or not edge_auth_secret or not hmac.compare_digest(edge_secret, edge_auth_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid edge auth header")
        if not raw_email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-ExeDev-Email header")
        email = raw_email
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unsupported auth mode")

    if impactweb_client is not None:
        try:
            mems = impactweb_client.list_memberships(exercise_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Membership lookup failed: {exc}") from exc
        for m in mems:
            m_uid = str(m.get("user_id", ""))
            m_email = str(m.get("email", "")).strip().lower()
            if (user_id and m_uid == user_id) or (email and m_email == email):
                return AuthenticatedMember(
                    user_id=m_uid,
                    email=m_email,
                    full_name=str(m.get("full_name") or m_email),
                    role=str(m.get("role", "viewer")),
                    exercise_id=exercise_id,
                )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Not a member of exercise {exercise_id}")

    # Standalone mode fallback (no IMPACT Web client wired)
    for row in STANDALONE_DEMO_USERS.values():
        if (user_id and row["id"] == user_id) or (email and row["email"] == email):
            return AuthenticatedMember(
                user_id=row["id"],
                email=row["email"],
                full_name=row["full_name"],
                role=row["role"],
                exercise_id=exercise_id,
            )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Not a member of exercise {exercise_id}")
