import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ResidentReport } from "../types";

const POLL_MS = 4000;

/** What residents of this building have reported, as it lands: each one filed against the room and fixture it names.
    It reads the site model, so the owner sees the after side in the same place as the before side. */
export function ReportsFeed({ id, onOpen }: { id: number; onOpen?: (r: ResidentReport) => void }) {
  const [reports, setReports] = useState<ResidentReport[]>([]);
  const [fresh, setFresh] = useState<string | null>(null);
  const known = useRef<Set<string> | null>(null);

  useEffect(() => {
    let current = true;
    const read = () => api.siteModel(id).then((m) => {
      if (!current) return;
      const arrived = known.current && m.reports.find((r) => !known.current!.has(r.id));
      known.current = new Set(m.reports.map((r) => r.id));
      if (arrived) setFresh(arrived.id);
      setReports(m.reports);
    }).catch(() => { /* no site model for this building, or not signed in: show nothing */ });
    read();
    const timer = window.setInterval(read, POLL_MS);
    return () => { current = false; window.clearInterval(timer); };
  }, [id]);

  if (!reports.length) return null;
  return (
    <aside className="reports-feed" aria-live="polite" aria-label="Reports from residents">
      <h3>From residents <span>{reports.length}</span></h3>
      <ul>
        {[...reports].reverse().slice(0, 3).map((r) => (
          <li key={r.id} className={`${r.id === fresh ? "is-fresh" : ""}${r.where && onOpen ? " can-open" : ""}`}
              onClick={() => { if (r.where && onOpen) onOpen(r); }} title={r.where && onOpen ? "Open this room in the scan" : undefined}>
            <strong>{r.where ? `${r.where.room ?? "A room"}${r.where.thing ? `, at the ${r.where.thing}` : ""}` : "Not matched to a scanned room"}</strong>
            <p>“{r.text}”</p>
            <small>{r.where ? `${r.where.scan_name}${r.where.placed_by ? ", placed from the resident's words" : ""}. ` : ""}{r.status ? `${r.status.replace(/\.$/, "")}.` : "Reported, not yet reviewed."}</small>
          </li>
        ))}
      </ul>
    </aside>
  );
}
