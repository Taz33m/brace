// Center stage: Overview (parent's map), Aerial (dated wipe comparison), Interior (parent's interior viewer).
// The map and interior slots are always mounted, at the same place in the tree, whatever the case or the load
// state: an inactive slot is only made invisible (visibility, not display:none), so the map and the Matterport
// iframe keep their state and size instead of reloading on a view switch, a case switch, a refresh or an error.
// With no case to show, a status layer (loading, load error, nothing selected) covers the hidden slots.
import type { ReactNode } from "react";
import type { Evidence, OwnerCaseView } from "../../recovery/contracts";
import { EmptyState, EvidenceBadge, Panel, SegmentedControl } from "../recovery-ui";
import { AerialCompare } from "./AerialCompare";
import type { AerialPairChoice } from "./AerialCompare";
import { formatSourceDate } from "./format";
import { bindingLabel } from "./model";

export type CenterView = "overview" | "aerial" | "interior";

const VIEW_OPTIONS = [
  { value: "overview", label: "Overview" },
  { value: "aerial", label: "Aerial" },
  { value: "interior", label: "Interior" },
] as const;

export type CenterStageProps = {
  /** The open case, or null when none is shown; the slots then stay mounted but hidden under `placeholder`. */
  view: OwnerCaseView | null;
  /** Panel title. Defaults to "Property view". */
  title?: ReactNode;
  /** Covers the stage when `view` is null (loading, load error, nothing selected). */
  placeholder?: ReactNode;
  center: CenterView;
  on_center: (v: CenterView) => void;
  captures: Evidence[];
  aerial_choice: AerialPairChoice;
  on_aerial_choice: (c: AerialPairChoice) => void;
  selected_evidence_id: string | null;
  on_select_evidence: (evidence_id: string) => void;
  map_slot: ReactNode;
  interior_slot: ReactNode;
};

const layerClass = (base: string, visible: boolean) => (visible ? base : `${base} is-hidden`);

export function CenterStage({
  view,
  title = "Property view",
  placeholder,
  center,
  on_center,
  captures,
  aerial_choice,
  on_aerial_choice,
  selected_evidence_id,
  on_select_evidence,
  map_slot,
  interior_slot,
}: CenterStageProps) {
  const showOverview = view != null && center === "overview";
  const showInterior = view != null && center === "interior";
  const scans = view ? view.evidence.filter((e) => e.kind === "matterport_view") : [];

  // The element types and positions below must not change between states, or React would remount the slots.
  return (
    <Panel
      title={title}
      aside={view ? <SegmentedControl options={VIEW_OPTIONS} value={center} onChange={on_center} ariaLabel="Center view" /> : undefined}
      className={view ? "rw-stage" : "rw-stage is-idle"}
    >
      <div className="rw-viewport">
        <div className={layerClass("rw-layer rw-layer--slot", showOverview)} aria-hidden={!showOverview || undefined} aria-label="Map overview">
          <div className="rw-slot">{map_slot}</div>
        </div>

        {view && center === "aerial" && (
          <div className="rw-layer rw-layer--scroll" aria-label="Aerial comparison">
            <AerialCompare
              captures={captures}
              incident_at={view.case.incident_at}
              choice={aerial_choice}
              onChoice={on_aerial_choice}
              selected_evidence_id={selected_evidence_id}
              on_select_evidence={on_select_evidence}
            />
          </div>
        )}

        <div className={layerClass("rw-layer rw-layer--interior", showInterior)} aria-hidden={!showInterior || undefined} aria-label="Interior">
          <div className="rw-slot">{interior_slot}</div>
          {view && (
            <div className="rw-scans">
              <p className="rw-scans-title">Interior scans in this case</p>
              {scans.length === 0 ? (
                <EmptyState title="No interior scans">No Matterport view is attached to this case.</EmptyState>
              ) : (
                <ul className="rw-scan-list">
                  {scans.map((s) => (
                    <li key={s.evidence_id}>
                      <EvidenceBadge
                        label={s.location?.label ?? s.source_label}
                        kindLabel={s.location ? bindingLabel(s.location.binding) : "Location not recorded"}
                        date={formatSourceDate(s.captured_at)}
                        selected={selected_evidence_id === s.evidence_id}
                        onClick={() => on_select_evidence(s.evidence_id)}
                        title={s.summary}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {!view && <div className="rw-layer rw-layer--status">{placeholder}</div>}
      </div>
    </Panel>
  );
}
