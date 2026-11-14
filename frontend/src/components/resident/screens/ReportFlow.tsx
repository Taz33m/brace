/**
 * Report a problem: form -> review -> send.
 *
 * The draft lives in the shell (`draft` / `set_draft`) so leaving and coming back keeps it. Async
 * photo work always updates by `local_id` through the updater form, never a captured draft.
 *
 * Sending follows the contract: upload every photo first (one idempotency key per photo, reused on
 * retry), then submit the report with one key per intended payload (same payload => same key, so a
 * lost response retried returns the original receipt). Nothing is ever sent in the background.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { LocationRef, ReportInput, ResidentHome } from "../contract";
import type { ObservedChoice, PhotoItem, ReportDraft, ReportFlowProps } from "./types";
import { emptyReportDraft } from "./types";
import { ActionBar, Choice, Message, ScreenHead } from "../ui";
import {
  IconAlert,
  IconCamera,
  IconCheck,
  IconClose,
  IconImage,
  IconMic,
  IconOther,
  IconPin,
  IconPower,
  IconRetry,
  IconRoof,
  IconSmoke,
  IconStop,
  IconWater,
} from "../icons";
import { REPORT_CATEGORIES, categoryLabel } from "../lib/status";
import { newIdempotencyKey } from "../lib/idempotency";
import { toResidentError } from "../lib/errors";
import { formatWhen, localInputToIso, toLocalInput } from "../lib/time";
import { preparePhoto } from "../lib/photos";
import { useDictation } from "../lib/useDictation";
import { useFlowLifetime } from "../lib/useFlowLifetime";

const MAX_PHOTOS = 6;

const CATEGORY_ICONS: Record<ReportInput["category"], ReactNode> = {
  water: <IconWater />,
  roof: <IconRoof />,
  smoke_or_fire: <IconSmoke />,
  power_or_access: <IconPower />,
  other: <IconOther />,
};

const WHEN_CHOICES: { value: ObservedChoice; label: string }[] = [
  { value: "now", label: "Just now" },
  { value: "earlier", label: "Earlier" },
  { value: "unknown", label: "Not sure" },
];

type SectionKey = "category" | "where" | "text" | "when" | "photos";
const SECTION_ORDER: SectionKey[] = ["category", "where", "text", "when", "photos"];
type FormErrors = Partial<Record<SectionKey, string>>;

type Phase =
  | { kind: "idle" }
  | { kind: "uploading"; index: number; total: number }
  | { kind: "submitting" }
  | { kind: "upload_failed"; local_ids: string[]; message: string; retryable: boolean }
  | { kind: "error"; message: string; retryable: boolean }
  | { kind: "settled"; message: string };

/** Only rooms in the resident's own verified unit scan can be picked as an exact room. */
function verifiedRooms(home: ResidentHome): LocationRef[] {
  return home.selectable_locations.filter((l) => l.binding === "verified_unit");
}

function validate(d: ReportDraft, rooms: LocationRef[]): FormErrors {
  const e: FormErrors = {};
  if (!d.category) e.category = "Choose what kind of problem it is.";
  const roomOk = !!d.selected_location_id && rooms.some((r) => r.location_id === d.selected_location_id);
  if (!roomOk && !d.location_description.trim()) {
    e.where = rooms.length ? "Tap a room, or describe where it is." : "Describe where it is.";
  }
  if (!d.text.trim()) e.text = "Say what happened. A few words is enough.";
  if (!d.observed_choice) e.when = "Choose when you noticed it. Not sure is fine.";
  else if (d.observed_choice === "earlier") {
    const iso = localInputToIso(d.observed_local);
    if (!iso) e.when = "Enter roughly when, or choose Not sure.";
    else if (new Date(iso).getTime() > Date.now() + 60_000) e.when = "That time hasn't happened yet. Check the date and time.";
  }
  if (d.photos.some((p) => p.state === "preparing")) e.photos = "Wait a moment. Your photos are still being prepared.";
  return e;
}

function whereText(room: LocationRef | null, description: string | null): string {
  const desc = description?.trim() || "";
  if (room && desc) return `${room.label} — ${desc}`;
  return room?.label || desc || "Not given";
}

function joinText(current: string, spoken: string): string {
  const add = spoken.trim();
  if (!add) return current;
  if (!current.trim()) return add;
  return `${current.replace(/\s+$/, "")} ${add}`;
}

function listNumbers(ns: number[]): string {
  if (ns.length <= 1) return String(ns[0] ?? "");
  return `${ns.slice(0, -1).join(", ")} and ${ns[ns.length - 1]}`;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export function ReportFlow(props: ReportFlowProps) {
  const { api, home, connection, draft, set_draft, on_submitted, on_expired, on_busy } = props;
  const onBusyRef = useRef(on_busy);
  onBusyRef.current = on_busy;
  // Leaving the screen ends any busy state this flow reported.
  useEffect(() => () => onBusyRef.current?.(false), []);

  const [step, setStep] = useState<"form" | "review">("form");
  const [attempted, setAttempted] = useState(false);
  const [announce, setAnnounce] = useState("");
  const [formNotice, setFormNotice] = useState<string | null>(null);
  const [photoNotice, setPhotoNotice] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  const mainRef = useRef<HTMLElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const libraryRef = useRef<HTMLInputElement>(null);
  const sendStatusRef = useRef<HTMLDivElement>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const keeperRef = useRef(props.keeper);
  /** "Just now" is stamped once per intended send, so a retry carries the same payload (and key). */
  const nowStampRef = props.now_stamp;
  /** Photos removed while still preparing; their late result is discarded. */
  const removedRef = useRef(new Set<string>());
  const sendingRef = useRef(false);
  const settledRef = useRef(false);
  const lifetimeRef = useFlowLifetime();

  const rooms = useMemo(() => verifiedRooms(home), [home]);
  const errors = validate(draft, rooms);
  const shown: FormErrors = attempted ? errors : {};
  const offline = connection === "offline";
  const sending = phase.kind === "uploading" || phase.kind === "submitting";
  const selectedRoom = rooms.find((r) => r.location_id === draft.selected_location_id) ?? null;
  const unitLabel = rooms[0]?.unit_label ?? home.unit_label;

  // Moving between form and review is a screen change: top of page, focus the new heading.
  const stepMounted = useRef(false);
  useEffect(() => {
    if (!stepMounted.current) {
      stepMounted.current = true;
      return;
    }
    window.scrollTo({ top: 0 });
    mainRef.current?.querySelector<HTMLElement>("[data-screen-title]")?.focus({ preventScroll: true });
  }, [step]);

  // Bring a send failure into view; it renders just above the action bar.
  useEffect(() => {
    if (phase.kind === "upload_failed" || phase.kind === "error") {
      sendStatusRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "end" });
    }
  }, [phase.kind]);

  const update = useCallback((patch: Partial<ReportDraft>) => set_draft((d) => ({ ...d, ...patch })), [set_draft]);

  const patchPhoto = useCallback(
    (local_id: string, patch: Partial<PhotoItem>) =>
      set_draft((d) =>
        d.photos.some((p) => p.local_id === local_id)
          ? { ...d, photos: d.photos.map((p) => (p.local_id === local_id ? { ...p, ...patch } : p)) }
          : d,
      ),
    [set_draft],
  );

  const onDictated = useCallback((t: string) => set_draft((d) => ({ ...d, text: joinText(d.text, t) })), [set_draft]);
  const dictation = useDictation(onDictated);

  // ---------------- photos ----------------

  function addFiles(input: HTMLInputElement) {
    const files = input.files ? Array.from(input.files) : [];
    input.value = ""; // iOS keeps one capture per session; reset so the next pick fires again
    if (!files.length) return;
    const room = Math.max(0, MAX_PHOTOS - draftRef.current.photos.length);
    const take = files.slice(0, room);
    const dropped = files.length - take.length;
    setPhotoNotice(
      dropped > 0
        ? `A report can have up to ${MAX_PHOTOS} photos. ${dropped === 1 ? "1 photo wasn't" : `${dropped} photos weren't`} added.`
        : null,
    );
    if (!take.length) return;
    const items: PhotoItem[] = take.map(() => ({
      local_id: newIdempotencyKey(),
      file: null,
      preview_url: null,
      state: "preparing",
      idempotency_key: newIdempotencyKey(),
      upload_id: null,
      error: null,
    }));
    set_draft((d) => ({ ...d, photos: [...d.photos, ...items] }));
    items.forEach((item, i) => {
      preparePhoto(take[i]).then(
        (prepared) => {
          if (removedRef.current.has(item.local_id)) {
            URL.revokeObjectURL(prepared.preview_url);
            return;
          }
          patchPhoto(item.local_id, { file: prepared.file, preview_url: prepared.preview_url, state: "ready", error: null });
        },
        (e: unknown) => {
          if (removedRef.current.has(item.local_id)) return;
          const message = e instanceof Error && e.message ? e.message : "This photo couldn't be added. Try a different one.";
          patchPhoto(item.local_id, { state: "failed", error: message });
        },
      );
    });
  }

  function removePhoto(item: PhotoItem) {
    if (item.state === "preparing") removedRef.current.add(item.local_id);
    if (item.preview_url) URL.revokeObjectURL(item.preview_url);
    set_draft((d) => ({ ...d, photos: d.photos.filter((p) => p.local_id !== item.local_id) }));
    setPhotoNotice(null);
    // The tile (and its button) is gone; keep focus in the photos section.
    // After the re-render, so the add button is enabled again if the grid was full.
    requestAnimationFrame(() =>
      libraryRef.current?.parentElement?.querySelector<HTMLButtonElement>("[data-add-photo]")?.focus(),
    );
  }

  // ---------------- form -> review ----------------

  function setObserved(choice: ObservedChoice) {
    if (choice !== "now") nowStampRef.current = null;
    update({ observed_choice: choice });
  }

  function goReview() {
    if (dictation.listening) dictation.stop();
    const missing = SECTION_ORDER.filter((k) => errors[k]);
    if (missing.length) {
      setAttempted(true);
      const first = missing[0];
      setAnnounce(
        `${missing.length === 1 ? "One thing needs" : `${missing.length} things need`} filling in before you review. ${errors[first]}`,
      );
      const section = document.getElementById(`rr-sec-${first}`);
      const target =
        section?.querySelector<HTMLElement>("[data-focus-first]") ??
        section?.querySelector<HTMLElement>("button:not(:disabled), input:not([tabindex='-1']), textarea");
      section?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
      target?.focus({ preventScroll: true });
      return;
    }
    setAnnounce("");
    setFormNotice(null);
    setPhase({ kind: "idle" });
    setStep("review");
  }

  function backToForm() {
    if (sending) return;
    setPhase({ kind: "idle" });
    setStep("form");
  }

  // ---------------- send ----------------

  async function send(skip?: ReadonlySet<string>) {
    const lifetime = lifetimeRef.current;
    if (!lifetime || lifetime.aborted || sendingRef.current || settledRef.current || offline) return;
    const current = draftRef.current;
    if (Object.keys(validate(current, rooms)).length) {
      setAttempted(true);
      setStep("form");
      return;
    }
    sendingRef.current = true;
    onBusyRef.current?.(true);
    try {
      let photos = current.photos.filter((p) => p.file);
      if (skip?.size) {
        current.photos.forEach((p) => skip.has(p.local_id) && p.preview_url && URL.revokeObjectURL(p.preview_url));
        set_draft((d) => ({ ...d, photos: d.photos.filter((p) => !skip.has(p.local_id)) }));
        photos = photos.filter((p) => !skip.has(p.local_id));
      }

      // 1. Uploads first. Each photo keeps its own key, so a retry never stores it twice.
      const uploadIds = new Map<string, string>();
      photos.forEach((p) => p.state === "uploaded" && p.upload_id && uploadIds.set(p.local_id, p.upload_id));
      const pending = photos.filter((p) => !uploadIds.has(p.local_id));
      const failed: { local_id: string; n: number; message: string; retryable: boolean }[] = [];
      for (let i = 0; i < pending.length; i++) {
        if (lifetime.aborted) return;
        const p = pending[i];
        setPhase({ kind: "uploading", index: i + 1, total: pending.length });
        patchPhoto(p.local_id, { state: "uploading", error: null });
        try {
          const up = await api.upload_image(p.file as File, p.idempotency_key);
          if (lifetime.aborted) return;
          uploadIds.set(p.local_id, up.upload_id);
          patchPhoto(p.local_id, { state: "uploaded", upload_id: up.upload_id, error: null });
        } catch (e) {
          if (lifetime.aborted) return;
          const err = toResidentError(e);
          if (err.kind === "expired") {
            setPhase({ kind: "idle" });
            on_expired();
            return;
          }
          patchPhoto(p.local_id, { state: "failed", error: err.message });
          failed.push({ local_id: p.local_id, n: photos.indexOf(p) + 1, message: err.message, retryable: err.retryable });
          if (err.kind === "network") break; // no signal: the rest would fail the same way
        }
      }
      if (failed.length) {
        const ns = failed.map((f) => f.n);
        const which = ns.length === 1 ? `Photo ${ns[0]} didn't upload.` : `Photos ${listNumbers(ns)} didn't upload.`;
        setPhase({
          kind: "upload_failed",
          local_ids: failed.map((f) => f.local_id),
          message: `${which} ${failed[0].message}`,
          retryable: failed.some((f) => f.retryable),
        });
        return;
      }

      // 2. The report, with the returned upload IDs.
      if (lifetime.aborted) return;
      let observed_at: string | null = null;
      if (current.observed_choice === "now") {
        nowStampRef.current ??= new Date().toISOString();
        observed_at = nowStampRef.current;
      } else if (current.observed_choice === "earlier") {
        observed_at = localInputToIso(current.observed_local);
      }
      const room = rooms.find((r) => r.location_id === current.selected_location_id) ?? null;
      const input: ReportInput = {
        category: current.category as ReportInput["category"],
        text: current.text.trim(),
        selected_location_id: room?.location_id ?? null,
        location_description: current.location_description.trim() || null,
        observed_at,
        upload_ids: photos.map((p) => uploadIds.get(p.local_id)).filter((id): id is string => !!id),
      };
      setPhase({ kind: "submitting" });
      const key = keeperRef.current.keyFor(input);
      try {
        const receipt = await api.submit_report(input, key);
        if (lifetime.aborted) return;
        keeperRef.current.succeeded();
        nowStampRef.current = null;
        on_submitted(receipt);
      } catch (e) {
        if (lifetime.aborted) return;
        const err = toResidentError(e);
        if (err.kind === "expired") {
          setPhase({ kind: "idle" });
          on_expired();
        } else if (err.code === "idempotency_conflict") {
          // An earlier send whose reply was lost did arrive; the server refused a second, edited copy.
          settledRef.current = true;
          keeperRef.current.succeeded();
          nowStampRef.current = null;
          current.photos.forEach((photo) => photo.preview_url && URL.revokeObjectURL(photo.preview_url));
          set_draft(emptyReportDraft);
          setPhase({
            kind: "settled",
            message: "Your earlier send already reached the property team, so this version wasn't sent again. Check My updates to see it.",
          });
        } else if (err.kind === "invalid") {
          keeperRef.current.rejected();
          if (err.code === "location_unavailable" || err.code === "location_not_selectable") update({ selected_location_id: null });
          if (err.code === "upload_unavailable") {
            // Those uploads can't be attached again (e.g. already used): upload the photos afresh.
            set_draft((d) => ({
              ...d,
              photos: d.photos.map((p) =>
                p.upload_id && p.file
                  ? { ...p, state: "ready", upload_id: null, idempotency_key: newIdempotencyKey(), error: null }
                  : p,
              ),
            }));
          }
          setPhase({ kind: "idle" });
          setFormNotice(err.message);
          setAttempted(true);
          setStep("form");
        } else {
          // No answer from the server: it may have stored the report. Keep the key until we know.
          if (err.kind === "network" || err.kind === "unknown" || err.kind === "unavailable") keeperRef.current.markUncertain();
          setPhase({ kind: "error", message: err.message, retryable: err.retryable });
        }
      }
    } finally {
      sendingRef.current = false;
      onBusyRef.current?.(false);
    }
  }

  if (phase.kind === "settled") {
    return (
      <>
        <main className="r-main has-actionbar" role="status">
          <ScreenHead title="Earlier report received" lede={phase.message} />
          <p>Return home to open My updates, or start a new report for another problem.</p>
        </main>
        <ActionBar>
          <button type="button" className="r-btn" onClick={props.on_cancel}>Back to home</button>
          <button type="button" className="r-btn primary" onClick={() => {
            settledRef.current = false;
            setAttempted(false);
            setFormNotice(null);
            setPhotoNotice(null);
            setPhase({ kind: "idle" });
            setStep("form");
          }}>Start a new report</button>
        </ActionBar>
      </>
    );
  }

  // ---------------- review step ----------------

  if (step === "review") {
    const sendable = draft.photos.filter((p) => p.file);
    const unusable = draft.photos.length - sendable.length;
    const failedCount = phase.kind === "upload_failed" ? phase.local_ids.length : 0;
    const whenText =
      draft.observed_choice === "now"
        ? "Just now"
        : draft.observed_choice === "earlier"
          ? formatWhen(localInputToIso(draft.observed_local))
          : "Not sure";
    const sendLabel =
      phase.kind === "uploading"
        ? `Sending photo ${phase.index} of ${phase.total}…`
        : phase.kind === "submitting"
          ? "Sending…"
          : "Send report";

    return (
      <>
        <main ref={mainRef} className="r-main has-actionbar">
          <ScreenHead title="Check and send" lede="Make sure this is right. Nothing is sent until you tap Send report." />

          <section className="rr-dest" aria-label="Where this report goes">
            <span className="rr-dest-icon"><IconPin size={26} /></span>
            <div className="rr-dest-text">
              <p>This report goes to <strong>{home.property_name}</strong></p>
              {home.unit_confirmed && home.unit_label ? (
                <p className="rr-dest-unit">Unit {home.unit_label}</p>
              ) : (
                <p className="rr-dest-unit unconfirmed">
                  {home.unit_label ? `Unit ${home.unit_label} — not confirmed` : "Unit not confirmed"}
                </p>
              )}
              <p className="r-meta">{home.address}</p>
              {!home.unit_confirmed ? (
                <p className="r-meta">The property team will confirm which home this is.</p>
              ) : null}
            </div>
          </section>

          <dl className="r-list rr-facts">
            <div className="r-row">
              <dt className="r-meta">Problem</dt>
              <dd>{draft.category ? categoryLabel(draft.category) : "Not chosen"}</dd>
            </div>
            <div className="r-row">
              <dt className="r-meta">Where</dt>
              <dd>{whereText(selectedRoom, draft.location_description)}</dd>
            </div>
            <div className="r-row">
              <dt className="r-meta">What happened</dt>
              <dd className="rr-text">{draft.text.trim()}</dd>
            </div>
            <div className="r-row">
              <dt className="r-meta">When you noticed it</dt>
              <dd>{whenText}</dd>
            </div>
            <div className="r-row">
              <dt className="r-meta">Photos</dt>
              <dd className="rr-photos-dd">
                {sendable.length ? (
                  <PhotoGrid photos={sendable} label="Photos to send" />
                ) : (
                  <span>No photos</span>
                )}
                {unusable > 0 ? (
                  <span className="r-meta">
                    {unusable === 1 ? "1 photo couldn't be added and won't be sent." : `${unusable} photos couldn't be added and won't be sent.`}
                  </span>
                ) : null}
              </dd>
            </div>
          </dl>

          <div ref={sendStatusRef} className="rr-send-status">
            {phase.kind === "upload_failed" ? (
              <Message
                tone="bad"
                action={
                  <div className="rr-msg-actions">
                    {phase.retryable ? (
                      <button type="button" className="r-btn" onClick={() => void send()} disabled={offline}>
                        <IconRetry size={20} /> Try again
                      </button>
                    ) : null}
                    <button type="button" className="r-btn" onClick={() => void send(new Set(phase.local_ids))} disabled={offline}>
                      {failedCount === 1 ? "Send without that photo" : "Send without those photos"}
                    </button>
                  </div>
                }
              >
                {phase.message} Your report hasn't been sent yet. Everything you entered is still here.
              </Message>
            ) : null}
            {phase.kind === "error" ? (
              <Message
                tone="bad"
                action={
                  phase.retryable ? (
                    <div className="rr-msg-actions">
                      <button type="button" className="r-btn" onClick={() => void send()} disabled={offline}>
                        <IconRetry size={20} /> Try again
                      </button>
                    </div>
                  ) : undefined
                }
              >
                {phase.message}
                {phase.retryable ? null : " Tap Edit to change your report, or go back to home."}
              </Message>
            ) : null}
            {offline ? (
              <div id="rr-offline-note">
                <Message tone="warn">
                  You're offline. Your report is ready and still here. Tap Send report when you have signal. Nothing is sent automatically.
                </Message>
              </div>
            ) : null}
          </div>
        </main>
        <ActionBar>
          <button type="button" className="r-btn secondary-narrow" onClick={backToForm} disabled={sending}>
            Edit
          </button>
          <button
            type="button"
            className="r-btn primary"
            onClick={() => void send()}
            disabled={sending || offline}
            aria-busy={sending}
            aria-describedby={offline ? "rr-offline-note" : undefined}
          >
            {sendLabel}
          </button>
        </ActionBar>
      </>
    );
  }

  // ---------------- form step ----------------

  const photoCount = draft.photos.length;
  const full = photoCount >= MAX_PHOTOS;
  const prepFailures = draft.photos
    .map((p, i) => ({ p, n: i + 1 }))
    .filter(({ p }) => p.state === "failed" && p.error);

  return (
    <>
      <main ref={mainRef} className="r-main has-actionbar">
        <ScreenHead
          title="Report a problem"
          lede="Tell the property team what's wrong. You'll check everything before it's sent."
        />
        {formNotice ? <Message tone="bad">{formNotice}</Message> : null}
        <p className="r-sr" role="status" aria-live="polite">{announce}</p>

        <section id="rr-sec-category" className="r-section rr-sec" aria-labelledby="rr-h-category">
          <h2 id="rr-h-category" className="r-title-sm">What's the problem?</h2>
          <div
            role="radiogroup"
            aria-labelledby="rr-h-category"
            aria-required="true"
            aria-describedby={shown.category ? "rr-err-category" : undefined}
            className="r-choices"
          >
            {REPORT_CATEGORIES.map((c) => {
              const on = draft.category === c.value;
              return (
                <Choice
                  key={c.value}
                  role="radio"
                  icon={CATEGORY_ICONS[c.value]}
                  title={c.label}
                  sub={c.hint}
                  selected={on}
                  trailing={on ? <IconCheck size={22} /> : undefined}
                  onClick={() => update({ category: c.value })}
                />
              );
            })}
          </div>
          {shown.category ? <FieldError id="rr-err-category">{shown.category}</FieldError> : null}
        </section>

        <section id="rr-sec-where" className="r-section rr-sec" aria-labelledby="rr-h-where">
          <h2 id="rr-h-where" className="r-title-sm">Where is it?</h2>
          {rooms.length > 0 ? (
            <>
              <p className="r-hint" id="rr-rooms-hint">
                {unitLabel ? `Rooms in Unit ${unitLabel}.` : "Rooms in your unit."} Tap one, or describe the spot below.
              </p>
              <div
                role="radiogroup"
                aria-labelledby="rr-h-where"
                aria-describedby={shown.where ? "rr-rooms-hint rr-err-where" : "rr-rooms-hint"}
                className="rr-chips"
              >
                {rooms.map((r) => {
                  const on = draft.selected_location_id === r.location_id;
                  return (
                    <button
                      key={r.location_id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      className="rr-chip"
                      onClick={() => update({ selected_location_id: on ? null : r.location_id })}
                    >
                      {on ? <IconCheck size={18} /> : null}
                      {r.label}
                    </button>
                  );
                })}
              </div>
            </>
          ) : null}
          <div className="r-field">
            <label htmlFor="rr-where-text" className="r-label">
              {rooms.length ? "Somewhere else, or more detail" : "Describe where it is"}
            </label>
            {rooms.length === 0 ? (
              <p className="r-hint" id="rr-where-hint">
                Say where in the building it is, in your own words.
              </p>
            ) : null}
            <input
              id="rr-where-text"
              className="r-input"
              type="text"
              autoComplete="off"
              enterKeyHint="next"
              placeholder="Lobby, near the mail room"
              value={draft.location_description}
              maxLength={500}
              onChange={(e) => update({ location_description: e.target.value })}
              aria-invalid={shown.where ? true : undefined}
              aria-describedby={
                [rooms.length === 0 ? "rr-where-hint" : "", shown.where ? "rr-err-where" : ""].filter(Boolean).join(" ") || undefined
              }
            />
          </div>
          {shown.where ? <FieldError id="rr-err-where">{shown.where}</FieldError> : null}
        </section>

        <section id="rr-sec-text" className="r-section rr-sec" aria-labelledby="rr-h-text">
          <h2 id="rr-h-text" className="r-title-sm">
            <label htmlFor="rr-text">What happened?</label>
          </h2>
          <textarea
            id="rr-text"
            className="r-textarea"
            value={draft.text}
            maxLength={4000}
            onChange={(e) => update({ text: e.target.value })}
            placeholder="Water is coming through the ceiling by the window."
            aria-invalid={shown.text ? true : undefined}
            aria-describedby={shown.text ? "rr-err-text" : undefined}
          />
          {dictation.supported ? (
            <div className="rr-mic">
              <button
                type="button"
                className="r-btn"
                aria-pressed={dictation.listening}
                onClick={dictation.listening ? dictation.stop : dictation.start}
              >
                {dictation.listening ? <IconStop size={20} /> : <IconMic size={20} />}
                {dictation.listening ? "Stop listening" : "Speak instead"}
              </button>
              {dictation.listening ? (
                <span className="r-hint rr-listening" role="status">
                  Listening. What you say is added to the box.
                </span>
              ) : null}
            </div>
          ) : null}
          {dictation.error ? <FieldError id="rr-err-dictation">{dictation.error} You can still type.</FieldError> : null}
          {shown.text ? <FieldError id="rr-err-text">{shown.text}</FieldError> : null}
        </section>

        <section id="rr-sec-when" className="r-section rr-sec" aria-labelledby="rr-h-when">
          <h2 id="rr-h-when" className="r-title-sm">When did you notice it?</h2>
          <div
            role="radiogroup"
            aria-labelledby="rr-h-when"
            aria-required="true"
            aria-describedby={shown.when ? "rr-err-when" : undefined}
            className="rr-chips rr-seg"
          >
            {WHEN_CHOICES.map((w) => {
              const on = draft.observed_choice === w.value;
              return (
                <button
                  key={w.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  className="rr-chip"
                  onClick={() => setObserved(w.value)}
                >
                  {on ? <IconCheck size={18} /> : null}
                  {w.label}
                </button>
              );
            })}
          </div>
          {draft.observed_choice === "earlier" ? (
            <div className="r-field">
              <label htmlFor="rr-when-at" className="r-label">About when?</label>
              <input
                id="rr-when-at"
                data-focus-first
                className="r-input"
                type="datetime-local"
                max={toLocalInput(new Date())}
                value={draft.observed_local}
                onChange={(e) => update({ observed_local: e.target.value })}
                aria-invalid={shown.when ? true : undefined}
                aria-describedby={shown.when ? "rr-when-hint rr-err-when" : "rr-when-hint"}
              />
              <p className="r-hint" id="rr-when-hint">Your best guess is fine.</p>
            </div>
          ) : null}
          {draft.observed_choice === "unknown" ? (
            <p className="r-hint">That's fine. The property team will see when your report arrived.</p>
          ) : null}
          {shown.when ? <FieldError id="rr-err-when">{shown.when}</FieldError> : null}
        </section>

        <section id="rr-sec-photos" className="r-section rr-sec" aria-labelledby="rr-h-photos">
          <h2 id="rr-h-photos" className="r-title-sm">
            Photos <span className="rr-optional">optional</span>
          </h2>
          <p className="r-hint" id="rr-photos-hint">
            {full
              ? `That's ${MAX_PHOTOS} photos, the most one report can take.`
              : `A photo helps the property team see the damage. Up to ${MAX_PHOTOS}.`}
          </p>
          <div className="rr-photo-actions">
            <button
              type="button"
              className="r-btn"
              data-add-photo
              onClick={() => cameraRef.current?.click()}
              disabled={full}
              aria-describedby="rr-photos-hint"
            >
              <IconCamera size={22} /> Take photo
            </button>
            <button
              type="button"
              className="r-btn"
              onClick={() => libraryRef.current?.click()}
              disabled={full}
              aria-describedby="rr-photos-hint"
            >
              <IconImage size={22} /> Choose photos
            </button>
            <input
              ref={cameraRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="r-sr"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => addFiles(e.currentTarget)}
            />
            <input
              ref={libraryRef}
              type="file"
              accept="image/*"
              multiple
              className="r-sr"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => addFiles(e.currentTarget)}
            />
          </div>
          {photoCount > 0 ? <PhotoGrid photos={draft.photos} label="Photos you added" onRemove={removePhoto} /> : null}
          {photoNotice ? <p className="r-hint" role="status">{photoNotice}</p> : null}
          {prepFailures.map(({ p, n }) => (
            <FieldError key={p.local_id} id={`rr-err-photo-${p.local_id}`}>
              Photo {n}: {p.error}
            </FieldError>
          ))}
          {shown.photos ? <FieldError id="rr-err-photos">{shown.photos}</FieldError> : null}
        </section>
      </main>
      <ActionBar>
        <button type="button" className="r-btn primary" onClick={goReview}>
          Review report
        </button>
      </ActionBar>
    </>
  );
}

function FieldError({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={id} className="r-field-error rr-err">
      <IconAlert size={18} />
      <span>{children}</span>
    </p>
  );
}

const PHOTO_STATE_LABEL: Record<PhotoItem["state"], string | null> = {
  preparing: "Preparing…",
  ready: null,
  uploading: "Uploading…",
  uploaded: "Uploaded",
  failed: "Didn't upload",
};

function PhotoGrid({ photos, label, onRemove }: { photos: PhotoItem[]; label: string; onRemove?: (p: PhotoItem) => void }) {
  return (
    <ul className="r-photos rr-photo-list" aria-label={label}>
      {photos.map((p, i) => {
        const n = i + 1;
        const failed = p.state === "failed";
        const stateLabel = failed && !p.file ? "Couldn't add" : PHOTO_STATE_LABEL[p.state];
        const busy = p.state === "preparing" || p.state === "uploading";
        return (
          <li key={p.local_id} className="r-photo" aria-busy={busy || undefined}>
            {p.preview_url ? (
              <img src={p.preview_url} alt={`Photo ${n} you added`} />
            ) : (
              <span className="rr-photo-blank" role="img" aria-label={`Photo ${n}`}>
                <IconImage size={28} />
              </span>
            )}
            {stateLabel ? (
              <span className={`r-photo-state${failed ? " failed" : ""}`}>
                {p.state === "uploaded" ? <IconCheck size={14} /> : failed ? <IconAlert size={14} /> : null}
                {stateLabel}
              </span>
            ) : null}
            {busy ? <span className="rr-photo-busy" aria-hidden="true" /> : null}
            {onRemove ? (
              <button
                type="button"
                className="r-photo-remove"
                aria-label={`Remove photo ${n}`}
                disabled={p.state === "uploading"}
                onClick={() => onRemove(p)}
              >
                <IconClose size={18} />
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
