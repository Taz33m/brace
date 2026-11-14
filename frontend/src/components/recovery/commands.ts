// Command runner for owner actions. It tracks pending/error per key and never touches case data:
// the server snapshot (refreshed by the parent after on_command resolves) is the only truth.
//
// The bookkeeping lives in a React-free store (createCommandStore) so it can be unit tested; useCommandRunner
// only wires it to React. The store is scoped, normally to the open case_id: when the scope changes, every
// pending flag, error and stored body is dropped, and a promise that settles after the change is ignored, so
// a failure (or its Retry body) from one case can never surface or be re-sent in another.
import { useCallback, useEffect, useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { OwnerCommand } from "../../recovery/contracts";

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
export type CommandBody = DistributiveOmit<OwnerCommand, "expected_revision">;

export type CommandStatus = { pending: boolean; error: string | null };

export type CommandRunner = {
  /**
   * Sends `body` with the latest case_revision. Resolves true on success; false on failure, if `key` is
   * already pending, or if the scope (case) changed before the server answered.
   */
  run(key: string, body: CommandBody): Promise<boolean>;
  /** Re-sends the last body for `key` with the latest case_revision (the body itself, incl. any task revision, is kept). */
  retry(key: string): Promise<boolean>;
  /** Clears a failed command's error. Ignored while pending. */
  dismiss(key: string): void;
  status(key: string): CommandStatus;
  anyPending: boolean;
};

const IDLE: CommandStatus = { pending: false, error: null };
export const COMMAND_FALLBACK_ERROR = "The server did not confirm this change.";

/** Pull a readable message out of whatever on_command rejected with. */
export function commandErrorMessage(e: unknown): string {
  if (e instanceof Error && e.message.trim() !== "") return e.message;
  if (typeof e === "object" && e !== null && "error" in e) {
    const inner = (e as { error: unknown }).error;
    if (typeof inner === "object" && inner !== null && "message" in inner) {
      const msg = (inner as { message: unknown }).message;
      if (typeof msg === "string" && msg.trim() !== "") return msg;
    }
  }
  if (typeof e === "string" && e.trim() !== "") return e;
  return COMMAND_FALLBACK_ERROR;
}

/* ------------------------------------------------------------ pure core */

export type CommandStoreState = {
  /** The scope these statuses belong to (normally the open case_id). */
  readonly scope: string | null;
  /** Only keys that are pending or failed. A key that succeeded or was dismissed is absent, i.e. idle. */
  readonly statuses: Readonly<Record<string, CommandStatus>>;
  readonly anyPending: boolean;
};

export type CommandStore = {
  /** An immutable snapshot; a new object after every change (useSyncExternalStore-compatible). */
  getState(): CommandStoreState;
  subscribe(listener: () => void): () => void;
  /**
   * Moves the store to another scope. A change drops every pending flag, error and stored body, and makes
   * promises still in flight from the old scope settle silently (they resolve false and write nothing).
   */
  setScope(scope: string | null): void;
  /** The case_revision injected into the next run or retry. */
  setRevision(case_revision: number): void;
  setHandler(on_command: (command: OwnerCommand) => Promise<void>): void;
  run(key: string, body: CommandBody): Promise<boolean>;
  retry(key: string): Promise<boolean>;
  dismiss(key: string): void;
  status(key: string): CommandStatus;
};

export type CommandStoreInit = {
  on_command: (command: OwnerCommand) => Promise<void>;
  case_revision: number;
  scope?: string | null;
};

/** React-free command bookkeeping. useCommandRunner is a thin hook over this. */
export function createCommandStore(init: CommandStoreInit): CommandStore {
  let handler = init.on_command;
  let revision = init.case_revision;
  let state: CommandStoreState = { scope: init.scope ?? null, statuses: {}, anyPending: false };
  // Bumped on every scope change; a command remembers the epoch it started in.
  let epoch = 0;
  // Synchronous bookkeeping so a double click in one frame cannot send twice.
  const pending = new Set<string>();
  const bodies = new Map<string, CommandBody>();
  const listeners = new Set<() => void>();

  const commit = (statuses: Record<string, CommandStatus>) => {
    state = { scope: state.scope, statuses, anyPending: Object.values(statuses).some((s) => s.pending) };
    for (const listener of [...listeners]) listener();
  };
  const without = (key: string): Record<string, CommandStatus> => {
    const next = { ...state.statuses };
    delete next[key];
    return next;
  };

  async function execute(key: string, body: CommandBody): Promise<boolean> {
    if (pending.has(key)) return false;
    const startedIn = epoch;
    pending.add(key);
    bodies.set(key, body);
    commit({ ...state.statuses, [key]: { pending: true, error: null } });

    let error: string | null = null;
    try {
      const command = { ...body, expected_revision: revision } as OwnerCommand;
      await handler(command);
    } catch (e) {
      error = commandErrorMessage(e);
    }

    // The scope changed while this was in flight: its outcome belongs to the previous case. Write nothing,
    // and in particular do not clear a pending flag the new scope may have set for the same key.
    if (startedIn !== epoch) return false;
    pending.delete(key);
    if (error == null) {
      bodies.delete(key);
      commit(without(key));
      return true;
    }
    commit({ ...state.statuses, [key]: { pending: false, error } });
    return false;
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    setScope(scope) {
      if (scope === state.scope) return;
      epoch += 1;
      pending.clear();
      bodies.clear();
      state = { scope, statuses: {}, anyPending: false };
      for (const listener of [...listeners]) listener();
    },
    setRevision(case_revision) {
      revision = case_revision;
    },
    setHandler(on_command) {
      handler = on_command;
    },
    run: (key, body) => execute(key, body),
    retry(key) {
      const body = bodies.get(key);
      if (!body) return Promise.resolve(false);
      return execute(key, body);
    },
    dismiss(key) {
      if (pending.has(key)) return;
      bodies.delete(key);
      if (key in state.statuses) commit(without(key));
    },
    status: (key) => state.statuses[key] ?? IDLE,
  };
}

/* ------------------------------------------------------------ React hook */

// Layout effects warn during server rendering (tests render statically); effects never run there anyway.
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

const NO_STATUSES: CommandStoreState = { scope: null, statuses: {}, anyPending: false };

/**
 * The owner command runner. `scope` is optional for backward compatibility; RecoveryWorkspace passes the open
 * case_id so that a case switch drops every pending flag, error and Retry body of the previous case.
 */
export function useCommandRunner(
  on_command: (command: OwnerCommand) => Promise<void>,
  case_revision: number,
  scope: string | null = null,
): CommandRunner {
  const [store] = useState(() => createCommandStore({ on_command, case_revision, scope }));

  // Committed values only: a command carries the revision of the snapshot the owner is looking at.
  useIsomorphicLayoutEffect(() => {
    store.setHandler(on_command);
    store.setRevision(case_revision);
    store.setScope(scope);
  }, [store, on_command, case_revision, scope]);

  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  // In the render where the scope has just changed, the store still holds the previous scope until the
  // layout effect above resets it. Never show that state to the new scope, not even for one render.
  const visible = state.scope === scope ? state : NO_STATUSES;
  const status = useCallback((key: string) => visible.statuses[key] ?? IDLE, [visible]);
  const anyPending = visible.anyPending;

  return useMemo(
    () => ({ run: store.run, retry: store.retry, dismiss: store.dismiss, status, anyPending }),
    [store, status, anyPending],
  );
}
