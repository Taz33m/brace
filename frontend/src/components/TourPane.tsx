import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { BEARING } from "../geo";
import type { Direction, Scan } from "../types";
import { loadMatterportSdk } from "../matterport-sdk";

export interface TourHandle {
  /** Open a scan if needed, fly to a position in it and face a direction. With `tag`, pin a labelled marker in that view. */
  lookFrom: (scanId: string, sweepId: string | null, direction: Direction, tag?: string) => void;
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
  const [failure, setFailure] = useState("The scan could not connect.");
  const [retry, setRetry] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const sdk = useRef<any>(null);
  const yaw = useRef(0);
  const ids = useRef<Set<string>>(new Set());
  const where = useRef<Record<string, { x: number; y: number; z: number }>>({});
  const tagged = useRef<Set<string>>(new Set());
  const pending = useRef<{ sweepId: string | null; direction: Direction; tag?: string } | null>(null);
  const cb = useRef({ onMove, onTurn });
  cb.current = { onMove, onTurn };
  const scan = scans.find((s) => s.id === scanId) ?? null;

  const move = (sweepId: string | null, direction: Direction, tag?: string) => {
    const mp = sdk.current;
    if (!mp || !scan) return;
    const offset = scan.sdk_yaw_offset;
    const rotation = direction in PITCH ? { x: PITCH[direction], y: yaw.current }
      : { x: 0, y: offset != null ? offset - BEARING[direction as keyof typeof BEARING] : yaw.current };
    const target = sweepId && ids.current.has(sweepId) ? sweepId : null;
    if (target) mp.Sweep.moveTo(target, { rotation, transition: mp.Sweep.Transition.FLY, transitionTime: 1300 }).catch(() => {});
    else mp.Camera.setRotation(rotation, { speed: 60 }).catch(() => {});
    // Pin the action in the scene: a marker about two metres along the view from where the camera stands.
    const pos = target ? where.current[target] : null;
    const key = `${target}:${tag}`;
    if (tag && pos && mp.Tag?.add && !tagged.current.has(key)) {
      tagged.current.add(key);
      const yawRad = (rotation.y * Math.PI) / 180;
      const dy = direction === "up" ? 0.9 : direction === "down" ? -1.2 : -0.2;
      const reach = direction === "up" || direction === "down" ? 0.4 : 2;
      mp.Tag.add({
        label: tag, description: "", color: { r: 0.81, g: 0.29, b: 0.1 },
        anchorPosition: { x: pos.x - Math.sin(yawRad) * reach, y: pos.y + dy, z: pos.z - Math.cos(yawRad) * reach },
        stemVector: { x: 0, y: 0.25, z: 0 },
      }).catch(() => {});
    }
  };

  useEffect(() => {
    const el = frame.current;
    if (!el || !scan) return;
    let cancelled = false;
    let subs: { cancel: () => void }[] = [];
    let last = 0;
    let connecting = false;
    sdk.current = null;
    ids.current = new Set();
    tagged.current = new Set();
    setState("loading");
    const connect = async () => {
      if (connecting || cancelled) return;
      connecting = true;
      let sdkLoaded = false;
      try {
        const library = await loadMatterportSdk();
        if (cancelled) return;
        sdkLoaded = true;
        const mp = await library.connect(el, sdkKey, "");
        if (cancelled) return;
        sdk.current = mp;
        subs.push(mp.Sweep.data.subscribe({
          onCollectionUpdated(all: Record<string, { enabled?: boolean; position?: { x: number; y: number; z: number } }>) {
            ids.current = new Set(Object.keys(all).filter((k) => all[k].enabled !== false));
            where.current = Object.fromEntries(Object.entries(all).filter(([, v]) => v.position).map(([k, v]) => [k, v.position!]));
            if (pending.current && ids.current.size) { const p = pending.current; pending.current = null; setTimeout(() => move(p.sweepId, p.direction, p.tag), 600); }
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
        if (!cancelled) {
          setFailure(sdkLoaded ? "The scan could not connect. Try again." : "The Matterport viewer could not load. Check your connection and try again.");
          setState("failed");
        }
      }
    };
    el.addEventListener("load", connect);
    return () => { cancelled = true; el.removeEventListener("load", connect); subs.forEach((s) => s.cancel()); subs = []; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanId, sdkKey, retry]);

  useImperativeHandle(ref, () => ({
    lookFrom(id, sweepId, direction, tag) {
      if (id !== scanId) { pending.current = { sweepId, direction, tag }; setScanId(id); }
      else if (sdk.current && ids.current.size) move(sweepId, direction, tag);
      else pending.current = { sweepId, direction, tag };
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
          ? <iframe key={`${scan.id}:${retry}`} ref={frame} title={`3D scan: ${scan.name}`} allow="xr-spatial-tracking; fullscreen"
                    src={`https://my.matterport.com/show?m=${scan.id}&play=1&qs=1&brand=0&title=0&help=0&search=0&applicationKey=${sdkKey}`} />
          : <p className="empty-pane">No space in this building has been scanned. The plan rests on the aerial imagery and the record.</p>}
      </div>
      <footer className="pane-foot">
        {!scan ? "" : state === "loading" ? "Loading the scan…" : state === "failed" ? <span role="alert">{failure} <button type="button" onClick={() => setRetry(value => value + 1)}>Retry viewer</button></span>
          : `${scan.kind[0].toUpperCase()}${scan.kind.slice(1)}${scan.structure ? ` in ${scan.structure}` : ""}${scan.area_sqft ? `, about ${scan.area_sqft.toLocaleString()} sq ft` : ""}. Scans cover single spaces, not the whole building.`}
      </footer>
    </section>
  );
});
