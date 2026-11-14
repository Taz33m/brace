"""The contract's error envelope. Messages are user-safe: no stack traces or secrets."""
from __future__ import annotations


class PlatformError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False,
                 current_revision: int | None = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.current_revision = retryable, current_revision

    def envelope(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable,
                          "current_revision": self.current_revision}}


def not_found(what: str = "This item") -> PlatformError:
    return PlatformError(404, "not_found", f"{what} was not found.")


def unauthenticated() -> PlatformError:
    return PlatformError(401, "unauthenticated", "Sign in to continue.")


def forbidden() -> PlatformError:
    return PlatformError(403, "forbidden", "You do not have access to this.")


def invalid(message: str, code: str = "invalid_request") -> PlatformError:
    return PlatformError(422, code, message)


def revision_conflict(current: int) -> PlatformError:
    return PlatformError(409, "revision_conflict", "This case changed. Reload before applying this edit.",
                         retryable=True, current_revision=current)
