"""Actors, token hashing, and the owner secret bootstrap.

Raw invitation and session tokens are only ever returned to the caller once; the
database stores SHA-256 hashes. The owner secret comes from BRACE_OWNER_SECRET and
there is no default: unset or empty disables owner login.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Literal, Optional

from .errors import PlatformError

OWNER_SECRET_ENV = "BRACE_OWNER_SECRET"
LOCAL_OWNER_ID = "owner:local"


@dataclass(frozen=True)
class Actor:
    role: Literal["owner", "resident", "system"]
    actor_id: str
    case_id: Optional[str] = None
    household_id: Optional[str] = None


SYSTEM = Actor(role="system", actor_id="system:platform")


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_owner_secret(secret: str) -> bool:
    configured = os.environ.get(OWNER_SECRET_ENV, "")
    if not configured:
        raise PlatformError(503, "owner_login_disabled",
                            "Owner sign-in is not configured on this server.")
    return hmac.compare_digest(secret.encode("utf-8"), configured.encode("utf-8"))
