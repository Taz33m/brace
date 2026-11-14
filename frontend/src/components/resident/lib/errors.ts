/**
 * Normalises whatever the injected ResidentApi throws into one shape the screens can render.
 *
 * Expected from the lead's adapter (see README "API mismatches"): an Error-like object carrying
 * `status` (HTTP status) and/or `body` / `error` matching the contract's ApiErrorBody envelope.
 * A fetch network failure (TypeError, AbortError) is treated as retryable "network".
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
  const status = statusOf(e);
  const env = envelope(e);
  const isNetwork =
    status == null && !env &&
    (e instanceof TypeError || (e instanceof DOMException && (e.name === "AbortError" || e.name === "TimeoutError")) ||
      (typeof navigator !== "undefined" && navigator.onLine === false));
  const kind: ResidentError["kind"] = isNetwork ? "network" : kindFromStatus(status);
  const fb = FALLBACK[kind];
  return {
    kind,
    // Server messages are written for people (contract error envelope); prefer them when present.
    message: env?.message || fb.message,
    retryable: env ? env.retryable : fb.retryable,
    status,
    code: env?.code ?? null,
  };
}
