# Platform Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the PR #3 deferred review findings that matter for the integrated demo.

**Architecture:** Changes stay inside `CaseStore` and `build_router`. No schema migration or contract field changes.

**Tech Stack:** unchanged (FastAPI, sqlite3, Pillow).

**Spec:** `backend/recovery/platform/docs/2026-11-14-platform-hardening-design.md`, plus `docs/recovery-handoffs/04-RECOVERY-PLATFORM.md` (lead integration checkpoint).

## Global Constraints

- Write only `backend/recovery/platform/**`, `tests/test_recovery_platform*.py`, `tests/test_recovery_permissions*.py`.
- Every existing test on `main` (416 passing) must still pass, including the lead's integration tests.
- No new dependencies and no contract payload changes. The new status 429 is flagged to the lead.

## Review Focus

1. The lead's owner controller retries a lost `publish_notice` with the same key after the first attempt committed. It must get the original result, not a 409. Tested in Task 1.
2. Two identical owner commands arrive concurrently: one notice, and both responses succeed. Tested in Task 1.
3. A wrong owner secret repeated in a loop gets 429, while a correct secret after the window works. Tested in Task 3.
4. An upload without a key is rejected before the body is read. Tested in Task 2.
5. The startup sweep must never delete a committed photo. Tested in Task 2.

---

### Task 1: Atomic owner-command idempotency
**Files:** `store.py`. Test `tests/test_recovery_platform_hardening.py`.
- [ ] Tests: `test_command_replay_after_commit_returns_original_result` (simulate a crash by recording nothing extra: the first call commits, then the same key is replayed and returns the same result); `test_concurrent_identical_commands_apply_once`; `test_replayed_create_invitation_still_409`; `test_same_key_different_command_conflicts`.
- [ ] Implement: `_Idem` record; `_owner_edit(..., idem)` replays before the revision check; handlers record before commit.

### Task 2: Upload ordering and orphan sweep
- [ ] Tests: `test_upload_without_key_rejected_before_body_read`; `test_startup_sweep_removes_old_orphans_only`.
- [ ] Implement: key/session checks first in the route; `sweep_orphan_media(min_age=timedelta(minutes=10))` called on init.

### Task 3: Housekeeping, throttle, proposal evidence, forwarded proto
- [ ] Tests: `test_startup_purges_expired_sessions_and_old_idempotency`; `test_owner_secret_throttled_after_ten_failures`; `test_proposal_unknown_evidence_ids_dropped`; `test_forwarded_proto_trusted_only_from_loopback`.
- [ ] Implement, run the full suite, commit, push, final review, PR.
