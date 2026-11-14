# Resident phone experience (P3)

The phone half of Brace recovery: a resident reports a problem (with photos), requests support,
and follows their own reports, repair tasks and the property's published notices, live.

Spec: `docs/recovery-handoffs/03-RESIDENT-EXPERIENCE.md`. Contract: `docs/recovery-handoffs/shared-contract.ts`.

## Interface

```ts
import { ResidentExperience } from "./components/resident/ResidentExperience";

<ResidentExperience api={residentApi} on_session_expired={() => { /* show re-invite path */ }} />
```

`api` is the contract's `ResidentApi`, supplied by the lead after the invitation/session bootstrap.
The component never reads owner or preparation endpoints and never touches tokens.

## Run the preview (no backend needed)

```bash
cd frontend && npm run dev
# open http://localhost:5174/src/components/resident/preview.html
# start in a scenario: ...preview.html?scenario=lost_response
```

The preview injects an in-memory fake API (`fixtures/`) behind a visible "UI fixture" banner.
Scenarios: `happy`, `lost_response`, `upload_failure`, `expired_on_submit`, `no_rooms`, `empty`,
`unit_unconfirmed`. Side controls simulate the owner: review a report, advance a task, publish a
notice, drop the connection (replays with a duplicate event), expire the session. The fake API is
never a fallback for the real one; it is only reachable through `preview.html`.

On a phone: the preview is served by Vite on `localhost`, so a phone needs the lead's HTTPS/LAN
server (port 5175) or the integrated mount.

## Files

| Path | Purpose |
|---|---|
| `ResidentExperience.tsx` | Exported component: navigation, drafts (in memory only), connection / expired states |
| `useResidentSession.ts` | Snapshot load, live subscription, coalesced refresh, newest-snapshot-wins |
| `screens/` | Home, Report flow, Receipt, Support, Updates; `types.ts` is the shell↔screen interface |
| `lib/status.ts` | All resident wording for report / support / task states |
| `lib/events.ts` | Event dedupe + cursor gate |
| `lib/idempotency.ts` | One key per intended submission, reused on retry |
| `lib/errors.ts` | Normalises adapter errors (status / ApiErrorBody / network) |
| `lib/photos.ts`, `lib/useDictation.ts` | Photo prep (resize, HEIC→JPEG) and optional speech-to-text |
| `contract.ts` | Type-only re-export of the lead's contract (swap path when `src/recovery/contracts.ts` lands) |
| `ResidentPreview.tsx`, `preview.html`, `preview-main.tsx`, `preview.css`, `fixtures/` | Opt-in preview only |

## Checks

```bash
cd frontend && npx tsc --noEmit
npx --yes tsx --test src/components/resident/__tests__/*.test.mjs   # logic tests, no new dependencies
```
