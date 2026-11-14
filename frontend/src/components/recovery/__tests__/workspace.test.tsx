// Workspace shell: load states, panels, slots, the aerial default pair and timestamp handling.
import type { Evidence, MediaRef, MoneyRange } from "../../../recovery/contracts";
import { FIXTURE_LABEL, fixtureCases, fixtureSnapshot } from "../fixtures/preview-fixture";
import {
  AerialCompare,
  aerialCaptures,
  aerialRelationNote,
  choiceForSelected,
  defaultAerialPair,
  IMAGE_UNAVAILABLE,
  NO_AERIAL_CHOICE,
} from "../AerialCompare";
import type { AerialPairChoice } from "../AerialCompare";
import { compareSourceDatesChronological, compareSourceDatesCoarse, formatSourceDate, formatTimestamp, rangeKindLabel } from "../format";
import { LOAD_ERROR_FALLBACK, RecoveryWorkspace, REFRESH_ERROR_FALLBACK } from "../RecoveryWorkspace";
import type { RecoveryWorkspaceProps } from "../RecoveryWorkspace";
import { RecoveryPreview } from "../RecoveryPreview";
import { assert, assertEqual, assertIncludes, assertNotIncludes, render, test } from "./harness";
import { noop, textOf } from "./test-utils";

const MAP = "MAP-SLOT-CONTENT";
const INTERIOR = "INTERIOR-SLOT-CONTENT";

function workspace(over: Partial<RecoveryWorkspaceProps> = {}): string {
  const props: RecoveryWorkspaceProps = {
    cases: fixtureCases(),
    snapshot: fixtureSnapshot("full"),
    state: "ready",
    error: null,
    busy: false,
    selected_evidence_id: null,
    map_slot: <div className="test-map">{MAP}</div>,
    interior_slot: <div className="test-interior">{INTERIOR}</div>,
    on_open_case: noop,
    on_back_to_prepare: noop,
    on_focus: noop,
    on_select_evidence: noop,
    on_command: () => Promise.resolve(),
    ...over,
  };
  return render(<RecoveryWorkspace {...props} />);
}

/** The chain of enclosing elements (tag + first class) around `needle` in static markup. */
function ancestry(html: string, needle: string): string[] {
  const at = html.indexOf(needle);
  assert(at >= 0, `markup contains ${needle}`);
  const stack: string[] = [];
  const tag = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(\/?)>/g;
  for (let m = tag.exec(html); m && m.index < at; m = tag.exec(html)) {
    const [, closing, name, attrs, selfClosing] = m;
    if (closing) stack.pop();
    else if (!selfClosing) stack.push(`${name}.${/class="([^" ]*)/.exec(attrs)?.[1] ?? ""}`);
  }
  return stack;
}

/* ------------------------------------------------------------ load states */

test("workspace/states: ready with an error keeps the workspace and shows an inline banner above the grid", () => {
  const view = fixtureSnapshot("full");
  const html = workspace({ snapshot: view, error: "Live updates stopped (test)" });
  const text = textOf(html);
  assertIncludes(html, 'role="alert"');
  assertIncludes(text, "Live updates stopped (test)");
  assertIncludes(text, `case rev ${view.case.case_revision}`, "the banner says which data is still shown");
  assert(html.indexOf("rw-banner") >= 0 && html.indexOf("rw-banner") < html.indexOf("rw-grid"), "the banner sits above the grid");
  assertIncludes(html, 'role="tablist"', "the tabs are still there");
  assertIncludes(html, MAP);
  assertIncludes(html, INTERIOR);
  assertNotIncludes(text, "Could not load this case", "no full-page error while a snapshot exists");

  const clean = workspace({ snapshot: view, error: "   " });
  assertNotIncludes(clean, "rw-banner", "a blank error is no error");
});

test("workspace/states: loading with a snapshot keeps the slots, tabs and drafts, with a quiet Refreshing… mark", () => {
  const html = workspace({ state: "loading" });
  const text = textOf(html);
  assertIncludes(html, MAP, "map slot still rendered");
  assertIncludes(html, INTERIOR, "interior slot still rendered");
  assertIncludes(text, "Refreshing…");
  assertIncludes(html, 'role="tablist"');
  assertNotIncludes(text, "Loading the recovery case", "no full-page loading screen");
  assertNotIncludes(html, "rw-banner");
  assertNotIncludes(html, 'aria-busy="true"', "the workspace stays usable while refreshing");
});

test("workspace/states: error with a snapshot keeps the slots and shows the error as a banner", () => {
  const html = workspace({ state: "error", error: "Refresh failed (test)" });
  const text = textOf(html);
  assertIncludes(html, MAP);
  assertIncludes(html, INTERIOR);
  assertIncludes(text, "Refresh failed (test)");
  assertIncludes(html, 'role="tablist"');
  assertNotIncludes(text, "Could not load this case");

  const silent = textOf(workspace({ state: "error", error: null }));
  assertIncludes(silent, REFRESH_ERROR_FALLBACK, "an error state without a message still shows a banner");
});

test("workspace/states: without a snapshot a load error is full-page and promises no automatic reload", () => {
  const text = textOf(workspace({ snapshot: null, state: "error", error: null }));
  assertIncludes(text, "Could not load this case");
  assertIncludes(text, LOAD_ERROR_FALLBACK);
  for (const promise of ["will reload", "brace will", "reloading", "automatically"]) {
    assertNotIncludes(text.toLowerCase(), promise, "no reload promise");
  }
  assertIncludes(text, "choose the case again");
  assertIncludes(text, "pick another case");
  assertIncludes(text, "go back to Prepare");

  const noCases = textOf(workspace({ cases: [], snapshot: null, state: "error", error: "Recovery service down (test)" }));
  assertIncludes(noCases, "Recovery service down (test)");
  assertIncludes(noCases, "go back to Prepare");
  assertNotIncludes(noCases, "choose the case again", "no case list to choose from");
  assertNotIncludes(noCases.toLowerCase(), "will reload");
});

test("workspace/states: without a snapshot, loading is full-page and the slots stay mounted underneath", () => {
  const html = workspace({ snapshot: null, state: "loading" });
  assertIncludes(textOf(html), "Loading the recovery case");
  assertIncludes(html, 'aria-busy="true"');
  assertNotIncludes(html, 'role="tablist"');
  assertIncludes(html, MAP, "map slot mounted (hidden) so it is not remounted when the case arrives");
  assertIncludes(html, INTERIOR);
  const empty = textOf(workspace({ snapshot: null }));
  assertIncludes(empty, "Select a case");
});

test("workspace/slots: the map and interior slots sit under the same elements in every state", () => {
  const states: Partial<RecoveryWorkspaceProps>[] = [
    {},
    { state: "loading" },
    { state: "error", error: "x (test)" },
    { error: "y (test)" },
    { snapshot: fixtureSnapshot("stale", "fx-case-2") },
    { snapshot: null, state: "loading" },
    { snapshot: null, state: "error" },
    { snapshot: null },
  ];
  for (const needle of [MAP, INTERIOR]) {
    const reference = ancestry(workspace(), needle);
    assertIncludes(reference.join(" > "), "section.r-panel > div.r-panel-body > div.rw-viewport > div.rw-layer > div.rw-slot");
    states.forEach((over, i) => assertEqual(ancestry(workspace(over), needle), reference, `${needle} in state #${i}`));
  }
});

/* ----------------------------------------------------------------- panels */

test("workspace/panels: all three tab panels render; the inactive two are hidden", () => {
  const html = workspace();
  const panels = [...html.matchAll(/<div[^>]*role="tabpanel"[^>]*>/g)].map((m) => m[0]);
  assertEqual(panels.length, 3, "condition, value and recovery panels are all in the DOM");
  const hidden = panels.filter((p) => /\shidden=""/.test(p));
  assertEqual(hidden.length, 2);
  assert(/id="rw-right-panel-condition"/.test(panels.find((p) => !/\shidden=""/.test(p)) ?? ""), "the selected Condition panel is visible");
  for (const v of ["condition", "value", "recovery"]) assertIncludes(html, `aria-controls="rw-right-panel-${v}"`, `tab ${v} points at its panel`);
});

test("workspace/inspector: a selected capture offers a way back to its view", () => {
  const capture = textOf(workspace({ selected_evidence_id: "fx-ev-aerial-oblique" }));
  assertIncludes(capture, "Show in Aerial view");
  assertIncludes(capture, IMAGE_UNAVAILABLE, "the capture without media shows the explicit missing-image state");
  assertIncludes(textOf(workspace({ selected_evidence_id: "fx-ev-mp-2b" })), "Show in Interior view");
  assertNotIncludes(textOf(workspace({ selected_evidence_id: "fx-ev-photo-2b" })), "Show in Aerial view");
});

/* ----------------------------------------------------------------- aerial */

function aerial(captures: Evidence[], incident_at: string, choice: AerialPairChoice = NO_AERIAL_CHOICE, selected: string | null = null): string {
  return render(
    <AerialCompare captures={captures} incident_at={incident_at} choice={choice} onChoice={noop} selected_evidence_id={selected} on_select_evidence={noop} />,
  );
}

test("aerial: on the full fixture the default pair prefers captures with an image", () => {
  for (const caseId of ["fx-case-1", "fx-case-2", "fx-case-3"]) {
    const view = fixtureSnapshot("full", caseId);
    const caps = aerialCaptures(view.evidence);
    assertEqual(
      caps.map((c) => c.evidence_id),
      ["fx-ev-aerial-before", "fx-ev-aerial-oblique", "fx-ev-aerial-after"],
      `${caseId}: capture order (the date-only oblique sorts within its day)`,
    );
    const pair = defaultAerialPair(caps, view.case.incident_at);
    assertEqual(pair.before?.evidence_id, "fx-ev-aerial-before", `${caseId} before`);
    assertEqual(pair.after?.evidence_id, "fx-ev-aerial-after", `${caseId}: the 15:42Z capture with an image, not the oblique without one`);
    const html = aerial(caps, view.case.incident_at);
    assertNotIncludes(html, IMAGE_UNAVAILABLE, `${caseId}: no missing image by default`);
    assertIncludes(html, 'type="range"', `${caseId}: the wipe is offered`);
    assertNotIncludes(textOf(html), "no capture from", `${caseId}: no mismatch note on a proper pair`);
  }
});

const IMG: MediaRef = { media_id: "m", url: "data:image/svg+xml,%3Csvg%2F%3E", alt: "test image", mime_type: "image/svg+xml" };

function capture(id: string, captured_at: string | null, media: MediaRef | null): Evidence {
  return {
    evidence_id: id,
    kind: "vexcel_image",
    source_id: `src-${id}`,
    source_label: `Capture ${id} (test)`,
    captured_at,
    effective_at: null,
    available_at: null,
    received_at: "2024-07-12T00:00:00Z",
    model_created_at: null,
    location: null,
    media,
    summary: "",
    limitations: [],
  };
}

test("aerial: a side uses a capture without an image only when it has nothing else", () => {
  const caps = aerialCaptures([capture("post", "2024-07-11", IMG), capture("pre-noimg", "2024-06-01", null), capture("pre-old", "2024-04-01", IMG)]);
  const pair = defaultAerialPair(caps, "2024-07-08");
  assertEqual(pair.before?.evidence_id, "pre-old", "an older capture with an image beats a newer one without");
  assertEqual(pair.after?.evidence_id, "post");

  const onlyBlank = aerialCaptures([capture("post", "2024-07-11", IMG), capture("pre-noimg", "2024-06-01", null)]);
  const fallback = defaultAerialPair(onlyBlank, "2024-07-08");
  assertEqual(fallback.before?.evidence_id, "pre-noimg", "the only pre-incident capture is still used");
  const html = aerial(onlyBlank, "2024-07-08");
  assertIncludes(html, IMAGE_UNAVAILABLE, "and its side shows the explicit missing state");
  assertNotIncludes(html, 'type="range"', "no wipe against a missing image");
});

test("aerial: the before/after notes are computed from the captures, not assumed", () => {
  const pre = capture("pre", "2024-06-01", IMG);
  const post = capture("post", "2024-07-11", IMG);
  const post2 = capture("post2", "2024-07-20", IMG);
  const incident = "2024-07-08";

  assertIncludes(aerialRelationNote("Before", post, incident, { pre: true, post: true }) ?? "", "is available under Before capture");
  assertIncludes(aerialRelationNote("Before", post, incident, { pre: false, post: true }) ?? "", "no capture from on or before the incident date is available");
  assertIncludes(aerialRelationNote("After", pre, incident, { pre: true, post: true }) ?? "", "A capture from after the incident date is available");
  assertIncludes(aerialRelationNote("After", pre, incident, { pre: true, post: false }) ?? "", "no capture from after the incident date is available");
  assertEqual(aerialRelationNote("Before", pre, incident, { pre: true, post: true }), null);
  assertEqual(aerialRelationNote("After", post, incident, { pre: true, post: true }), null);
  assertIncludes(aerialRelationNote("Before", capture("same", "2024-07-08T09:00:00Z", IMG), incident, { pre: true, post: true }) ?? "", "on the incident date");
  assertIncludes(aerialRelationNote("After", capture("undated", null, IMG), incident, { pre: true, post: true }) ?? "", "Capture date unknown");

  // Only post-incident captures: the two earliest are compared and the Before side says why.
  const onlyPost = textOf(aerial(aerialCaptures([post2, post]), incident));
  assertIncludes(onlyPost, "no capture from on or before the incident date is available");
  // The owner picked a post-incident capture as Before although a pre-incident one exists.
  const picked = textOf(aerial(aerialCaptures([pre, post, post2]), incident, { before: "post", after: "post2" }));
  assertIncludes(picked, "A capture from on or before the incident date is available under Before capture");
  assertNotIncludes(picked, "no capture from on or before");
});

test("aerial: evidence selected elsewhere without an image still shows, with the missing-image state", () => {
  const view = fixtureSnapshot("full");
  const caps = aerialCaptures(view.evidence);
  const next = choiceForSelected(caps, view.case.incident_at, NO_AERIAL_CHOICE, "fx-ev-aerial-oblique");
  assertEqual(next, { before: "fx-ev-aerial-before", after: "fx-ev-aerial-oblique" }, "a same-day post-incident capture replaces After");
  assert(next, "choice");
  const html = aerial(caps, view.case.incident_at, next, "fx-ev-aerial-oblique");
  assertIncludes(html, IMAGE_UNAVAILABLE);
  assertIncludes(textOf(html), "Synthetic aerial capture, east oblique (fixture)");
  assertIncludes(textOf(html), "(no image)", "the picker marks captures without an image");
  assertEqual(choiceForSelected(caps, view.case.incident_at, NO_AERIAL_CHOICE, "fx-ev-mp-2b"), null, "not a capture");
});

/* ------------------------------------------------------------------ dates */

test("format: formatTimestamp reads a timestamp without a zone as UTC and never shifts it", () => {
  // The runner sets TZ=America/Los_Angeles; a local-time parse would show 11:15 UTC here.
  assertEqual(formatTimestamp("2024-07-08T04:15:00"), "8 Jul 2024, 04:15 UTC");
  assertEqual(formatTimestamp("2024-07-08T04:15"), "8 Jul 2024, 04:15 UTC");
  assertEqual(formatTimestamp("2024-07-08 04:15:00"), "8 Jul 2024, 04:15 UTC");
  assertEqual(formatTimestamp("2024-07-08T23:59:59.999999"), "8 Jul 2024, 23:59 UTC");
  assertEqual(formatSourceDate("2024-07-08T04:15:00"), "8 Jul 2024, 04:15 UTC");
  assertEqual(formatTimestamp("2024-07-08T04:15:00Z"), "8 Jul 2024, 04:15 UTC");
  assertEqual(formatTimestamp("2024-07-08T04:15:00-04:00"), "8 Jul 2024, 08:15 UTC");
  assertEqual(formatTimestamp("2024-07-08T04:15:00+0530"), "7 Jul 2024, 22:45 UTC");
  // Date-only behaviour is unchanged.
  assertEqual(formatTimestamp("2024-07-08"), "8 Jul 2024");
  assertEqual(formatTimestamp("2024-07"), "Jul 2024");
  assertEqual(formatTimestamp(null), "Time unknown");
  // Not a timestamp: shown as given, never guessed in some zone.
  assertEqual(formatTimestamp("2024-02-30T10:00:00Z"), "2024-02-30T10:00:00Z");
  assertEqual(formatTimestamp("yesterday"), "yesterday");
});

test("format: source dates compare at the coarser precision with no time-zone shift", () => {
  assertEqual(compareSourceDatesCoarse("2024-07-11", "2024-07-11T15:42:00Z"), 0);
  assertEqual(compareSourceDatesCoarse("2024-07", "2024-07-31"), 0);
  assertEqual(compareSourceDatesCoarse("2024", "2024-12-31T23:00:00Z"), 0);
  assertEqual(compareSourceDatesCoarse("2024-07-08T23:30:00-04:00", "2024-07-08"), 0, "its own calendar day, not 9 Jul UTC");
  assertEqual(compareSourceDatesCoarse("2024-07-08T23:30:00-04:00", "2024-07-09T01:00:00Z"), 1, "two timestamps compare as instants");
  assertEqual(compareSourceDatesCoarse("2024-07-08T04:15:00", "2024-07-08T04:15:00Z"), 0, "no zone means UTC");
  assertEqual(compareSourceDatesCoarse("2024-05-18", "2024-07-08"), -1);
  assertEqual(compareSourceDatesCoarse(null, "2024"), null);
  assertEqual(compareSourceDatesCoarse("soon", "2024"), null);

  const sorted = ["2024-07-11T15:42:00Z", null, "2024-07-11", "soon", "2024-07", "2024-05-18"].sort(compareSourceDatesChronological);
  assertEqual(sorted, ["2024-05-18", "2024-07", "2024-07-11", "2024-07-11T15:42:00Z", null, "soon"]);
});

/* --------------------------------------------------------- unknown values */

test("unknown values: an unrecognised kind, binding, mode or range kind reads as such, never blank", () => {
  const view = fixtureSnapshot("full");
  const ev = view.evidence.find((e) => e.evidence_id === "fx-ev-aerial-after");
  assert(ev && ev.location, "fixture capture with a location");
  (ev as { kind: string }).kind = "drone_video";
  (ev.location as { binding: string }).binding = "lidar_match";
  (view.case as { mode: string }).mode = "tabletop_drill";
  const text = textOf(workspace({ snapshot: view, selected_evidence_id: "fx-ev-aerial-after" }));
  assertIncludes(text, "Drone video (unrecognised kind)", "inspector kind");
  assertIncludes(text, "Unrecognised binding “Lidar match”, treated as unverified", "inspector binding");
  assertIncludes(text, "Tabletop drill (unrecognised mode)", "mode banner and queue");
  assertNotIncludes(text, "undefined");
  assertNotIncludes(text, "Show in Aerial view", "an unknown kind gets no view shortcut");

  const label = rangeKindLabel("monte_carlo_band" as MoneyRange["range_kind"]);
  assertEqual(label, "Monte carlo band range (unrecognised kind), not a confidence interval");
});

test("aerial: media that is not an image counts as no image for the pair and the wipe", () => {
  const pdf: MediaRef = { media_id: "p", url: "/api/recovery/media/p", alt: "a document", mime_type: "application/pdf" };
  const caps = aerialCaptures([capture("pre", "2024-06-01", pdf), capture("pre-old", "2024-04-01", IMG), capture("post", "2024-07-11", IMG)]);
  assertEqual(defaultAerialPair(caps, "2024-07-08").before?.evidence_id, "pre-old", "a PDF is not an image");
  const html = aerial(caps, "2024-07-08", { before: "pre", after: "post" });
  assertIncludes(html, IMAGE_UNAVAILABLE, "the PDF side shows the missing-image state, not a broken <img>");
  assertNotIncludes(html, "/api/recovery/media/p", "no <img> points at the PDF");
});

/* ---------------------------------------------------------------- preview */

test("preview: the stand-in parent renders with its fixture labels", () => {
  const text = textOf(render(<RecoveryPreview />));
  assertIncludes(text, FIXTURE_LABEL);
  assertIncludes(text, "Map slot: the lead mounts Brace's map here");
  assertIncludes(text, "Make next command fail");
  assertIncludes(text, "Refresh failed");
});
