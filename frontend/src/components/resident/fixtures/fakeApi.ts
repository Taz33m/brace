/**
 * UI FIXTURE — an in-memory ResidentApi for the explicit preview only.
 *
 * Never used as a fallback when the real API fails. Synthetic property, people and IDs.
 * Behaves like the contract: idempotent submissions keyed by Idempotency-Key, uploads before
 * reports, events that carry IDs (not data), replay after a dropped connection (with deliberate
 * duplicates so the client's dedupe is exercised), and 401s for an expired session.
 */
import type {
  CaseEvent,
  PublishedNotice,
  ReportInput,
  ReportReceipt,
  ResidentApi,
  ResidentHome,
  ResidentReport,
  SupportInput,
  SupportReceipt,
  TaskStatus,
  UploadedMedia,
} from "../contract";
import { buildHome, type FixtureOptions } from "./data";

export type Scenario = "happy" | "lost_response" | "upload_failure" | "expired_on_submit" | "no_rooms" | "empty" | "unit_unconfirmed";

export const SCENARIOS: { value: Scenario; label: string; detail: string }[] = [
  { value: "happy", label: "Everything works", detail: "Normal latency, every call succeeds." },
  { value: "lost_response", label: "Lost response, then retry", detail: "First send is saved but the reply is lost. Retry returns the same receipt." },
  { value: "upload_failure", label: "Photo upload fails once", detail: "Each photo's first upload fails with 503; retry succeeds." },
  { value: "expired_on_submit", label: "Session expires on send", detail: "Sending a report or request returns 401." },
  { value: "no_rooms", label: "No verified unit scan", detail: "No selectable rooms; descriptive location only." },
  { value: "empty", label: "Nothing yet", detail: "No notices, tasks, reports or requests." },
  { value: "unit_unconfirmed", label: "Unit not confirmed", detail: "Household's unit association is unconfirmed." },
];

class HttpError extends Error {
  constructor(public status: number, public body: { error: { code: string; message: string; retryable: boolean } }) {
    super(body.error.message);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

const expiredError = () =>
  new HttpError(401, { error: { code: "session_expired", message: "Your access link has expired. Ask the property team for a new one.", retryable: false } });

interface Listener {
  on_event: (e: CaseEvent) => void;
  on_connection: (s: "connected" | "reconnecting" | "expired") => void;
  connected: boolean;
  last_delivered: number;
}

const TASK_ORDER: TaskStatus[] = ["proposed", "approved", "accepted", "in_progress", "completion_submitted", "verified"];
const TASK_DETAIL: Record<TaskStatus, string> = {
  proposed: "The property team is planning this work.",
  approved: "Approved. A crew has not accepted it yet.",
  accepted: "A crew accepted the job.",
  in_progress: "The crew has started work.",
  completion_submitted: "The crew says it is finished. The property team will check it.",
  verified: "The property team checked the repair.",
  cancelled: "This work was cancelled.",
};

export class FakeResidentApi implements ResidentApi {
  private home: ResidentHome;
  private events: CaseEvent[] = [];
  private listeners = new Set<Listener>();
  private idem = new Map<string, unknown>();
  private failedOnce = new Set<string>();
  private expired = false;
  private seq = 1;
  readonly scenario: Scenario;
  latency = 650;

  constructor(scenario: Scenario = "happy") {
    this.scenario = scenario;
    const opts: FixtureOptions = {
      rooms: scenario !== "no_rooms",
      content: scenario !== "empty",
      unit_confirmed: scenario !== "unit_unconfirmed",
    };
    this.home = buildHome(opts);
  }

  // ---------------- ResidentApi ----------------

  async get_home(): Promise<ResidentHome> {
    await sleep(this.latency * 0.6);
    this.guard();
    return clone(this.home);
  }

  async upload_image(file: File, idempotency_key: string): Promise<UploadedMedia> {
    await sleep(this.latency + Math.min(1500, file.size / 2000));
    this.guard();
    const prior = this.idem.get(`u:${idempotency_key}`) as UploadedMedia | undefined;
    if (prior) return clone(prior);
    if (this.scenario === "upload_failure" && !this.failedOnce.has(`u:${idempotency_key}`)) {
      this.failedOnce.add(`u:${idempotency_key}`);
      throw new HttpError(503, { error: { code: "upload_unavailable", message: "Photo storage is busy. Try that photo again.", retryable: true } });
    }
    if (!file.type.startsWith("image/")) {
      throw new HttpError(422, { error: { code: "not_an_image", message: "That file isn't a photo.", retryable: false } });
    }
    const id = `upl_${this.seq++}`;
    const media: UploadedMedia = {
      upload_id: id,
      media: { media_id: `med_${id}`, url: URL.createObjectURL(file), alt: "Photo you added", mime_type: file.type },
    };
    this.idem.set(`u:${idempotency_key}`, media);
    return clone(media);
  }

  async submit_report(input: ReportInput, idempotency_key: string): Promise<ReportReceipt> {
    await sleep(this.latency);
    this.guard();
    if (this.scenario === "expired_on_submit") {
      this.expire(false);
      throw expiredError();
    }
    const prior = this.idem.get(`r:${idempotency_key}`) as ReportReceipt | undefined;
    if (prior) {
      if (this.idem.get(`rp:${idempotency_key}`) !== JSON.stringify(input)) {
        throw new HttpError(409, { error: { code: "idempotency_conflict", message: "This key was already used for a different report.", retryable: false } });
      }
      return { ...clone(prior), duplicate: true };
    }
    if (!input.text.trim()) {
      throw new HttpError(422, { error: { code: "text_required", message: "Say what happened before sending.", retryable: false } });
    }
    const loc = input.selected_location_id
      ? this.home.selectable_locations.find((l) => l.location_id === input.selected_location_id && l.binding === "verified_unit") ?? null
      : null;
    if (input.selected_location_id && !loc) {
      throw new HttpError(422, { error: { code: "location_unavailable", message: "That room can't be selected. Describe where it is instead.", retryable: false } });
    }
    const uploads = [...this.idem.entries()].filter(([k]) => k.startsWith("u:")).map(([, v]) => v as UploadedMedia);
    const media = input.upload_ids.map((u) => {
      const m = uploads.find((v) => v.upload_id === u);
      if (!m) throw new HttpError(422, { error: { code: "unknown_upload", message: "A photo didn't finish uploading. Try it again.", retryable: false } });
      return m.media;
    });
    const report: ResidentReport = {
      report_id: `RPT-${1040 + this.seq++}`,
      household_id: "fx-hh-4b",
      category: input.category,
      text: input.text.trim(),
      location: loc,
      location_description: input.location_description,
      observed_at: input.observed_at,
      received_at: new Date().toISOString(),
      status: "reported",
      media,
      public_status_detail: "The property team will review your report. Changes will show here.",
    };
    this.home.reports.unshift(report);
    this.bump("report.updated", report.report_id);
    const receipt: ReportReceipt = { report: clone(report), case_revision: this.home.case_revision, analysis_revision: 1, duplicate: false };
    this.idem.set(`r:${idempotency_key}`, receipt);
    this.idem.set(`rp:${idempotency_key}`, JSON.stringify(input));
    if (this.scenario === "lost_response" && !this.failedOnce.has(`r:${idempotency_key}`)) {
      this.failedOnce.add(`r:${idempotency_key}`);
      throw new TypeError("Failed to fetch"); // saved server-side, reply lost on the way back
    }
    return clone(receipt);
  }

  async request_support(input: SupportInput, idempotency_key: string): Promise<SupportReceipt> {
    await sleep(this.latency);
    this.guard();
    if (this.scenario === "expired_on_submit") {
      this.expire(false);
      throw expiredError();
    }
    const prior = this.idem.get(`s:${idempotency_key}`) as SupportReceipt | undefined;
    if (prior) return { ...clone(prior), duplicate: true };
    if (!input.description.trim()) {
      throw new HttpError(422, { error: { code: "description_required", message: "Say what you need before sending.", retryable: false } });
    }
    const receipt: SupportReceipt = {
      request_id: `SUP-${310 + this.seq++}`,
      household_id: "fx-hh-4b",
      category: input.category,
      description: input.description.trim(),
      status: "received",
      received_at: new Date().toISOString(),
      public_status_detail: "The property team has your request. This is not a booking; they'll reply here.",
      duplicate: false,
    };
    this.home.support_requests.unshift(receipt);
    this.bump("support.updated", receipt.request_id);
    this.idem.set(`s:${idempotency_key}`, receipt);
    if (this.scenario === "lost_response" && !this.failedOnce.has(`s:${idempotency_key}`)) {
      this.failedOnce.add(`s:${idempotency_key}`);
      throw new TypeError("Failed to fetch");
    }
    return clone(receipt);
  }

  subscribe(args: {
    after: number;
    on_event: (event: CaseEvent) => void;
    on_connection: (state: "connected" | "reconnecting" | "expired") => void;
  }): () => void {
    const l: Listener = { on_event: args.on_event, on_connection: args.on_connection, connected: false, last_delivered: args.after };
    this.listeners.add(l);
    setTimeout(() => {
      if (!this.listeners.has(l)) return;
      if (this.expired) return l.on_connection("expired");
      l.connected = true;
      l.on_connection("connected");
      this.replay(l);
    }, 300);
    return () => {
      this.listeners.delete(l);
    };
  }

  // ---------------- preview controls (owner-side simulation) ----------------

  /** Owner moves the newest open report reported -> under_review -> verified. */
  reviewLatestReport(): string {
    const r = this.home.reports.find((x) => x.status === "reported" || x.status === "under_review");
    if (!r) return "No open report to review. Send one first.";
    r.status = r.status === "reported" ? "under_review" : "verified";
    r.public_status_detail =
      r.status === "under_review"
        ? "The property team is reviewing your report."
        : "The property team confirmed this problem. Repair work will show under tasks.";
    this.bump("report.updated", r.report_id);
    return `Report ${r.report_id} → ${r.status}`;
  }

  /** Owner/crew advance the first open task one step (creates a proposed task if none is open). */
  advanceTask(): string {
    let t = this.home.tasks.find((x) => x.status !== "verified" && x.status !== "cancelled");
    if (!t) {
      t = {
        task_id: `TSK-${200 + this.seq++}`,
        revision: 1,
        title: "Dry out and replace wet ceiling drywall in the hallway",
        status: "proposed",
        public_status_detail: TASK_DETAIL.proposed,
        confirmed_schedule: null,
        updated_at: new Date().toISOString(),
      };
      this.home.tasks.unshift(t);
    } else {
      const next = TASK_ORDER[TASK_ORDER.indexOf(t.status) + 1];
      t.status = next;
      t.public_status_detail = TASK_DETAIL[next];
      t.updated_at = new Date().toISOString();
      if (next === "accepted") {
        const when = new Date(Date.now() + 26 * 3600 * 1000);
        when.setMinutes(0, 0, 0);
        t.confirmed_schedule = when.toISOString();
      }
    }
    this.bump("task.updated", t.task_id);
    return `Task ${t.task_id} → ${t.status}`;
  }

  /** Owner publishes a building notice. */
  publishNotice(): string {
    const n: PublishedNotice = {
      notice_id: `NTC-${100 + this.seq++}`,
      title: "Lift B back in service",
      body: "Lift B is working again. Lift A stays off while the motor room dries out. Use the east stairs if you need to.",
      published_at: new Date().toISOString(),
      published_by: "Property management",
      source_ids: [],
    };
    this.home.notices.unshift(n);
    this.bump("notice.published", n.notice_id);
    return `Notice ${n.notice_id} published`;
  }

  /** Drop every live connection, then reconnect and replay starting one event early (a duplicate). */
  dropConnection(seconds = 4): string {
    for (const l of this.listeners) {
      l.connected = false;
      l.on_connection("reconnecting");
    }
    setTimeout(() => {
      for (const l of this.listeners) {
        if (this.expired) {
          l.on_connection("expired");
          continue;
        }
        l.connected = true;
        l.on_connection("connected");
        l.last_delivered = Math.max(0, l.last_delivered - 1);
        this.replay(l);
      }
    }, seconds * 1000);
    return `Connection dropped for ${seconds}s`;
  }

  /** Revoke the session: next calls 401, live stream reports expired. */
  expire(notify = true): string {
    this.expired = true;
    if (notify) this.bump("session.revoked", null);
    for (const l of this.listeners) l.on_connection("expired");
    return "Session revoked";
  }

  // ---------------- internals ----------------

  private guard() {
    if (this.expired) throw expiredError();
  }

  /** Commit a change: advance revision + cursor, append an ID-only event, deliver to live listeners. */
  private bump(type: string, entity_id: string | null) {
    this.home.case_revision += 1;
    this.home.event_cursor += 1;
    this.home.updated_at = new Date().toISOString();
    this.events.push({
      event_id: this.home.event_cursor,
      case_id: this.home.case_id,
      case_revision: this.home.case_revision,
      analysis_revision: 1,
      type,
      at: this.home.updated_at,
      entity_id,
      public_summary: null,
    });
    for (const l of this.listeners) if (l.connected) this.replay(l);
  }

  private replay(l: Listener) {
    for (const e of this.events) if (e.event_id > l.last_delivered) l.on_event(clone(e));
    const last = this.events[this.events.length - 1];
    if (last) l.last_delivered = Math.max(l.last_delivered, last.event_id);
  }
}
