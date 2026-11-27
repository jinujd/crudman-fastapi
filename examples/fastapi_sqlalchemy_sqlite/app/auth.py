"""DEMO authentication: tokens are "<role>:<user id>", e.g. "Bearer admin:1".

Never use this in production; replace current_user with real token verification (JWT, sessions, …).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, object]:
    if creds is None or ":" not in creds.credentials:
        raise HTTPException(401, "Send 'Authorization: Bearer <role>:<id>' (demo tokens)")
    role, _, user_id = creds.credentials.partition(":")
    if not user_id.isdigit():
        raise HTTPException(401, "Invalid demo token")
    return {"id": int(user_id), "role": role}
