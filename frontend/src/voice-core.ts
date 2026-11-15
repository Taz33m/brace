/**
 * The small decisions of the live voice: when to reopen a dropped line, what to tell the model when it is back,
 * and how a response or an error from the service is read.
 *
 * Nothing here touches the browser or the network, so all of it can be tested with made-up values.
 */

/** How many times a dropped line is reopened before giving up. */
export const RECONNECTS = 2;
/** How long to wait before each attempt, first then second. */
export const BACKOFF_MS = [600, 2000];
/** A line that held this long before dropping gets its attempts back: it is a new fault, not the same one again. */
export const STEADY_MS = 20_000;
/** "disconnected" often mends itself within a second or two; after this long it is treated as a drop. */
export const DISCONNECTED_MS = 4000;
/** A tool that has not answered by now is reported to the model as failed, so the conversation carries on. */
export const TOOL_MS = 20_000;
/** A response that was asked for and not confirmed by now is given up on, so nothing waits on it for ever. */
export const UNCONFIRMED_MS = 10_000;
/** With no network at all, an attempt waits this long at most for it to come back. */
export const OFFLINE_WAIT_MS = 30_000;
/** How many finished lines the model is reminded of after a reconnect. */
export const RECALL = 6;
const RECALL_CHARS = 240;

/** A finished line: Brace's or the person's. */
export interface Said { who: "agent" | "you"; text: string }

/**
 * Which attempt comes next, or null when it is time to give up.
 * `used` is how many have been made since the line last held steady; `heldMs` is how long it had been up when it dropped.
 */
export function nextAttempt(used: number, heldMs: number): number | null {
  const spent = heldMs >= STEADY_MS ? 0 : Math.max(0, used);
  return spent < RECONNECTS ? spent + 1 : null;
}

/** The wait before attempt 1, 2 and so on. */
export function backoffMs(attempt: number): number {
  return BACKOFF_MS[Math.min(Math.max(attempt, 1), BACKOFF_MS.length) - 1];
}

/** Add a finished line to what will be recalled, keeping only the newest few. Empty lines are not kept. */
export function recall(said: Said[], who: Said["who"], text: string): void {
  const words = text.trim();
  if (!words) return;
  said.push({ who, text: words });
  while (said.length > RECALL) said.shift();
}

/**
 * What the model is told once a dropped line is back. The new session remembers nothing, so it is given the
 * last few lines, told not to greet again, and told whether the person is still waiting for an answer.
 */
export function rejoin(said: readonly Said[], unanswered: boolean): string {
  const lines = said.slice(-RECALL).map((s) => {
    const words = s.text.length > RECALL_CHARS ? `${s.text.slice(0, RECALL_CHARS)}…` : s.text;
    return `${s.who === "agent" ? "You said" : "They said"}: ${words}`;
  });
  return [
    "[line] The connection dropped for a moment and is back. This is the same conversation with the same person, carried on.",
    "Do not greet them again, do not introduce yourself, and do not mention the interruption unless they ask.",
    lines.length ? `The last things said, oldest first:\n${lines.join("\n")}` : "Nothing had been said yet.",
    unanswered ? "They are still waiting for an answer to the last thing they said. Answer it now." : "Wait for them to speak.",
  ].join("\n");
}

const record = (value: unknown): Record<string, unknown> => (value && typeof value === "object" ? (value as Record<string, unknown>) : {});

/**
 * How a response ended, from the service's `response.done` event: "completed", "cancelled" (the person spoke over
 * it), "failed" or "incomplete". An event with no status is taken as completed. `why` is the reason given, if any.
 */
export function ending(event: unknown): { status: string; why: string | null } {
  const response = record(record(event).response);
  const status = typeof response.status === "string" && response.status ? response.status : "completed";
  const details = record(response.status_details), error = record(details.error);
  const why = [error.code, error.message, details.reason].find((part) => typeof part === "string" && part) as string | undefined;
  return { status, why: why ?? null };
}

/** The service's `error` event in two words: its code (or type) and its message. */
export function fault(event: unknown): { code: string; message: string } {
  const error = record(record(event).error);
  const text = (value: unknown) => (typeof value === "string" ? value : "");
  return { code: text(error.code) || text(error.type) || "unknown", message: text(error.message) };
}

/** The error that means our request for a response lost to one the service had already started. */
export const ALREADY_RESPONDING = "conversation_already_has_active_response";
