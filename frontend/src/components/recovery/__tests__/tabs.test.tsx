// Tab rendering tests: Condition, Value, Recovery (tasks, invitations), comparables and the event timeline.
// Static rendering only; click behaviour is covered through the pure helpers the click handlers call.
import type {
  CaseEvent,
  Comparable,
  Evidence,
  LocationRef,
  Observation,
  OwnerCaseView,
  RecoveryTask,
  SupportReceipt,
  TaskStatus,
} from "../../../recovery/contracts";
import { ComparablesList, comparablePrice } from "../ComparablesList";
import { ConditionTab } from "../ConditionTab";
import { EventTimeline, SUPERSEDED_PUBLICATION_LABEL } from "../EventTimeline";
import { fixtureSnapshot } from "../fixtures/preview-fixture";
import {
  bindingLabel,
  commandKey,
  evidenceKindLabel,
  findingEvidence,
  latestCaptured,
  observationStatusLabel,
  taskSiteTarget,
} from "../model";
import { INVITATION_CREATED_NOTE, InvitationRow, RecoveryTab } from "../RecoveryTab";
import { TaskCard } from "../TaskCard";
import { ValueTab } from "../ValueTab";
import { assert, assertEqual, assertIncludes, assertNotIncludes, render, test } from "./harness";
import { fakeRunner, noop, textOf } from "./test-utils";
import type { FakeRunner } from "./test-utils";

const ROOF = "fx-obs-roof-membrane";

/* ---------------------------------------------------------------- helpers */

function condition(view: OwnerCaseView, runner: FakeRunner = fakeRunner()): string {
  return render(
    <ConditionTab view={view} busy={false} runner={runner} selected_evidence_id={null} on_focus={noop} on_select_evidence={noop} />,
  );
}

function value(view: OwnerCaseView, runner: FakeRunner = fakeRunner()): string {
  return render(<ValueTab view={view} busy={false} runner={runner} on_select_evidence={noop} />);
}

function recovery(view: OwnerCaseView, runner: FakeRunner = fakeRunner()): string {
  return render(<RecoveryTab view={view} busy={false} runner={runner} on_focus={noop} on_select_evidence={noop} />);
}

function taskCard(view: OwnerCaseView, task: RecoveryTask, runner: FakeRunner = fakeRunner()): string {
  return render(<TaskCard task={task} view={view} busy={false} runner={runner} on_focus={noop} on_select_evidence={noop} />);
}

function find<T>(items: readonly T[], pred: (x: T) => boolean, what: string): T {
  const hit = items.find(pred);
  assert(hit !== undefined, `fixture has ${what}`);
  return hit;
}

const taskWith = (view: OwnerCaseView, status: TaskStatus) => find(view.tasks, (t) => t.status === status, `a ${status} task`);

/** The <li> of the observation card titled `title`. Cards contain no nested list items. */
function observationCard(html: string, title: string): string {
  const card = [...html.matchAll(/<li class="rc-obs(?: [^"]*)?">[\s\S]*?<\/li>/g)].map((m) => m[0]).find((c) => c.includes(title));
  assert(card !== undefined, `observation card "${title}" rendered`);
  return card;
}

const observationCardCount = (html: string) => [...html.matchAll(/<li class="rc-obs(?: [^"]*)?">/g)].length;

/** The attribute text of the button whose visible text is exactly `label`, or undefined. */
function buttonAttrs(html: string, label: string): string | undefined {
  return [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find((m) => textOf(m[2]) === label)?.[1];
}

const isDisabled = (attrs: string) => /\bdisabled\b/.test(attrs);

/** The task card's Schedule value, as markup and as text. */
function scheduleOf(view: OwnerCaseView, task: RecoveryTask): { html: string; text: string } {
  const m = /<dt>Schedule<\/dt><dd>([\s\S]*?)<\/dd>/.exec(taskCard(view, task));
  assert(m, "schedule row rendered");
  return { html: m[1], text: textOf(m[1]) };
}

/* -------------------------------------------------------------- condition */

test("Condition: the roof finding's thumbnail and click target are the post-incident capture, not May", () => {
  const view = fixtureSnapshot("full");
  const roof = find(view.observations, (o) => o.observation_id === ROOF, "the roof finding");
  const picked = findingEvidence(view, roof);
  assertEqual(picked.supporting?.evidence_id, "fx-ev-aerial-after", "supporting image");
  assertEqual(picked.primary?.evidence_id, "fx-ev-aerial-after", "a click on the finding selects that same evidence");
  assertEqual(roof.location?.location_id, "fx-loc-roof-east", "and focuses the finding's location");

  const after = find(view.evidence, (e) => e.evidence_id === "fx-ev-aerial-after", "the post-incident capture");
  assert(after.media, "post-incident capture has media");
  const card = observationCard(condition(view), roof.title);
  assertIncludes(card, `alt="${after.media.alt}"`, "thumbnail is the post-incident capture");
  assertNotIncludes(card, "before the incident", "the May capture is not the thumbnail");
  assertIncludes(textOf(card), "Captured 11 Jul 2024, 15:42 UTC", "Captured shows the post-incident capture");

  const reversed: Observation = { ...roof, evidence_ids: [...roof.evidence_ids].reverse() };
  assertEqual(findingEvidence(view, reversed).supporting?.evidence_id, "fx-ev-aerial-after", "independent of citation order");
});

test("Condition: latest capture with an image wins; unknown dates last; no timezone shift", () => {
  const view = fixtureSnapshot("full");
  const base = find(view.evidence, (e) => e.evidence_id === "fx-ev-aerial-after", "an aerial capture");
  const media = base.media;
  assert(media, "base capture has media");
  const ev = (id: string, captured_at: string | null, withImage = true): Evidence => ({
    ...base,
    evidence_id: id,
    source_id: `src-${id}`,
    captured_at,
    media: withImage ? { ...media, media_id: `m-${id}` } : null,
  });

  // "2024-07-11T02:00:00" has no offset: read as UTC it is 02:00Z, earlier than 05:00Z. Read in the runner's local
  // time (Los Angeles) it would be 09:00Z and wrongly win.
  const items = [ev("undated", null), ev("may", "2024-05-18"), ev("no-offset", "2024-07-11T02:00:00"), ev("utc", "2024-07-11T05:00:00Z"), ev("no-image", "2024-08-01", false)];
  view.evidence = items;
  const o: Pick<Observation, "evidence_ids"> = { evidence_ids: items.map((e) => e.evidence_id) };
  assertEqual(findingEvidence(view, o).supporting?.evidence_id, "utc", "latest capture that has an image, no timezone shift");
  assertEqual(findingEvidence(view, o).primary?.evidence_id, "utc", "the click selects the same evidence");

  assertEqual(latestCaptured([ev("a", null), ev("b", "2024")])?.evidence_id, "b", "an unknown date sorts last");
  assertEqual(latestCaptured([ev("a", null), ev("b", null)])?.evidence_id, "a", "all unknown: the first cited");
  assertEqual(latestCaptured([ev("d", "2024-07-11"), ev("m", "2024-07")])?.evidence_id, "d", "date-only beats its month");
  // As strings "…T01:00:00-04:00" sorts before "…T04:00:00Z", but as instants it is 05:00Z, the later of the two.
  assertEqual(latestCaptured([ev("x", "2024-07-11T01:00:00-04:00"), ev("y", "2024-07-11T04:00:00Z")])?.evidence_id, "x", "offsets compare as instants, not strings");

  const noImages: Pick<Observation, "evidence_ids"> = { evidence_ids: ["no-image", "may"] };
  view.evidence = [ev("no-image", "2024-08-01", false), ev("may", "2024-05-18")];
  assertEqual(findingEvidence(view, noImages).supporting?.evidence_id, "may", "only items with an image can be the thumbnail");
});

test("Condition: an inferred observation never renders a verified mark", () => {
  const inferred = find(fixtureSnapshot("full").observations, (o) => o.basis === "inferred", "a model suggestion");
  for (const status of ["reported", "under_review", "needs_more_info"]) {
    const view = fixtureSnapshot("full");
    view.observations = [{ ...inferred, status: status as Observation["status"] }];
    const card = observationCard(condition(view), inferred.title);
    assertNotIncludes(card, "r-tone-verified", `${status}: no verified tone`);
    assertNotIncludes(textOf(card), "Verified", `${status}: no Verified label`);
    assertIncludes(textOf(card), "Model suggestion (not verified)", `${status}: labelled as a model suggestion`);
    assertIncludes(card, "rc-obs--inferred", `${status}: drawn as provisional`);
  }
});

test("Condition: structure_id shows next to the location and room association", () => {
  const view = fixtureSnapshot("full");
  const roof = find(view.observations, (o) => o.observation_id === ROOF, "the roof finding");
  assertIncludes(textOf(observationCard(condition(view), roof.title)), "Location Roof, east wing (fixture) Verified space Structure fx-struct-main");

  const ceiling = find(view.observations, (o) => o.observation_id === "fx-obs-ceiling-2b", "the 2B ceiling finding");
  assertIncludes(textOf(observationCard(condition(view), ceiling.title)), "Unit 2B, living room (fixture) Verified unit Structure fx-struct-main");

  view.observations = view.observations.map((o) => (o.observation_id === ROOF && o.location ? { ...o, location: { ...o.location, structure_id: null } } : o));
  assertNotIncludes(textOf(observationCard(condition(view), roof.title)), "Structure", "no structure row without a structure_id");
});

test("Condition: unknown statuses, evidence kinds and bindings get readable labels; nothing is dropped", () => {
  const view = fixtureSnapshot("full");
  const roof = find(view.observations, (o) => o.observation_id === ROOF, "the roof finding");
  view.evidence = view.evidence.map((e) => (e.evidence_id === "fx-ev-inspection-roof" ? { ...e, kind: "drone_video" as Evidence["kind"] } : e));
  view.observations = view.observations.map((o) =>
    o.observation_id === ROOF
      ? {
          ...o,
          status: "needs_more_info" as Observation["status"],
          location: o.location && { ...o.location, binding: "verified_room" as LocationRef["binding"] },
        }
      : o,
  );
  const html = condition(view);
  const text = textOf(html);
  assertNotIncludes(text, "undefined");
  assertEqual(observationCardCount(html), view.observations.length, "every observation is listed");
  assertIncludes(text, "Status not recognised (1)");
  const card = observationCard(html, roof.title);
  assertIncludes(textOf(card), "Needs more info (unrecognised status)");
  assertIncludes(textOf(card), "Drone video (unrecognised kind)");
  assertIncludes(textOf(card), bindingLabel("verified_room"));
  assertIncludes(bindingLabel("verified_room"), "treated as unverified");
  assertIncludes(card, "rc-binding--unknown", "an unrecognised binding is not drawn as a verified place");
  assertNotIncludes(card, "Request verification", "no review actions for a status this screen does not know");

  // The notice source picker uses the same fallback (it used to read "undefined: ...").
  const recoveryText = textOf(recovery(view));
  assertIncludes(recoveryText, "Drone video (unrecognised kind): Synthetic roof inspection (fixture)");
  assertNotIncludes(recoveryText, "undefined");

  // Fallbacks are safe for odd values.
  assertEqual(observationStatusLabel("constructor"), "Constructor (unrecognised status)");
  assertEqual(evidenceKindLabel(""), "Unknown kind");
  assertEqual(evidenceKindLabel("resident_photo"), "Resident photo");
});

test("Condition: a failed review stays visible; Retry only while the move still applies", () => {
  const view = fixtureSnapshot("full");
  const ceiling = find(view.observations, (o) => o.observation_id === "fx-obs-ceiling-2b", "an under-review finding");
  const roof = find(view.observations, (o) => o.observation_id === ROOF, "a verified finding");
  const runner = fakeRunner({
    [commandKey.reviewObservation(view.case.case_id, ceiling.observation_id, "dismissed")]: { pending: false, error: "Server said no." },
    [commandKey.reviewObservation(view.case.case_id, roof.observation_id, "dismissed")]: { pending: false, error: "Conflict." },
    [commandKey.reviewObservation("fx-case-2", ceiling.observation_id, "verified")]: { pending: false, error: "Other case." },
  });
  const html = condition(view, runner);
  const ceilingCard = observationCard(html, ceiling.title);
  assertIncludes(textOf(ceilingCard), "Dismiss failed. Server said no.");
  assert(buttonAttrs(ceilingCard, "Retry") !== undefined, "Retry for a move that still applies");
  const roofCard = observationCard(html, roof.title);
  assertIncludes(textOf(roofCard), "Dismiss failed. Conflict.");
  assertIncludes(textOf(roofCard), "no longer applies");
  assert(buttonAttrs(roofCard, "Retry") === undefined, "no Retry once the observation has moved on");
  assertNotIncludes(textOf(html), "Other case.", "another case's command never shows here");
});

/* ------------------------------------------------------------------ value */

test("Value: a fresh draft remains reviewable while the published assessment stays current", () => {
  const view = fixtureSnapshot("full");
  const published = find(view.assessments, a => a.assessment_id === view.current_assessment_id, "current published assessment");
  const draft = { ...published, assessment_id: "draft-review-test", status: "draft" as const, published_at: null,
    base_analysis_revision: view.case.analysis_revision, headline: "New reviewed input draft", summary: "Draft details for owner review." };
  view.assessments.push(draft);
  const runner = fakeRunner();
  const html = value(view, runner);
  assertIncludes(textOf(html), "Review draft valuation before publishing");
  assertIncludes(textOf(html), "This draft is separate from the published assessment");
  assertIncludes(textOf(html), "Draft details for owner review.");
  assertEqual(view.current_assessment_id, published.assessment_id, "review does not replace the assessment of record");
  assertEqual(runner.calls.length, 0, "opening the Value tab never publishes a draft");
});

test("Value: the insufficient variant reads 'Not enough evidence' with no $ amount in its market-value rows", () => {
  const html = value(fixtureSnapshot("insufficient"));
  const marketAt = html.indexOf('aria-label="Market value"');
  const costsAt = html.indexOf('aria-label="Costs (not a change in market value)"');
  assert(marketAt >= 0 && costsAt > marketAt, "market-value block rendered before the costs block");
  const market = textOf(html.slice(html.indexOf(">", marketAt) + 1, costsAt));
  assertEqual(market.split("Not enough evidence").length - 1, 3, "benchmark, current condition and after repair");
  assertNotIncludes(market, "$", "no dollar figure in the market-value rows");
  const costs = textOf(html.slice(html.indexOf(">", costsAt) + 1, html.indexOf("Repair lines", costsAt)));
  assertEqual(costs.split("Not enough evidence").length - 1, 2, "repair and downtime cost");
  assertNotIncludes(costs, "$");
  assertNotIncludes(textOf(html), "$0");
});

test("Value: stale wording depends on status; a published assessment is never called unpublishable", () => {
  const PUBLISHED = "Inputs changed after this assessment was published; its figures may be out of date. Run a new assessment.";

  const published = fixtureSnapshot("full");
  published.case.analysis_revision += 1;
  const publishedText = textOf(value(published));
  assertIncludes(publishedText, PUBLISHED, "published, inputs changed since");
  assertNotIncludes(publishedText, "can't be published");

  // The fixture's stale case has status "stale" but was published (published_at set).
  const stalePublished = textOf(value(fixtureSnapshot("stale")));
  assertIncludes(stalePublished, PUBLISHED, "status stale, but it was published");
  assertNotIncludes(stalePublished, "can't be published");

  const run = fixtureSnapshot("stale");
  run.assessments = run.assessments.map((a) => (a.assessment_id === run.current_assessment_id ? { ...a, published_at: null } : a));
  const runText = textOf(value(run));
  assertIncludes(runText, "kept as history; it can't be published", "a stale run that was never published");
  assertNotIncludes(runText, PUBLISHED);

  const draft = fixtureSnapshot("conditional");
  draft.current_assessment_id = "fx-asmt-draft";
  draft.case.analysis_revision += 1;
  const draftHtml = value(draft);
  assertIncludes(textOf(draftHtml), "can't be published until it's re-run", "a draft on older inputs");
  assertNotIncludes(textOf(draftHtml), PUBLISHED);
  assertEqual(buttonAttrs(draftHtml, "Publish"), undefined, "no Publish button for an out-of-date draft");

  const fresh = fixtureSnapshot("conditional");
  fresh.current_assessment_id = "fx-asmt-draft";
  const freshHtml = value(fresh);
  assert(buttonAttrs(freshHtml, "Publish") !== undefined, "an up-to-date draft can be published");
  assertNotIncludes(textOf(freshHtml), "Inputs changed", "no stale banner when the inputs are current");
});

test("Value: Run assessment is enabled when the active run's inputs are already out of date", () => {
  const blocked = fixtureSnapshot("insufficient"); // a run on analysis revision 6 is active; the case is at 6
  const blockedHtml = value(blocked);
  const blockedButton = buttonAttrs(blockedHtml, "Run assessment");
  assert(blockedButton !== undefined && isDisabled(blockedButton), "disabled while a run on the current inputs is active");
  assertIncludes(textOf(blockedHtml), "Run assessment is unavailable: a run on the current inputs (analysis revision 6) is already in progress");

  const outdated = fixtureSnapshot("insufficient");
  outdated.case.analysis_revision += 1;
  const html = value(outdated);
  const button = buttonAttrs(html, "Run assessment");
  assert(button !== undefined && !isDisabled(button), "enabled: the active run will finish stale");
  assertIncludes(textOf(html), "so it will finish stale. You can run a new assessment on the latest inputs.");

  const busy = render(<ValueTab view={outdated} busy runner={fakeRunner()} on_select_evidence={noop} />);
  const busyButton = buttonAttrs(busy, "Run assessment");
  assert(busyButton !== undefined && isDisabled(busyButton), "still disabled while busy");
});

/* ----------------------------------------------------------------- tasks */

test("TaskCard: a failed transition stays visible on the card with the form closed, with Retry and Dismiss", () => {
  const view = fixtureSnapshot("full");
  const task = taskWith(view, "approved");
  const key = commandKey.transitionTask(view.case.case_id, task.task_id, "accepted");
  const html = taskCard(view, task, fakeRunner({ [key]: { pending: false, error: "Contractor confirmation was rejected." } }));
  assertNotIncludes(html, "<form", "the transition form is closed");
  assertIncludes(textOf(html), "Record acceptance failed: Contractor confirmation was rejected.");
  assertIncludes(html, 'role="alert"');
  assert(buttonAttrs(html, "Retry") !== undefined, "Retry offered");
  assertIncludes(html, 'aria-label="Dismiss error"', "Dismiss offered");

  const pending = textOf(taskCard(view, task, fakeRunner({ [key]: { pending: true, error: null } })));
  assertIncludes(pending, "Record acceptance: waiting for the server", "a pending command is visible with the form closed");
  assertNotIncludes(pending, "Accepted", "pending never reads as accepted");

  const accepted = taskWith(view, "accepted");
  const goneKey = commandKey.transitionTask(view.case.case_id, accepted.task_id, "approved");
  const goneHtml = taskCard(view, accepted, fakeRunner({ [goneKey]: { pending: false, error: "Conflict." } }));
  assertIncludes(textOf(goneHtml), "Approve failed: Conflict.");
  assertIncludes(textOf(goneHtml), "no longer applies");
  assertEqual(buttonAttrs(goneHtml, "Retry"), undefined, "no Retry for a move the task no longer allows");

  const otherCase = commandKey.transitionTask("fx-case-2", task.task_id, "accepted");
  assertNotIncludes(textOf(taskCard(view, task, fakeRunner({ [otherCase]: { pending: false, error: "Other case." } }))), "Other case.");
});

test("TaskCard: schedule wording on edge data", () => {
  const view = fixtureSnapshot("full");

  const cancelled = scheduleOf(view, { ...taskWith(view, "cancelled"), confirmed_schedule: "2024-07-16T13:00:00Z" });
  assertIncludes(cancelled.text, "No current schedule: task cancelled.", "a cancelled task never presents a schedule as current");
  assertIncludes(cancelled.html, "<s>16 Jul 2024, 13:00 UTC</s>", "the old date is struck through");
  assertEqual(scheduleOf(view, { ...taskWith(view, "cancelled"), confirmed_schedule: null }).text, "Schedule not confirmed: task cancelled");

  for (const status of ["proposed", "approved", "accepted", "in_progress", "completion_submitted", "verified"] as const) {
    for (const blank of ["", "   "]) {
      const s = scheduleOf(view, { ...taskWith(view, status), confirmed_schedule: blank });
      assertEqual(s.text, "Schedule not confirmed", `${status}, schedule ${JSON.stringify(blank)}`);
    }
    const dated = scheduleOf(view, { ...taskWith(view, status), confirmed_schedule: "2024-07-20" });
    if (status === "proposed" || status === "approved") {
      assertIncludes(dated.text, "Schedule not confirmed.", `${status}: a date on file is not confirmed`);
      assertIncludes(dated.text, "tentative date is on file", status);
      assertIncludes(dated.text, "20 Jul 2024", status);
      assertNotIncludes(dated.text, "booked", status);
    } else {
      assertEqual(dated.text, "20 Jul 2024", `${status}: accepted or later shows the date as confirmed`);
    }
  }
  assertEqual(scheduleOf(view, { ...taskWith(view, "cancelled"), confirmed_schedule: " " }).text, "Schedule not confirmed: task cancelled");

  const unknown = scheduleOf(view, { ...taskWith(view, "accepted"), status: "on_hold" as TaskStatus, confirmed_schedule: "2024-07-20" });
  assertIncludes(unknown.text, "Schedule not confirmed.", "a status this screen does not know never shows a schedule as confirmed");
});

test("TaskCard: one 'Show on site' action focuses the location and selects the first cited evidence", () => {
  const view = fixtureSnapshot("full");
  const task = find(view.tasks, (t) => t.task_id === "fx-task-membrane", "the membrane task");
  const target = taskSiteTarget(view, task);
  assertEqual(target.location?.location_id, "fx-loc-roof-east");
  assertEqual(target.evidence_id, "fx-ev-inspection-roof", "first cited evidence");
  assertEqual(taskSiteTarget(view, { ...task, evidence_ids: ["fx-ev-missing", "fx-ev-aerial-after"] }).evidence_id, "fx-ev-aerial-after", "skips ids not in the snapshot");

  const button = buttonAttrs(taskCard(view, task, fakeRunner({}, true)), "Show on site");
  assert(button !== undefined && !isDisabled(button), "always available, even while a command is pending");
  assert(buttonAttrs(taskCard(view, { ...task, location: null }), "Show evidence") !== undefined, "evidence only");
  const none = taskCard(view, { ...task, location: null, evidence_ids: [] });
  assert(buttonAttrs(none, "Show on site") === undefined && buttonAttrs(none, "Show evidence") === undefined, "nothing to show, no button");
});

/* --------------------------------------------------------------- recovery */

test("Recovery: invitation copy never promises this panel will show a link", () => {
  const text = textOf(recovery(fixtureSnapshot("full")));
  assertIncludes(text, "The app around this panel shows that link or QR code");
  assertNotIncludes(text.toLowerCase(), "link appears");
  assertNotIncludes(text.toLowerCase(), "appears once");
  assertNotIncludes(text, "Invitation created", "nothing is claimed before the server confirms");

  const row = (created: boolean, status: { pending: boolean; error: string | null } = { pending: false, error: null }) =>
    textOf(
      render(
        <ul>
          <InvitationRow household_id="fx-hh-2b" unit_label="2B" status={status} created={created} disabled={false} on_create={noop} on_retry={noop} on_dismiss={noop} />
        </ul>,
      ),
    );
  assertEqual(INVITATION_CREATED_NOTE, "Invitation created (server confirmed). The app delivers the link, outside this panel.");
  assertIncludes(row(true), INVITATION_CREATED_NOTE, "per-household note once the server confirmed");
  assertNotIncludes(row(false), "Invitation created");
  assertNotIncludes(row(true, { pending: true, error: null }), "Invitation created", "not shown beside a new attempt in flight");
  const failed = row(true, { pending: false, error: "Server unavailable." });
  assertIncludes(failed, "Could not create the invitation for unit 2B. Server unavailable.");
  assertNotIncludes(failed, "Invitation created", "not shown beside a failure");
});

test("Recovery: unknown task and support statuses are listed with readable labels", () => {
  const view = fixtureSnapshot("full");
  view.tasks = [...view.tasks, { ...taskWith(view, "accepted"), task_id: "fx-task-hold", title: "Held task", status: "on_hold" as TaskStatus }];
  view.support_requests = view.support_requests.map((r, i) =>
    i === 0 ? { ...r, status: "escalated" as SupportReceipt["status"], category: "legal" as SupportReceipt["category"] } : r,
  );
  const html = recovery(view);
  const text = textOf(html);
  assertNotIncludes(text, "undefined");
  assertIncludes(text, "Status not recognised");
  assertIncludes(text, "Held task");
  assertIncludes(text, "On hold (unrecognised status)");
  assertIncludes(text, "Escalated (unrecognised status)");
  assertIncludes(text, "Legal (unrecognised category)");
  const held = /<article class="rr-task rr-task--on_hold"[\s\S]*?<\/article>/.exec(html)?.[0];
  assert(held, "the unknown-status task gets a full card");
  for (const label of ["Approve", "Record acceptance", "Mark in progress", "Cancel task"]) {
    assertEqual(buttonAttrs(held, label), undefined, `no "${label}" on an unknown status`);
  }
});

test("Command keys carry the case: another case's failed notice or run never shows here", () => {
  assertEqual(commandKey.publishNotice("fx-case-1"), "notice:publish:fx-case-1");
  assertEqual(commandKey.startAssessment("fx-case-1"), "assessment:start:fx-case-1");
  assert(commandKey.publishNotice("fx-case-1") !== commandKey.publishNotice("fx-case-2"), "notice keys differ per case");
  assert(
    commandKey.transitionTask("a:b", "c", "accepted") !== commandKey.transitionTask("a", "b:c", "accepted"),
    "ids that contain ':' stay unambiguous",
  );

  const caseB = fixtureSnapshot("full", "fx-case-2");
  const fromA = fakeRunner({
    [commandKey.publishNotice("fx-case-1")]: { pending: false, error: "Case A notice failed." },
    [commandKey.startAssessment("fx-case-1")]: { pending: false, error: "Case A run failed." },
    [commandKey.createInvitation("fx-case-1", "fx-hh-2b")]: { pending: false, error: "Case A invite failed." },
  });
  assertNotIncludes(textOf(recovery(caseB, fromA)), "Case A");
  assertNotIncludes(textOf(value(caseB, fromA)), "Case A");

  const own = fakeRunner({
    [commandKey.publishNotice("fx-case-2")]: { pending: false, error: "Case B notice failed." },
    [commandKey.startAssessment("fx-case-2")]: { pending: false, error: "Case B run failed." },
    [commandKey.createInvitation("fx-case-2", "fx-hh-2b")]: { pending: false, error: "Case B invite failed." },
  });
  const ownRecovery = textOf(recovery(caseB, own));
  assertIncludes(ownRecovery, "Case B notice failed.");
  assertIncludes(ownRecovery, "Case B invite failed.");
  assertIncludes(textOf(value(caseB, own)), "Case B run failed.");
});

/* ------------------------------------------------------------ comparables */

test("Comparables: a null price explains itself from price_status and never shows $0", () => {
  assertEqual(comparablePrice({ price_usd: null, price_status: "Price not disclosed" }).text, "Price not disclosed");
  assertEqual(comparablePrice({ price_usd: null, price_status: "not_disclosed" }).text, "Price not disclosed");
  assertEqual(comparablePrice({ price_usd: null, price_status: "Pending deed recording" }).text, "No price on record (status: Pending deed recording)");
  assertEqual(comparablePrice({ price_usd: null, price_status: "Disclosed price" }).text, "No price on record (status: Disclosed price)");
  assertEqual(comparablePrice({ price_usd: null, price_status: "  " }).text, "No price on record (no status given)");
  assertEqual(comparablePrice({ price_usd: Number.NaN, price_status: "Disclosed price" }).missing, true, "a non-finite price is not a figure");
  assertEqual(comparablePrice({ price_usd: 16_750_000, price_status: "Disclosed price" }), { text: "$16,750,000", missing: false });

  const view = fixtureSnapshot("full");
  const comps = view.assessments.find((a) => a.assessment_id === view.current_assessment_id)?.valuation?.comparables ?? [];
  const base = find(comps, (c) => c.price_usd === null, "a comparable with a null price");
  const list: Comparable[] = [
    { ...base, comp_id: "fx-comp-nd" },
    { ...base, comp_id: "fx-comp-pending", label: "Pending comp", price_status: "Pending deed recording" },
    { ...base, comp_id: "fx-comp-blank", label: "Blank comp", price_status: "" },
  ];
  const text = textOf(render(<ComparablesList view={view} comparables={list} on_select_evidence={noop} />));
  assertIncludes(text, "Price not disclosed");
  assertIncludes(text, "No price on record (status: Pending deed recording)");
  assertIncludes(text, "No price on record (no status given)");
  assertNotIncludes(text, "$", "no dollar figure for any null price");
  assertNotIncludes(text, "Price status: Pending deed recording", "the status is not repeated");
});

/* --------------------------------------------------------------- timeline */

test("Timeline: duplicate event ids render once, and an earlier publication is marked superseded", () => {
  const ev = (event_id: number, type: string, case_revision: number, entity_id: string | null, public_summary: string | null = null): CaseEvent => ({
    event_id,
    case_id: "fx-case-1",
    case_revision,
    analysis_revision: 1,
    type,
    at: new Date(Date.UTC(2024, 6, 8, event_id)).toISOString(),
    entity_id,
    public_summary,
  });
  const events = [
    ev(1, "assessment.published", 1, "fx-asmt-a"),
    ev(2, "drone.flight_logged", 2, null, "First copy"),
    ev(2, "drone.flight_logged", 2, null, "Second copy"),
    ev(3, "assessment.published", 3, "fx-asmt-b"),
    ev(1, "assessment.published", 1, "fx-asmt-a"),
  ];
  const html = render(<EventTimeline events={events} case_revision={3} analysis_revision={1} />);
  const items = [...html.matchAll(/<li class="rt-event[^"]*">[\s\S]*?<\/li>/g)].map((m) => m[0]);
  assertEqual(items.length, 3, "three unique events");
  const text = textOf(html);
  assertIncludes(text, "First copy", "the first delivery of a duplicate is kept");
  assertNotIncludes(text, "Second copy");
  assertIncludes(text, "Drone flight logged", "an unknown type still reads as words");
  assertEqual(text.split(SUPERSEDED_PUBLICATION_LABEL).length - 1, 1, "one superseded publication");
  assertIncludes(items[0], "fx-asmt-b");
  assertNotIncludes(items[0], SUPERSEDED_PUBLICATION_LABEL, "the latest publication stands");
  assertIncludes(items[0], "Current revision");
  assertIncludes(items[2], "fx-asmt-a");
  assertIncludes(items[2], SUPERSEDED_PUBLICATION_LABEL, "the earlier publication is superseded");

  const single = textOf(render(<EventTimeline events={[ev(5, "assessment.published", 5, "fx-asmt-c")]} case_revision={5} analysis_revision={1} />));
  assertNotIncludes(single, SUPERSEDED_PUBLICATION_LABEL, "a lone publication is not superseded");
});
