import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { BEARING } from "../geo";
import type { Direction, Scan } from "../types";

declare global {
  interface Window { MP_SDK?: { connect: (iframe: HTMLIFrameElement, key: string, version: string) => Promise<any> } }
}

export interface TourHandle {
  /** Open a scan if needed, fly to a position in it and face a direction. */
  lookFrom: (scanId: string, sweepId: string | null, direction: Direction) => void;
}

interface Props {
  scans: Scan[];
  sdkKey: string;
  onMove: (scanId: string, sweepId: string) => void;
  onTurn: (bearing: number | null) => void;
}

const PITCH: Record<string, number> = { up: 70, down: -55 };

export const TourPane = forwardRef<TourHandle, Props>(function TourPane({ scans, sdkKey, onMove, onTurn }, ref) {
  const [scanId, setScanId] = useState<string | null>(scans[0]?.id ?? null);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const frame = useRef<HTMLIFrameElement>(null);
  const sdk = useRef<any>(null);
  const yaw = useRef(0);
  const ids = useRef<Set<string>>(new Set());
  const pending = useRef<{ sweepId: string | null; direction: Direction } | null>(null);
  const cb = useRef({ onMove, onTurn });
  cb.current = { onMove, onTurn };
  const scan = scans.find((s) => s.id === scanId) ?? null;

  const move = (sweepId: string | null, direction: Direction) => {
    const mp = sdk.current;
    if (!mp || !scan) return;
    const offset = scan.sdk_yaw_offset;
    const rotation = direction in PITCH ? { x: PITCH[direction], y: yaw.current }
      : { x: 0, y: offset != null ? offset - BEARING[direction as keyof typeof BEARING] : yaw.current };
    const target = sweepId && ids.current.has(sweepId) ? sweepId : null;
    if (target) mp.Sweep.moveTo(target, { rotation, transition: mp.Sweep.Transition.FLY, transitionTime: 1300 }).catch(() => {});
    else mp.Camera.setRotation(rotation, { speed: 60 }).catch(() => {});
  };

  useEffect(() => {
    const el = frame.current;
    if (!el || !scan) return;
    let cancelled = false;
    let subs: { cancel: () => void }[] = [];
    let last = 0;
    sdk.current = null;
    ids.current = new Set();
    setState("loading");
    const connect = async () => {
      if (!window.MP_SDK) { setState("failed"); return; }
      try {
        const mp = await window.MP_SDK.connect(el, sdkKey, "");
        if (cancelled) return;
        sdk.current = mp;
        subs.push(mp.Sweep.data.subscribe({
          onCollectionUpdated(all: Record<string, { enabled?: boolean }>) {
            ids.current = new Set(Object.keys(all).filter((k) => all[k].enabled !== false));
            if (pending.current && ids.current.size) { const p = pending.current; pending.current = null; setTimeout(() => move(p.sweepId, p.direction), 600); }
          },
        }));
        subs.push(mp.Sweep.current.subscribe((s: { id?: string; sid?: string }) => { const id = s.id || s.sid; if (id) cb.current.onMove(scan.id, id); }));
        subs.push(mp.Camera.pose.subscribe((p: { rotation: { y: number } }) => {
          yaw.current = p.rotation.y;
          const now = performance.now();
          if (now - last < 90) return;
          last = now;
          cb.current.onTurn(scan.sdk_yaw_offset != null ? (((scan.sdk_yaw_offset - p.rotation.y) % 360) + 360) % 360 : null);
        }));
        setState("ready");
      } catch {
        if (!cancelled) setState("failed");
      }
    };
    el.addEventListener("load", connect);
    return () => { cancelled = true; el.removeEventListener("load", connect); subs.forEach((s) => s.cancel()); subs = []; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanId, sdkKey]);

  useImperativeHandle(ref, () => ({
    lookFrom(id, sweepId, direction) {
      if (id !== scanId) { pending.current = { sweepId, direction }; setScanId(id); }
      else if (sdk.current && ids.current.size) move(sweepId, direction);
      else pending.current = { sweepId, direction };
    },
  }));

  return (
    <section className="pane tour-pane" aria-label="Inside: scanned spaces">
      <header className="pane-head">
        <h2>Inside</h2>
        {scans.length > 0 && (
          <div className="pane-tools">
            <select value={scanId ?? ""} onChange={(e) => setScanId(e.target.value)} aria-label="Scanned space">
              {scans.map((s) => <option key={s.id} value={s.id}>{s.name}{s.level ? ` (floor ${s.level})` : ""}</option>)}
            </select>
          </div>
        )}
      </header>
      <div className="pane-body">
        {scan
          ? <iframe key={scan.id} ref={frame} title={`3D scan: ${scan.name}`} allow="xr-spatial-tracking; fullscreen"
                    src={`https://my.matterport.com/show?m=${scan.id}&play=1&qs=1&brand=0&title=0&help=0&search=0&applicationKey=${sdkKey}`} />
          : <p className="empty-pane">No space in this building has been scanned. The plan rests on the aerial imagery and the record.</p>}
      </div>
      <footer className="pane-foot">
        {!scan ? "" : state === "loading" ? "Loading the scan…" : state === "failed" ? "The scan could not connect. Reload the page."
          : `${scan.kind[0].toUpperCase()}${scan.kind.slice(1)}${scan.structure ? ` in ${scan.structure}` : ""}${scan.area_sqft ? `, about ${scan.area_sqft.toLocaleString()} sq ft` : ""}. Scans cover single spaces, not the whole building.`}
      </footer>
    </section>
  );
});
