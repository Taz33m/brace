# Platform hardening (Person 4, second pass): short design

Context: PR #3 merged. The lead's integration checkpoint (`04-RECOVERY-PLATFORM.md`, top) asks
Person 4 to continue within scope; no new features. This pass closes the deferred findings
of the PR #3 final review that now matter because the lead's owner controller replays lost
command responses with the same Idempotency-Key and phones arrive through the Vite proxy.

## Changes

1. **Atomic owner-command idempotency.** Replay check and receipt are written inside the
   command's own write transaction (replay is checked before the revision check, since a
   successful first attempt has already advanced the revision). Two identical concurrent
   commands: one applies, the other replays. `start_assessment` keeps recording after
   launch, because its result depends on the launcher outcome and it is already
   deduplicated by the active run.
2. **Uploads:** session and key validated before the body is read; the session lookup runs
   off the event loop; media files without a committed row and older than 10 minutes
   are swept on startup.
3. **Housekeeping on startup:** delete expired or revoked sessions and idempotency records
   older than 7 days.
4. **Owner secret throttle:** 10 failed attempts within 5 minutes → 429
   `too_many_attempts` (retryable) until the window clears. Global, because all
   requests arrive from the loopback proxy. New status code; flag to lead.
5. **Agent task proposals:** evidence IDs not registered on the case are dropped
   (households already are).
6. **`X-Forwarded-Proto`** honored only from a loopback client.

## Approaches considered

- Idempotency: (a) per-handler in-transaction replay/record (chosen); (b) a unique
  "in-progress" placeholder row written before the handler: needs a second commit and
  cleanup on failure. (a) is smaller and covers the crash gap.
- Orphan files: (a) startup sweep of unreferenced, older files (chosen); (b) temp name
  + rename after commit: a crash after commit would leave a row pointing at a missing
  file, which is worse.

## Not changing

Lead-owned files (`support_router.py` uses CaseStore internals; it works and is tested),
contract payloads, task/observation state machines.
