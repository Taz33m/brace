import { useId, useState } from "react";
import type { OwnerCaseView } from "../../../docs/recovery-handoffs/shared-contract";
import type { RecoverySpatial } from "./spatial";
import { evidenceImageUrl } from "./spatial";
import { captureComparison, captureDate } from "./capture-comparison";
import type { CaptureSide } from "./capture-comparison";
import "./capture-comparison.css";

interface Props { spatial: RecoverySpatial | null; snapshot: OwnerCaseView | null }

function CaptureImage({ side, url }: { side: CaptureSide; url: string | null }) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  return <figure className="brace-capture-side">
    <figcaption><span className="brace-capture-role">{side.role === "before" ? "Before the incident" : "After the incident"}</span>
      <strong>{side.window}</strong><span>{side.layer ? `Vexcel · ${side.layer}` : "Vexcel capture"}</span></figcaption>
    <div className="brace-capture-image">
      {url && status !== "error" ? <>
        <img src={url} alt={`${side.role === "before" ? "Before" : "After"}-incident aerial source, capture window ${side.window}`}
          loading="lazy" decoding="async" onLoad={() => setStatus("ready")} onError={() => setStatus("error")} />
        {status === "loading" && <p className="brace-capture-loading" role="status">Loading dated image…</p>}
      </> : <p className="brace-capture-missing" role="status">{status === "error"
        ? "This image could not be loaded. Reload the case to check its availability." : side.unavailable ?? "Dated image unavailable."}</p>}
    </div>
    {side.evidence && <details className="brace-capture-source"><summary>Source details</summary>
      <p>{side.evidence.source_label}</p><p className="brace-capture-source-id">{side.collection ?? side.evidence.source_id}</p>
      <p>{side.evidence.summary}</p>
      {url && <a href={url} target="_blank" rel="noopener noreferrer">Open source image <span aria-hidden="true">↗</span></a>}
    </details>}
  </figure>;
}

export function CaptureComparison({ spatial, snapshot }: Props) {
  const titleId = useId();
  const comparison = captureComparison(spatial, snapshot);
  if (!comparison || !snapshot) return null;
  const { case: current } = snapshot;
  return <section className="brace-capture-comparison" aria-labelledby={titleId}>
    <div className="brace-spatial-heading"><div><span>Vexcel · dated aerial evidence</span><h3 id={titleId}>Before &amp; after</h3></div>
      <p>Incident · {captureDate(current.incident_at)}</p></div>
    <p className="brace-capture-context">{current.incident_name} · {current.mode_label}</p>
    <div className="brace-capture-grid">{[comparison.before, comparison.after].map(side => {
      const url = side.available ? evidenceImageUrl(side.evidence, spatial, current.case_id, current.analysis_revision, window.location.origin) : null;
      return <CaptureImage key={`${current.case_id}:${current.analysis_revision}:${side.role}:${side.evidence?.evidence_id ?? "missing"}:${url}`}
        side={side} url={url} />;
    })}</div>
    <p className="brace-capture-note">Capture windows show when the source imagery was collected. Views may differ in angle, shadows, season and resolution; visible differences alone do not establish disaster damage.</p>
    {comparison.limitation && <details className="brace-capture-limitations"><summary>Comparison limitations</summary><p>{comparison.limitation}</p></details>}
  </section>;
}
