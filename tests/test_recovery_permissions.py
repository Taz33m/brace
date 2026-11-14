"""Invitations, sessions, and owner bootstrap: who can become whom."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.recovery.platform import auth
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OTHER_OWNER, OWNER, seeded


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media", clock=clock)


def _invite(store, household_id, ttl=timedelta(hours=72)):
    rev = store.owner_snapshot(OWNER, "case_test").case.case_revision
    return store.create_invitation(OWNER, "case_test", household_id, rev, ttl=ttl)


def test_invitation_exchange_yields_session_bound_to_household(store):
    ha, _, _, _ = seeded(store)
    result = _invite(store, ha)
    assert result.invitation_token and result.invitation_expires_at.endswith("+00:00")
    actor = store.resolve_session(store.exchange_invitation(result.invitation_token))
    assert (actor.role, actor.case_id, actor.household_id) == ("resident", "case_test", ha)


def test_invitation_requires_current_revision(store):
    ha, _, _, _ = seeded(store)
    with pytest.raises(PlatformError) as e:
        store.create_invitation(OWNER, "case_test", ha, 1)
    assert e.value.status == 409 and e.value.current_revision == 3


def test_other_owner_cannot_invite(store):
    ha, _, _, _ = seeded(store)
    with pytest.raises(PlatformError) as e:
        store.create_invitation(OTHER_OWNER, "case_test", ha, 3)
    assert e.value.status == 404


def test_invitation_for_household_of_other_case_is_rejected(store):
    seeded(store)
    with pytest.raises(PlatformError) as e:
        store.create_invitation(OWNER, "case_test", "hh_not_here", 3)
    assert e.value.status == 404


def test_expired_invitation_fails(store, clock):
    ha, _, _, _ = seeded(store)
    token = _invite(store, ha, ttl=timedelta(hours=1)).invitation_token
    clock.t += timedelta(hours=2)
    with pytest.raises(PlatformError) as e:
        store.exchange_invitation(token)
    assert e.value.status == 401


def test_unknown_invitation_fails(store):
    seeded(store)
    with pytest.raises(PlatformError) as e:
        store.exchange_invitation("not-a-real-token")
    assert e.value.status == 401


def test_revoked_invitation_fails_and_ends_its_sessions(store):
    ha, _, _, _ = seeded(store)
    result = _invite(store, ha)
    session = store.exchange_invitation(result.invitation_token)
    invitation_id = store.invitations(OWNER, "case_test")[0]["invitation_id"]
    store.revoke_invitation(OWNER, "case_test", invitation_id)
    assert store.resolve_session(session) is None
    with pytest.raises(PlatformError):
        store.exchange_invitation(result.invitation_token)
    types = [e.type for e in store.owner_snapshot(OWNER, "case_test").events]
    assert "session.revoked" in types


def test_session_expires(store, clock):
    ha, _, _, _ = seeded(store)
    session = store.exchange_invitation(_invite(store, ha).invitation_token)
    clock.t += timedelta(days=31)
    assert store.resolve_session(session) is None


def test_database_never_stores_raw_tokens(store, tmp_path):
    ha, _, _, _ = seeded(store)
    token = _invite(store, ha).invitation_token
    session = store.exchange_invitation(token)
    owner_session = store.create_owner_session(auth.LOCAL_OWNER_ID)
    store_bytes = b"".join(p.read_bytes() for p in tmp_path.glob("recovery.db*"))
    for raw in (token, session, owner_session):
        assert raw.encode() not in store_bytes


def test_owner_session_resolves_to_owner(store):
    actor = store.resolve_session(store.create_owner_session(auth.LOCAL_OWNER_ID))
    assert actor == auth.Actor(role="owner", actor_id=auth.LOCAL_OWNER_ID)


def test_owner_login_disabled_without_env(monkeypatch):
    monkeypatch.delenv(auth.OWNER_SECRET_ENV, raising=False)
    with pytest.raises(PlatformError) as e:
        auth.check_owner_secret("anything")
    assert e.value.code == "owner_login_disabled"
    monkeypatch.setenv(auth.OWNER_SECRET_ENV, "")
    with pytest.raises(PlatformError):
        auth.check_owner_secret("")


def test_owner_secret_compare(monkeypatch):
    monkeypatch.setenv(auth.OWNER_SECRET_ENV, "correct horse")
    assert auth.check_owner_secret("correct horse")
    assert not auth.check_owner_secret("wrong")
