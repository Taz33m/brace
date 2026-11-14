/**
 * Normalises whatever the injected ResidentApi throws into one shape the screens can render.
 *
 * Accepted shapes, in order:
 * 1. The lead's `RecoveryApiError` (frontend/src/recovery/client.ts): flat `status`, `code`,
 *    `retryable`, `message`. `status: 0` / `code: "network_error"` is a network failure;
 *    `code: "session_expired"` (401 or 403 without a body) ends the session.
 * 2. An object carrying the contract's ApiErrorBody envelope under `error` or `body.error`.
 * 3. A raw fetch failure (TypeError, AbortError, offline) — retryable "network".
 */
import type { ApiErrorBody } from "../contract";

export interface ResidentError {
  kind: "network" | "expired" | "forbidden" | "not_found" | "conflict" | "too_large" | "invalid" | "unavailable" | "unknown";
  message: string;
  retryable: boolean;
  status: number | null;
  code: string | null;
}

function envelope(e: unknown): ApiErrorBody["error"] | null {
  if (!e || typeof e !== "object") return null;
  const o = e as Record<string, unknown>;
  // Flat RecoveryApiError: code/retryable/message live on the error itself.
  if (typeof o.code === "string" && typeof o.retryable === "boolean" && typeof o.message === "string") {
    return { code: o.code, message: o.message, retryable: o.retryable };
  }
  const direct = o.error;
  if (direct && typeof direct === "object" && "code" in direct) return direct as ApiErrorBody["error"];
  const body = o.body;
  if (body && typeof body === "object" && "error" in body) {
    const inner = (body as Record<string, unknown>).error;
    if (inner && typeof inner === "object" && "code" in inner) return inner as ApiErrorBody["error"];
  }
  return null;
}

function statusOf(e: unknown): number | null {
  if (!e || typeof e !== "object") return null;
  const s = (e as Record<string, unknown>).status;
  return typeof s === "number" ? s : null;
}

const FALLBACK: Record<ResidentError["kind"], { message: string; retryable: boolean }> = {
  network: { message: "No connection. Your answers are still here. Try again when you have signal.", retryable: true },
  expired: { message: "Your access link has expired. Ask the property team for a new one.", retryable: false },
  forbidden: { message: "This link doesn't give access to that. Ask the property team for help.", retryable: false },
  not_found: { message: "That item isn't available any more.", retryable: false },
  conflict: { message: "Something changed while you were sending. Try again.", retryable: true },
  too_large: { message: "That photo is too large to send. Try a different photo.", retryable: false },
  invalid: { message: "Something in the form needs a fix before it can be sent.", retryable: false },
  unavailable: { message: "The service is busy right now. Try again in a moment.", retryable: true },
  unknown: { message: "Something went wrong while sending. Try again.", retryable: true },
};

function kindFromStatus(status: number | null): ResidentError["kind"] {
  switch (status) {
    case 401: return "expired";
    case 403: return "forbidden";
    case 404: return "not_found";
    case 409: return "conflict";
    case 413: return "too_large";
    case 422: return "invalid";
    case 502: case 503: case 504: return "unavailable";
    default: return status == null ? "unknown" : status >= 500 ? "unavailable" : "unknown";
  }
}

export function toResidentError(e: unknown): ResidentError {
  const rawStatus = statusOf(e);
  const env = envelope(e);
  // status 0 is the client's "no HTTP response" marker; it is a network failure only when it carries
  // no other meaning (client.ts also uses status 0 for local validation like invalid_idempotency_key).
  const isNetwork =
    env?.code === "network_error" || (rawStatus === 0 && !env) ||
    (rawStatus == null && !env &&
      (e instanceof TypeError ||
        (typeof DOMException !== "undefined" && e instanceof DOMException && (e.name === "AbortError" || e.name === "TimeoutError")) ||
        (typeof navigator !== "undefined" && navigator.onLine === false)));
  const status = rawStatus === 0 ? null : rawStatus;
  const kind: ResidentError["kind"] =
    isNetwork ? "network"
      : env?.code === "session_expired" ? "expired"
        : rawStatus === 0 && env ? (env.retryable ? "unknown" : "invalid")
          : kindFromStatus(status);
  const fb = FALLBACK[kind];
  return {
    kind,
    // Network and expiry use our resident wording (it tells them their answers are kept / what to do);
    // otherwise server messages are written for people, so prefer them.
    message: kind === "network" || kind === "expired" ? fb.message : env?.message || fb.message,
    retryable: kind === "network" ? true : kind === "expired" ? false : env ? env.retryable : fb.retryable,
    status,
    code: env?.code ?? null,
  };
}
