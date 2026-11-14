// Shared helpers for component tests (static rendering only; no DOM, no effects).
import type { CommandBody, CommandRunner, CommandStatus } from "../commands";

export type FakeRunner = CommandRunner & { calls: { key: string; body: CommandBody }[] };

/** A CommandRunner whose statuses are fixed. Pass `{ "task:x:accepted": { pending: false, error: "Nope" } }` to simulate a failure. */
export function fakeRunner(statuses: Record<string, CommandStatus> = {}, anyPending = false): FakeRunner {
  const calls: { key: string; body: CommandBody }[] = [];
  return {
    calls,
    run: (key, body) => {
      calls.push({ key, body });
      return Promise.resolve(true);
    },
    retry: () => Promise.resolve(true),
    dismiss: () => undefined,
    status: (key) => statuses[key] ?? { pending: false, error: null },
    anyPending: anyPending || Object.values(statuses).some((s) => s.pending),
  };
}

export const noop = (): void => undefined;

/** Strip tags so text assertions don't depend on markup. Collapses whitespace. */
export function textOf(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}
