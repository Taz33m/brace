import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const { toResidentError } = await loadTs("lib/errors.ts");

// Mirrors RecoveryApiError in frontend/src/recovery/client.ts (flat status/code/retryable/message).
class RecoveryApiError extends Error {
  constructor(status, error) {
    super(error.message);
    this.name = "RecoveryApiError";
    this.status = status;
    this.code = error.code;
    this.retryable = error.retryable;
  }
}
const flat = (status, code, message, retryable) => new RecoveryApiError(status, { code, message, retryable });

test("lead's network error (status 0, network_error) is a retryable network failure", () => {
  const r = toResidentError(flat(0, "network_error", "Could not reach the recovery service. Try again.", true));
  assert.equal(r.kind, "network");
  assert.equal(r.retryable, true);
  assert.equal(r.status, null);
  assert.match(r.message, /answers are still here/);
});

test("session_expired ends the session with resident wording", () => {
  for (const status of [401, 403]) {
    const r = toResidentError(flat(status, "session_expired", "Your session has expired or does not have access.", false));
    assert.equal(r.kind, "expired", String(status));
    assert.equal(r.retryable, false);
    assert.match(r.message, /expired/);
    assert.equal(r.code, "session_expired");
  }
});

test("envelope under body.error (fixture HttpError shape)", () => {
  const e = Object.assign(new Error("x"), { status: 409, body: { error: { code: "stale", message: "Someone else changed this.", retryable: true } } });
  const r = toResidentError(e);
  assert.equal(r.kind, "conflict");
  assert.equal(r.message, "Someone else changed this.");
  assert.equal(r.retryable, true);
  assert.equal(r.code, "stale");
  assert.equal(r.status, 409);
});

test("envelope directly under error", () => {
  const r = toResidentError({ status: 422, error: { code: "text_required", message: "Say what happened before sending.", retryable: false } });
  assert.equal(r.kind, "invalid");
  assert.equal(r.message, "Say what happened before sending.");
});

test("status mapping", () => {
  const cases = { 401: "expired", 403: "forbidden", 404: "not_found", 409: "conflict", 413: "too_large", 422: "invalid", 503: "unavailable", 500: "unavailable", 418: "unknown" };
  for (const [status, kind] of Object.entries(cases)) {
    const r = toResidentError({ status: Number(status) });
    assert.equal(r.kind, kind, status);
    assert.ok(r.message, status);
  }
  assert.equal(toResidentError({ status: 503 }).retryable, true);
  assert.equal(toResidentError({ status: 422 }).retryable, false);
});

test("server message preferred, except for network and expired", () => {
  assert.equal(toResidentError(flat(413, "too_large", "Photos must be under 20 MB.", false)).message, "Photos must be under 20 MB.");
  assert.equal(toResidentError(flat(503, "upload_unavailable", "Photo storage is busy.", true)).retryable, true);
  const expired = toResidentError(flat(401, "session_expired", "raw server text", false));
  assert.notEqual(expired.message, "raw server text");
  const net = toResidentError(flat(0, "network_error", "raw server text", true));
  assert.notEqual(net.message, "raw server text");
});

test("raw TypeError and AbortError are network failures", () => {
  assert.equal(toResidentError(new TypeError("Failed to fetch")).kind, "network");
  assert.equal(toResidentError(new DOMException("aborted", "AbortError")).kind, "network");
  const r = toResidentError(new TypeError("Failed to fetch"));
  assert.equal(r.retryable, true);
});

test("unknown junk never throws", () => {
  for (const v of [undefined, null, "boom", 42, {}, new Error("x")]) {
    const r = toResidentError(v);
    assert.ok(r.message);
  }
});

test("client-side validation errors with status 0 are not retryable network failures", () => {
  const r = toResidentError(flat(0, "invalid_idempotency_key", "Use a nonempty idempotency key for this submission.", false));
  assert.notEqual(r.kind, "network");
  assert.equal(r.retryable, false);
});
