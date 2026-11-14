/**
 * Loads the authorized resident snapshot and keeps it current from the live event stream.
 *
 * - One subscription per mounted api, started from the first snapshot's event_cursor.
 * - Each event refreshes the snapshot (events carry IDs, not data). Refreshes are coalesced and
 *   an older response never replaces a newer one.
 * - 401 / session.revoked / subscription "expired" all end in the expired state, reported once.
 * - Browser offline is shown separately from server reconnects.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ResidentApi, ResidentHome } from "./contract";
import { createEventGate, isNewerSnapshot, type EventGate } from "./lib/events";
import { toResidentError, type ResidentError } from "./lib/errors";

export type Connection = "connecting" | "connected" | "reconnecting" | "offline" | "expired";

export interface ResidentSession {
  home: ResidentHome | null;
  load_state: "loading" | "ready" | "error";
  load_error: ResidentError | null;
  connection: Connection;
  fresh_ids: ReadonlySet<string>;
  refresh: () => Promise<void>;
  expire: () => void;
}

const FRESH_MS = 4000;
/** If the stream stays "reconnecting" this long, start a fresh subscription. */
const STUCK_MS = 30_000;

export function useResidentSession(api: ResidentApi, on_session_expired: () => void): ResidentSession {
  const [home, setHome] = useState<ResidentHome | null>(null);
  const [loadState, setLoadState] = useState<ResidentSession["load_state"]>("loading");
  const [loadError, setLoadError] = useState<ResidentError | null>(null);
  const [serverConn, setServerConn] = useState<Exclude<Connection, "offline">>("connecting");
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine !== false));
  const [freshIds, setFreshIds] = useState<ReadonlySet<string>>(() => new Set());
  /** Bumped to tear down and restart the live subscription. */
  const [streamEpoch, setStreamEpoch] = useState(0);

  const homeRef = useRef<ResidentHome | null>(null);
  const gateRef = useRef<EventGate | null>(null);
  const expiredRef = useRef(false);
  const inflight = useRef<Promise<void> | null>(null);
  const again = useRef(false);
  const onExpiredRef = useRef(on_session_expired);
  onExpiredRef.current = on_session_expired;

  const expire = useCallback(() => {
    if (expiredRef.current) return;
    expiredRef.current = true;
    setServerConn("expired");
    onExpiredRef.current();
  }, []);

  const apply = useCallback((next: ResidentHome) => {
    if (!isNewerSnapshot(homeRef.current, next)) return;
    homeRef.current = next;
    gateRef.current?.advance(next.event_cursor);
    setHome(next);
  }, []);

  const fetchOnce = useCallback(async () => {
    try {
      const next = await api.get_home();
      apply(next);
      setLoadState("ready");
      setLoadError(null);
    } catch (e) {
      const err = toResidentError(e);
      if (err.kind === "expired") {
        expire();
        return;
      }
      // Keep showing the last good snapshot; only an initial load failure blocks the screen.
      if (!homeRef.current) {
        setLoadState("error");
        setLoadError(err);
      }
    }
  }, [api, apply, expire]);

  /** Coalesced refresh: one request in flight; a refresh asked for meanwhile runs once after it. */
  const refresh = useCallback((): Promise<void> => {
    if (expiredRef.current) return Promise.resolve();
    if (inflight.current) {
      again.current = true;
      return inflight.current;
    }
    const run = (async () => {
      do {
        again.current = false;
        await fetchOnce();
      } while (again.current && !expiredRef.current);
    })().finally(() => {
      inflight.current = null;
    });
    inflight.current = run;
    return run;
  }, [fetchOnce]);

  // Initial load.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Live subscription, started once the first snapshot gives us a cursor.
  const ready = home !== null;
  useEffect(() => {
    if (!ready || expiredRef.current || !homeRef.current) return;
    const gate = createEventGate(homeRef.current.event_cursor);
    gateRef.current = gate;
    const timers: number[] = [];
    let stuck: number | undefined;
    let unsub: (() => void) | null = null;
    try {
      unsub = api.subscribe({
        after: gate.cursor(),
        on_event: (event) => {
          const action = gate.accept(event);
          if (action === "expire") {
            expire();
            return;
          }
          if (action !== "refresh") return;
          if (event.entity_id) {
            const id = event.entity_id;
            setFreshIds((s) => new Set(s).add(id));
            timers.push(window.setTimeout(() => setFreshIds((s) => {
              const n = new Set(s);
              n.delete(id);
              return n;
            }), FRESH_MS));
          }
          void refresh();
        },
        on_connection: (state) => {
          if (state === "expired") {
            expire();
            return;
          }
          setServerConn(state);
          window.clearTimeout(stuck);
          if (state === "reconnecting") stuck = window.setTimeout(() => setStreamEpoch((n) => n + 1), STUCK_MS);
          // After a reconnect the adapter resumes from its last event ID; refresh anyway so a
          // missed public projection change cannot leave the screen stale.
          if (state === "connected") void refresh();
        },
      });
    } catch (e) {
      if (toResidentError(e).kind === "expired") expire();
      else setServerConn("reconnecting");
    }
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      window.clearTimeout(stuck);
      unsub?.();
      if (gateRef.current === gate) gateRef.current = null;
    };
  }, [api, ready, expire, refresh, streamEpoch]);

  // Browser connectivity.
  useEffect(() => {
    const up = () => {
      setOnline(true);
      void refresh();
    };
    const down = () => setOnline(false);
    // Restored from the back/forward cache: the old stream was stopped on pagehide.
    const shown = (e: PageTransitionEvent) => {
      if (!e.persisted) return;
      setStreamEpoch((n) => n + 1);
      void refresh();
    };
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    window.addEventListener("pageshow", shown);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
      window.removeEventListener("pageshow", shown);
    };
  }, [refresh]);

  const connection: Connection = serverConn === "expired" ? "expired" : !online ? "offline" : serverConn;

  return { home, load_state: loadState, load_error: loadError, connection, fresh_ids: freshIds, refresh, expire };
}
