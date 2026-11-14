// The selected evidence item: source, every date (unknowns spelled out), location, limitations and media.
import type { Evidence, LocationRef } from "../../recovery/contracts";
import { Button, EmptyState, Panel } from "../recovery-ui";
import { formatSourceDate, formatTimestamp } from "./format";
import { BINDING_LABEL, bindingLabel, evidenceKindLabel, hasImage, lookupKnown } from "./model";
import { IMAGE_UNAVAILABLE } from "./AerialCompare";

export type EvidenceInspectorProps = {
  selected_evidence_id: string | null;
  /** The selected item, or null when nothing is selected or it is not in this snapshot. */
  evidence: Evidence | null;
  on_focus: (location: LocationRef) => void;
  /**
   * Optional: re-selects the shown evidence. RecoveryWorkspace passes its wrapped handler, which also brings
   * the matching center view back (Aerial for a capture, Interior for a scan).
   */
  on_select_evidence?: (evidence_id: string) => void;
};

const VIEW_FOR_KIND: Partial<Record<Evidence["kind"], string>> = {
  vexcel_image: "Show in Aerial view",
  matterport_view: "Show in Interior view",
};

/** Kinds that are pictures by nature, so a missing one is called out as a missing image. */
const IMAGE_KINDS: ReadonlySet<string> = new Set(["vexcel_image", "matterport_view", "resident_photo"]);

function sourceDate(d: string | null): string {
  return d == null ? "Not stated by the source" : formatSourceDate(d);
}

export function EvidenceInspector({ selected_evidence_id, evidence, on_focus, on_select_evidence }: EvidenceInspectorProps) {
  if (evidence == null) {
    return (
      <Panel title="Evidence" className="ri-panel" collapsible>
        {selected_evidence_id == null ? (
          <EmptyState title="No evidence selected">Select an evidence chip in Condition, Value or Recovery, or a capture in Aerial, to see its source and dates here.</EmptyState>
        ) : (
          <EmptyState title="That evidence is not in this case">
            The selected item ({selected_evidence_id}) is not part of the current case snapshot.
          </EmptyState>
        )}
      </Panel>
    );
  }

  const loc = evidence.location;
  // An unknown binding is styled like "unverified" (bindingLabel says it is treated as unverified).
  const bindingClass = loc ? (lookupKnown(BINDING_LABEL, loc.binding) !== undefined ? loc.binding : "unverified") : null;
  const viewLabel = lookupKnown(VIEW_FOR_KIND, evidence.kind);
  const media = evidence.media;
  const dates: [string, string][] = [
    ["Captured", sourceDate(evidence.captured_at)],
    ["Effective", sourceDate(evidence.effective_at)],
    ["Available", sourceDate(evidence.available_at)],
    ["Received by Brace", formatTimestamp(evidence.received_at)],
    ["Model created", sourceDate(evidence.model_created_at)],
  ];

  return (
    <Panel title="Evidence" aside={<span className="ri-kind">{evidenceKindLabel(evidence.kind)}</span>} className="ri-panel" collapsible>
      <div className="ri-grid">
        <div className="ri-main">
          <p className="ri-source">{evidence.source_label}</p>
          <p className="ri-id">
            Source ID <code>{evidence.source_id}</code>
          </p>
          <p className="ri-summary">{evidence.summary}</p>

          <dl className="ri-dates">
            {dates.map(([k, v]) => (
              <div key={k} className="ri-date">
                <dt>{k}</dt>
                <dd className={v === "Not stated by the source" || v === "Date unknown" ? "ri-unknown" : undefined}>{v}</dd>
              </div>
            ))}
          </dl>

          <div className="ri-location">
            <p className="ri-sub">Location</p>
            {loc ? (
              <>
                <p>
                  {loc.label}
                  {loc.unit_label && <span className="ri-unit"> · Unit {loc.unit_label}</span>}
                </p>
                <p className={`ri-binding ri-binding--${bindingClass}`}>{bindingLabel(loc.binding)}</p>
                <Button variant="default" onClick={() => on_focus(loc)}>
                  Show location
                </Button>
              </>
            ) : (
              <p className="ri-unknown">No location recorded for this evidence.</p>
            )}
          </div>

          <div className="ri-limits">
            <p className="ri-sub">Limitations</p>
            {evidence.limitations.length > 0 ? (
              <ul>
                {evidence.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            ) : (
              <p className="ri-unknown">The source lists no limitations.</p>
            )}
          </div>
        </div>

        <div className="ri-media">
          {media && hasImage(evidence) ? (
            <img src={media.url} alt={media.alt} />
          ) : media && typeof media.url === "string" && media.url.trim() !== "" ? (
            // Media that is not an image (a PDF notice, say) is offered as a file, never drawn as a broken image.
            <div className="ri-media-missing">
              <a href={media.url} target="_blank" rel="noreferrer">
                Open the attached file{media.mime_type ? ` (${media.mime_type})` : ""}
              </a>
            </div>
          ) : (
            <div className="ri-media-missing">{IMAGE_KINDS.has(evidence.kind) ? IMAGE_UNAVAILABLE : "No image attached"}</div>
          )}
          {viewLabel && on_select_evidence && (
            <Button variant="default" className="ri-view-btn" onClick={() => on_select_evidence(evidence.evidence_id)}>
              {viewLabel}
            </Button>
          )}
        </div>
      </div>
    </Panel>
  );
}
