import type {
  ApiErrorBody,
  CaseEvent,
  CommandResult,
  OwnerCaseView,
  OwnerCommand,
  RecoveryCaseSummary,
  ResidentApi,
  ResidentHome,
  ReportInput,
  ReportReceipt,
  SupportInput,
  SupportReceipt,
  UploadedMedia,
} from "../../../docs/recovery-handoffs/shared-contract";
import type { RecoverySpatial } from "./spatial";

export interface HouseholdInput { expected_revision: number; unit_label: string | null }
export interface HouseholdReceipt {
  case_id: string;
  household: { household_id: string; unit_label: string | null; unit_confirmed: false };
  case_revision: number;
  analysis_revision: number;
  duplicate: boolean;
}
export interface HouseholdAccessView {
  case_id: string;
  case_revision: number;
  households: { household_id: string; unit_label: string | null; active_session_count: number;
    active_invitation_count: number;
    invitations: { invitation_id: string; created_at: string; expires_at: string; revoked_at: string | null }[] }[];
}
export interface RevokeAccessReceipt {
  case_id: string; household_id: string; case_revision: number; analysis_revision: number;
  revoked_invitation_count: number; revoked_session_count: number; duplicate: boolean;
}

export class RecoveryApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly current_revision?: number;

  constructor(status: number, error: ApiErrorBody["error"]) {
    super(error.message);
    this.name = "RecoveryApiError";
    this.status = status;
    this.code = error.code;
    this.retryable = error.retryable;
    this.current_revision = error.current_revision;
  }
}

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type ConnectionState = "connected" | "reconnecting" | "expired";
type Sleep = (milliseconds: number, signal: AbortSignal) => Promise<void>;
export interface RecoverySubscription {
  after: number;
  on_event: (event: CaseEvent) => void;
  on_connection: (state: ConnectionState) => void;
  /** Owner adapters may surface transport errors; ResidentApi remains unchanged. */
  on_error?: (error: RecoveryApiError) => void;
}
export interface RecoveryClientOptions {
  fetch?: Fetch;
  sleep?: Sleep;
  reconnect_initial_ms?: number;
  reconnect_max_ms?: number;
}

function abortError(): DOMException {
  return new DOMException("Request aborted", "AbortError");
}

function sleep(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(abortError()); return; }
    const onAbort = () => { clearTimeout(timer); reject(abortError()); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", onAbort); resolve(); }, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function failure(status: number, code: string, message: string, retryable = false): RecoveryApiError {
  return new RecoveryApiError(status, { code, message, retryable });
}

async function responseError(response: Response): Promise<RecoveryApiError> {
  let data: unknown;
  try { data = await response.json(); } catch { /* A proxy error page is not user-facing error text. */ }
  const body = data as Partial<ApiErrorBody> | undefined;
  const error = body?.error;
  if (error && typeof error.code === "string" && typeof error.message === "string" && typeof error.retryable === "boolean") {
    return new RecoveryApiError(response.status, {
      code: error.code, message: error.message, retryable: error.retryable,
      ...(Number.isSafeInteger(error.current_revision) ? { current_revision: error.current_revision } : {}),
    });
  }
  return failure(response.status, response.status === 401 || response.status === 403 ? "session_expired" : "request_failed",
    response.status === 401 || response.status === 403 ? "Your session has expired or does not have access." : `Recovery request failed (${response.status}).`,
    response.status === 408 || response.status === 429 || response.status >= 500);
}

function networkError(error: unknown): RecoveryApiError {
  return error instanceof RecoveryApiError ? error : failure(0, "network_error", "Could not reach the recovery service. Try again.", true);
}

function cursor(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isEvent(value: unknown): value is CaseEvent {
  if (!value || typeof value !== "object") return false;
  const e = value as Partial<CaseEvent>;
  return cursor(e.event_id) && cursor(e.case_revision) && cursor(e.analysis_revision)
    && typeof e.case_id === "string" && typeof e.type === "string" && typeof e.at === "string"
    && (e.entity_id === null || typeof e.entity_id === "string")
    && (e.public_summary === null || typeof e.public_summary === "string");
}

/** Incremental UTF-8/CRLF-aware framing. Only complete, blank-line-delimited events dispatch. */
class EventParser {
  private buffer = "";
  private data: string[] = [];
  private id: string | undefined;
  private frameSize = 0;

  constructor(private readonly dispatch: (data: string, id?: string) => void) {}

  push(chunk: string, final = false): void {
    this.buffer += chunk;
    if (this.buffer.length + this.frameSize > 1024 * 1024) throw failure(502, "invalid_stream", "Recovery event is too large.", true);
    while (true) {
      const index = this.buffer.search(/[\r\n]/);
      if (index < 0 || (!final && this.buffer[index] === "\r" && index === this.buffer.length - 1)) return;
      const line = this.buffer.slice(0, index);
      const length = this.buffer[index] === "\r" && this.buffer[index + 1] === "\n" ? 2 : 1;
      this.buffer = this.buffer.slice(index + length);
      this.line(line);
    }
  }

  private line(line: string): void {
    if (line === "") {
      if (this.data.length) this.dispatch(this.data.join("\n"), this.id);
      this.data = [];
      this.id = undefined;
      this.frameSize = 0;
      return;
    }
    if (line.startsWith(":")) return; // Heartbeat comment.
    this.frameSize += line.length;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.data.push(value);
    if (field === "id" && !value.includes("\0")) this.id = value;
    // Server retry/event names cannot change the client's bounded reconnect policy.
  }
}

export function createRecoveryClient(options: RecoveryClientOptions = {}) {
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  const wait = options.sleep ?? sleep;
  const initialDelay = options.reconnect_initial_ms ?? 500;
  const maxDelay = options.reconnect_max_ms ?? 15000;
  if (!Number.isFinite(initialDelay) || initialDelay < 1 || !Number.isFinite(maxDelay) || maxDelay < initialDelay) {
    throw new RangeError("Reconnect delays must be positive and bounded.");
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetcher(path, { ...init, credentials: "same-origin", cache: "no-store",
        headers: { Accept: "application/json", ...init.headers } });
    } catch (error) {
      if (init.signal?.aborted) throw abortError();
      throw networkError(error);
    }
    if (!response.ok) throw await responseError(response);
    try { return await response.json() as T; }
    catch { throw failure(response.status, "invalid_response", "The recovery service returned an unreadable response.", true); }
  }

  function keyHeader(key: string): Record<string, string> {
    if (typeof key !== "string" || !key.trim() || /[\r\n]/.test(key)) {
      throw failure(0, "invalid_idempotency_key", "Use a nonempty idempotency key for this submission.");
    }
    return { "Idempotency-Key": key };
  }

  function post<T>(path: string, body: unknown, key?: string): Promise<T> {
    return request<T>(path, { method: "POST", headers: { "Content-Type": "application/json", ...(key === undefined ? {} : keyHeader(key)) }, body: JSON.stringify(body) });
  }

  function subscribe(path: string, args: RecoverySubscription, caseId?: string): () => void {
    if (!cursor(args.after)) throw new RangeError("Event cursor must be a nonnegative safe integer.");
    const controller = new AbortController();
    let activeReader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let lastCursor = args.after;
    let delay = initialDelay;
    let stopped = false;
    let state: ConnectionState | undefined;

    const stop = () => {
      if (stopped) return;
      stopped = true;
      controller.abort();
      void activeReader?.cancel().catch(() => undefined);
      if (typeof window !== "undefined") window.removeEventListener("pagehide", stop);
    };
    const connection = (next: ConnectionState) => {
      if (stopped || state === next) return;
      state = next;
      args.on_connection(next);
    };
    if (typeof window !== "undefined") window.addEventListener("pagehide", stop, { once: true });

    const run = async () => {
      while (!stopped) {
        try {
          const response = await fetcher(`${path}?after=${lastCursor}`, {
            credentials: "same-origin", cache: "no-store", signal: controller.signal,
            headers: { Accept: "text/event-stream", "Last-Event-ID": String(lastCursor) },
          });
          if (stopped) { void response.body?.cancel().catch(() => undefined); break; }
          if (!response.ok) throw await responseError(response);
          if (!response.body || !response.headers.get("content-type")?.toLowerCase().includes("text/event-stream")) {
            throw failure(502, "invalid_stream", "The recovery event stream is unavailable.", true);
          }
          activeReader = response.body.getReader();
          connection("connected");
          const decoder = new TextDecoder();
          const parser = new EventParser((data, id) => {
            if (stopped) return;
            let event: unknown;
            try { event = JSON.parse(data); } catch { throw failure(502, "invalid_stream", "A recovery event could not be read.", true); }
            if (!isEvent(event) || (id !== undefined && (!/^\d+$/.test(id) || Number(id) !== event.event_id)) || (caseId !== undefined && event.case_id !== caseId)) {
              throw failure(502, "invalid_stream", "A recovery event did not match the requested case or cursor.", true);
            }
            if (event.event_id <= lastCursor) return;
            lastCursor = event.event_id;
            delay = initialDelay;
            args.on_event(event);
            if (event.type === "session.revoked" && caseId === undefined) { connection("expired"); stop(); }
          });
          while (!stopped) {
            const { done, value } = await activeReader.read();
            if (done) { parser.push(decoder.decode(), true); break; }
            parser.push(decoder.decode(value, { stream: true }));
          }
        } catch (error) {
          if (stopped || controller.signal.aborted) break;
          const problem = networkError(error);
          args.on_error?.(problem);
          if (problem.status === 401 || problem.status === 403) { connection("expired"); stop(); break; }
          if (!problem.retryable) { connection("reconnecting"); stop(); break; }
        } finally {
          if (activeReader) {
            try { await activeReader.cancel(); } catch { /* Stream already disconnected. */ }
            activeReader.releaseLock();
            activeReader = undefined;
          }
        }
        if (stopped) break;
        connection("reconnecting");
        try { await wait(delay, controller.signal); } catch { stop(); break; }
        delay = Math.min(maxDelay, delay * 2);
      }
    };
    // UI callbacks can throw; terminate rather than leak a subscription or reject globally.
    void run().catch(() => stop());
    return stop;
  }

  const resident_api: ResidentApi = {
    get_home: () => request<ResidentHome>("/api/resident/home"),
    upload_image: (file: File, idempotency_key: string) => {
      const body = new FormData();
      body.append("file", file);
      return request<UploadedMedia>("/api/resident/uploads", { method: "POST", headers: keyHeader(idempotency_key), body });
    },
    submit_report: (input: ReportInput, idempotency_key: string) => post<ReportReceipt>("/api/resident/reports", input, idempotency_key),
    request_support: (input: SupportInput, idempotency_key: string) => post<SupportReceipt>("/api/resident/support", input, idempotency_key),
    subscribe: (args) => subscribe("/api/resident/events", args),
  };

  return {
    owner_session: (secret: string) => post<{ ok: true }>("/api/recovery/session", { secret }),
    resident_session: (invitation_token: string) => post<{ ok: true }>("/api/resident/session", { invitation_token }),
    get_cases: () => request<{ cases: RecoveryCaseSummary[] }>("/api/recovery/cases"),
    get_case: (case_id: string) => request<OwnerCaseView>(`/api/recovery/cases/${encodeURIComponent(case_id)}`),
    get_spatial: (case_id: string, signal?: AbortSignal) => request<RecoverySpatial>(`/api/recovery/cases/${encodeURIComponent(case_id)}/spatial`, { signal }),
    create_household: (case_id: string, input: HouseholdInput, idempotency_key: string) =>
      post<HouseholdReceipt>(`/api/recovery/cases/${encodeURIComponent(case_id)}/households`, input, idempotency_key),
    get_household_access: (case_id: string, signal?: AbortSignal) =>
      request<HouseholdAccessView>(`/api/recovery/cases/${encodeURIComponent(case_id)}/households/access`, { signal }),
    revoke_household_access: (case_id: string, household_id: string, input: { expected_revision: number }, key: string) =>
      post<RevokeAccessReceipt>(`/api/recovery/cases/${encodeURIComponent(case_id)}/households/${encodeURIComponent(household_id)}/revoke-access`, input, key),
    command: (case_id: string, command: OwnerCommand, idempotency_key: string) =>
      post<CommandResult>(`/api/recovery/cases/${encodeURIComponent(case_id)}/commands`, command, idempotency_key),
    subscribe_case: (case_id: string, args: RecoverySubscription) =>
      subscribe(`/api/recovery/cases/${encodeURIComponent(case_id)}/events`, args, case_id),
    resident_api,
  };
}
