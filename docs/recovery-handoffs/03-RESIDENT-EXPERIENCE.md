# Person 3 — Resident phone experience

## Assignment

Build a small, real phone experience: residents report a problem, request support, and follow verified updates about their own home. The lead owns valuation and integration. Platform owns authorization, upload storage, and server state. You own the resident interaction and its failure handling.

Read the team overview, shared contract, and supplied TypeScript types. Person 2 installs the canonical frontend types as their first change. You can begin independent UI work and a clearly labeled preview immediately.

## Exclusive write scope

`/Users/tazeemmahashin/brace/frontend/src/components/resident/**`, including scoped styles, preview fixtures, and meaningful component tests. Do not edit App.tsx, global styles, configs, manifests, shared types, API implementations, backend code, or Standard Response.

## Reference material

Under `/Users/tazeemmahashin/Downloads/Standard-Response-CalHacks/`: `components/ui/phone-screen.tsx`; `components/phone/thread-model.ts`; `components/ready/profile.tsx`; `components/ready/sign-up.tsx`; `components/driver/offer-cards.tsx`; and `public/devpost/gallery/10-resident-and-driver.jpg`.

Borrow its clear choices, readable status, location diagrams, and changed-assignment treatment. Remove hard-coded evacuation/911/vehicle language. Do not inherit any implication of affiliation with emergency services.

## Exported interface

Export `ResidentExperience` from `frontend/src/components/resident/ResidentExperience.tsx`:

```ts
type ResidentExperienceProps = {
  api: ResidentApi;
  on_session_expired: () => void;
};
```

ResidentApi is defined in `shared-contract.ts`; the lead supplies the actual network adapter. The lead performs invitation exchange/session bootstrap before mounting. Your component fetches home, subscribes, handles report/upload/support interactions, and cleans up subscriptions.

## Screens and sequence

1. **Home:** property name, confirmed unit association or “Unit not confirmed,” visible exercise label when applicable, current published building update, and three large choices: Report a problem / Request support / My updates. Show when the information was last updated.
2. **Report:** choose category, choose an eligible room or describe the location, type what happened, optionally attach a photo, choose when it was observed, review and submit. Make confirmation of property/unit obvious.
3. **Receipt:** stable report ID, received time, “Reported — awaiting review,” original text/location/photo, and next step. Do not promise an inspection time unless supplied in the authorized response.
4. **Support:** housing, access assistance, communication assistance, or other. Collect only what is needed for the request. A submitted request is not a reservation or booked service.
5. **Updates:** own reports and support requests, published notices, and relevant task status. Do not show owner finances, internal agent analysis, other households, or unrestricted building images.

## Spatial and evidence behavior

Only enable exact room selection for `verified_unit` locations returned by the API. A `representative_layout` may be displayed with that label but must not imply it is the resident's unit; use descriptive location input instead. Never expose the full Matterport SDK on the phone or browse arbitrary model IDs.

Use only the media URLs and selectable spaces returned in ResidentHome. Uploads enter as reports, not verified damage. The resident's observation time and server received time remain distinct. If the person is unsure when something happened, accept unknown instead of inventing a timestamp.

## Reliability

- Generate one idempotency key per intended submission. Retry the same request with the same key after timeout; a genuinely new report gets a new key.
- Upload files first, then attach the returned upload IDs. Failed upload must not produce a misleading report receipt.
- Disable duplicate submit while pending, but keep entered text intact on network failure. Do not silently send anything later in the background.
- Use browser-supported file input/camera capture; keep manual file selection available. Platform validates content and size.
- Show Offline / Reconnecting / Session expired states. Retain an in-memory draft during transient errors; avoid persistent storage of sensitive report/photos by default.
- On an event, refresh the authorized resident snapshot; the event does not carry raw owner information. Reconnect using the returned event cursor. Ignore already processed event IDs.
- Actual authorization is server-side. Never treat a hidden UI element as a permission boundary or copy tokens into query strings or logs.

## Fixtures and testing

Provide an explicitly opt-in `ResidentPreview.tsx` with an injected fake ResidentApi, synthetic people, and a visible fixture banner. It must exercise success, lost response/retry, pending review, task status change, upload failure, and expired session. Never activate fake data when the real API fails.

Test at approximately 390px width, large text, keyboard where applicable, and touch controls. Test one actual phone with the integrated HTTPS server once the lead provides it. Report certificate/network restrictions honestly. Do not start a second heavyweight app or leave a browser/server running after a check.

## Acceptance

- A resident can submit a report and see a stable receipt with the same idempotency key on retry.
- Report location never falsely binds a model unit to a real dwelling.
- The view shows only authorized household data and published notices.
- New task status appears after an event/reconnect without duplication.
- “Accepted,” “completed,” and “occupancy cleared” are never conflated.
- Loading/error/no-notice/no-room/no-photo states are usable.
- Existing app configuration and all other owners' files remain untouched.

Return changed files, exported interface, screenshots, checks/results, any API mismatch, and device-verification status. SMS, voice, evacuation routing, medical advice, and housing booking are outside your assignment.
