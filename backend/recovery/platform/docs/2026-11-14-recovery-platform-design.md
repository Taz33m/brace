# Recovery platform (Person 4): short design

Source of truth: `docs/recovery-handoffs/04-RECOVERY-PLATFORM.md`, `05-SHARED-CONTRACT.md`,
`shared-contract.ts`, and `docs/recovery-core.md` (worker handshake). This note records only the
calls made where those documents are silent.

## Intent

Durable shared state under the recovery slice: one phone report reaches the owner, the
owner reviews and assigns work, and both sides see the same status. No valuation, damage
reasoning, model loop, or UI here. No invented data; unknown stays `None`.

## Approaches considered

1. **Hand-written SQLite store + typed command handlers (chosen).** Stdlib `sqlite3`, WAL,
   one connection per call, `BEGIN IMMEDIATE` for every mutation so the revision check,
   the write, and the event append are one transaction. No new dependencies.
2. SQLAlchemy/SQLModel: would need a dependency, which we are not allowed to add.
3. JSON-document-per-case storage: simpler reads but no unique constraints or row-level
   idempotency, and concurrent writers would need a lock file. Rejected.

## Shape

- `models.py`: Pydantic v2 models that mirror `shared-contract.ts` field for field.
- `schema.py`: versioned migrations (`PRAGMA user_version`), all tables from day one.
- `store.py`: `CaseStore(db_path, media_dir)`. Rows hold structured columns for things
  we query or constrain (ids, case, household, status, revision) plus a JSON column for
  the contract payload. Mutations go through one `_tx()` helper that opens
  `BEGIN IMMEDIATE`, checks `expected_revision`, writes, bumps `case_revision` (and
  `analysis_revision` when inputs change), and appends the event.
- `auth.py`: owner secret bootstrap (`BRACE_OWNER_SECRET`, disabled when unset, compared
  with `hmac.compare_digest`), invitation tokens (`secrets.token_urlsafe(32)`, SHA-256
  stored), session tokens (also hashed), FastAPI dependencies `require_owner`,
  `require_resident`.
- `uploads.py`: stdlib multipart parsing (`python-multipart` is not installed), Pillow
  decode check, EXIF-stripped display copy, server filenames.
- `router.py`: `build_router(store, assessment_launcher)`.

## Calls made where the contract is silent (flag to lead)

- Each resident report also creates an `Observation` (basis `reported`); the report's
  `status` mirrors that observation. Photos become `resident_photo` Evidence rows.
- One env secret means one owner actor (`owner:local`). Cases record `owner_id`; owner
  routes filter by it.
- `create_case` and `add_household` are store-only (lead bootstrap), no HTTP route.
- Tasks and draft notices enter only through `complete_assessment` proposals (lead) or
  store calls; they are activated only when the result is current.
- `publish_notice` publishes immediately from the command fields (the contract has no
  draft id on the command). Agent draft notices stay owner-only until the lead/UI
  publishes text through that command.
- Resident `public_status_detail` text is fixed per status, written server-side.
