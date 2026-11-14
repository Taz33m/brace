/**
 * One idempotency key per intended submission.
 *
 * The key is reused for every retry of the same payload (timeouts, lost responses) so the server
 * returns the original receipt instead of creating a duplicate. If the person changes what they are
 * sending, that is a new intended submission and it gets a new key. After a success the key is
 * retired, so a genuinely new report never reuses it.
 */
export function newIdempotencyKey(): string {
  const c = typeof globalThis !== "undefined" ? (globalThis.crypto as Crypto | undefined) : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  if (c && typeof c.getRandomValues === "function") {
    const b = c.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Stable serialisation so equal payloads compare equal regardless of key order. */
export function fingerprint(value: unknown): string {
  return JSON.stringify(value, (_k, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v as object).sort().map((k) => [k, (v as Record<string, unknown>)[k]]))
      : v,
  );
}

export interface SubmissionKeeper {
  /** Key for this payload: the same key as the last attempt when the payload is unchanged. */
  keyFor(payload: unknown): string;
  /** Call after the server confirmed the submission. The next payload gets a fresh key. */
  succeeded(): void;
}

export function createSubmissionKeeper(make: () => string = newIdempotencyKey): SubmissionKeeper {
  let current: { key: string; print: string } | null = null;
  return {
    keyFor(payload) {
      const print = fingerprint(payload);
      if (!current || current.print !== print) current = { key: make(), print };
      return current.key;
    },
    succeeded() {
      current = null;
    },
  };
}
