import type { CommandResult } from "../../../docs/recovery-handoffs/shared-contract";
import { RecoveryApiError } from "./client";

export interface NoticeDraft {
  draft_id: string;
  run_id: string | null;
  base_analysis_revision: number | null;
  title: string;
  body: string;
  source_ids: string[];
  eligible: boolean;
  unavailable_reason: string | null;
}
export interface NoticeScope { case_id: string; case_revision: number; analysis_revision: number }
export interface NoticeDraftList extends NoticeScope { drafts: NoticeDraft[] }
export interface PublishNoticeInput {
  expected_revision: number;
  title: string;
  body: string;
  household_ids: string[] | null;
}
type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
const failure = (status: number, code: string, message: string, retryable = false) =>
  new RecoveryApiError(status, { code, message, retryable });
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === "string");
const aborted = () => new DOMException("Request aborted", "AbortError");
export const noticeScopeKey = (scope: NoticeScope) => JSON.stringify([scope.case_id, scope.case_revision, scope.analysis_revision]);

function draftList(value: unknown): value is NoticeDraftList {
  if (!value || typeof value !== "object") return false;
  const list = value as Partial<NoticeDraftList>;
  if (typeof list.case_id !== "string" || !positive(list.case_revision) || !positive(list.analysis_revision) || !Array.isArray(list.drafts)) return false;
  const ids = new Set<string>();
  return list.drafts.every(draft => {
    if (!draft || typeof draft !== "object" || typeof draft.draft_id !== "string" || !draft.draft_id || ids.has(draft.draft_id)
        || (draft.run_id !== null && typeof draft.run_id !== "string")
        || (draft.base_analysis_revision !== null && !positive(draft.base_analysis_revision))
        || typeof draft.title !== "string" || typeof draft.body !== "string" || !strings(draft.source_ids)
        || typeof draft.eligible !== "boolean" || (draft.eligible && (draft.run_id === null || draft.base_analysis_revision === null))
        || (draft.unavailable_reason !== null && typeof draft.unavailable_reason !== "string")) return false;
    ids.add(draft.draft_id);
    return true;
  });
}

export function normalizedNotice(input: PublishNoticeInput): PublishNoticeInput {
  const title = input.title.trim(), body = input.body.trim();
  if (!positive(input.expected_revision) || !title || title.length > 200 || !body || body.length > 4000) {
    throw failure(0, "invalid_notice", "Enter a title of up to 200 characters and an update of up to 4,000 characters.");
  }
  if (input.household_ids !== null && (!strings(input.household_ids) || input.household_ids.length === 0 || input.household_ids.some(id => !id.trim()))) {
    throw failure(0, "invalid_recipients", "Choose at least one household or send to all households.");
  }
  return { expected_revision: input.expected_revision, title, body,
    household_ids: input.household_ids === null ? null : [...new Set(input.household_ids)].sort() };
}

/** Ignore the changing case revision when displaying confirmation of identical published copy. */
export function noticeContentKey(input: PublishNoticeInput): string {
  const { title, body, household_ids } = normalizedNotice(input);
  return JSON.stringify({ title, body, household_ids });
}

export function createNoticeClient(options: { fetch?: Fetcher } = {}) {
  const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  async function request(path: string, init: RequestInit): Promise<unknown> {
    let response: Response;
    try {
      response = await fetcher(path, { ...init, credentials: "same-origin", cache: "no-store",
        headers: { Accept: "application/json", ...init.headers } });
    } catch {
      if (init.signal?.aborted) throw aborted();
      throw failure(0, "network_error", "Could not reach resident updates. Try again with the same draft.", true);
    }
    if (init.signal?.aborted) throw aborted();
    let value: unknown;
    try { value = await response.json(); } catch { /* Never show proxy HTML or transport internals. */ }
    if (!response.ok) {
      const error = (value as { error?: { code?: unknown; message?: unknown; retryable?: unknown; current_revision?: unknown } } | undefined)?.error;
      if (error && typeof error.code === "string" && typeof error.message === "string" && typeof error.retryable === "boolean") {
        throw new RecoveryApiError(response.status, { code: error.code, message: error.message, retryable: error.retryable,
          ...(positive(error.current_revision) ? { current_revision: error.current_revision } : {}) });
      }
      throw failure(response.status, "notice_request_failed",
        response.status === 401 || response.status === 403 ? "Your owner session is unavailable." : "Resident updates could not be loaded. Try again.",
        response.status >= 500 || response.status === 429);
    }
    if (value === undefined) throw failure(502, "invalid_response", "Resident updates returned an unreadable response.", true);
    return value;
  }
  return {
    async list(case_id: string, signal?: AbortSignal): Promise<NoticeDraftList> {
      const value = await request(`/api/recovery/cases/${encodeURIComponent(case_id)}/draft-notices`, { signal });
      if (!draftList(value)) throw failure(502, "invalid_response", "Resident updates returned an invalid draft list.", true);
      return value;
    },
    async publish(case_id: string, draft_id: string, input: PublishNoticeInput, key: string, signal?: AbortSignal): Promise<CommandResult> {
      const body = normalizedNotice(input);
      if (!key || key.length < 8 || key.length > 200 || /[\r\n]/.test(key)) throw failure(0, "invalid_idempotency_key", "This publication needs a valid request key.");
      const value = await request(`/api/recovery/cases/${encodeURIComponent(case_id)}/draft-notices/${encodeURIComponent(draft_id)}/publish`, {
        method: "POST", signal, headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(body),
      });
      const result = value as Partial<CommandResult>;
      if (!result || !positive(result.case_revision) || result.case_revision <= body.expected_revision || !positive(result.analysis_revision)
          || (result.run_id !== null && typeof result.run_id !== "string")
          || (result.invitation_token !== null && typeof result.invitation_token !== "string")
          || (result.invitation_expires_at !== null && typeof result.invitation_expires_at !== "string")) {
        throw failure(502, "invalid_response", "Publication could not be confirmed. Retry the same draft.", true);
      }
      return result as CommandResult;
    },
  };
}

export interface NoticeState {
  scope: NoticeScope | null;
  status: "loading" | "ready" | "error";
  data: NoticeDraftList | null;
  error: string | null;
  publishing_id: string | null;
  publication_error: { draft_id: string; message: string } | null;
  published: Record<string, string>;
}
export const emptyNoticeState = (): NoticeState => ({ scope: null, status: "loading", data: null, error: null,
  publishing_id: null, publication_error: null, published: {} });

/** Request lifetimes and retries are independent of React rendering. No automatic publication. */
export class DraftNoticeController {
  state = emptyNoticeState();
  private generation = 0;
  private loadAbort: AbortController | null = null;
  private publishAbort: AbortController | null = null;
  // Keep the original request, including its revision, until the user changes
  // copy/audience or a definitive conflict proves it was never committed. SSE
  // may advance the case before a successful POST response reaches the browser.
  private attempts = new Map<string, { content: string; body: PublishNoticeInput; key: string }>();

  constructor(private readonly api: ReturnType<typeof createNoticeClient>, private readonly changed: (state: NoticeState) => void,
              private readonly newKey: () => string = () => globalThis.crypto?.randomUUID?.()
                ?? `notice-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`) {}

  private emit(patch: Partial<NoticeState>) { this.state = { ...this.state, ...patch }; this.changed(this.state); }

  async load(scope: NoticeScope): Promise<void> {
    const changedCase = this.state.scope?.case_id !== scope.case_id;
    this.cancel();
    const generation = this.generation;
    const controller = new AbortController();
    this.loadAbort = controller;
    if (changedCase) this.attempts.clear();
    this.emit({ scope: { ...scope }, status: "loading", data: null, error: null, publishing_id: null,
      publication_error: null, ...(changedCase ? { published: {} } : {}) });
    try {
      const data = await this.api.list(scope.case_id, controller.signal);
      if (controller.signal.aborted || generation !== this.generation) return;
      if (noticeScopeKey(data) !== noticeScopeKey(scope)) throw failure(409, "revision_conflict", "This case changed. Refresh the case before publishing an update.", true);
      this.emit({ status: "ready", data });
    } catch (error) {
      if (controller.signal.aborted || generation !== this.generation) return;
      this.emit({ status: "error", data: null, error: error instanceof Error ? error.message : "Resident updates could not be loaded." });
      throw error;
    }
  }

  async publish(draft_id: string, input: PublishNoticeInput): Promise<CommandResult | null> {
    const scope = this.state.scope, draft = this.state.data?.drafts.find(row => row.draft_id === draft_id);
    if (!scope || this.state.status !== "ready" || this.state.publishing_id || !draft || !draft.eligible
        || draft.base_analysis_revision !== scope.analysis_revision || input.expected_revision !== scope.case_revision) {
      throw failure(409, "draft_unavailable", "This draft is out of date or unavailable. Refresh the case before publishing.", true);
    }
    const requested = normalizedNotice(input), content = noticeContentKey(requested);
    const previous = this.attempts.get(draft_id);
    const attempt = previous?.content === content ? previous : { content, body: requested, key: this.newKey() };
    const { body, key } = attempt;
    this.attempts.set(draft_id, attempt);
    const generation = this.generation, controller = new AbortController();
    this.publishAbort = controller;
    this.emit({ publishing_id: draft_id, publication_error: null });
    try {
      const result = await this.api.publish(scope.case_id, draft_id, body, key, controller.signal);
      if (controller.signal.aborted || generation !== this.generation) return null;
      this.emit({ publishing_id: null, published: { ...this.state.published, [draft_id]: noticeContentKey(body) } });
      return result;
    } catch (error) {
      if (controller.signal.aborted || generation !== this.generation) return null;
      if (error instanceof RecoveryApiError && error.status === 409 && error.code === "revision_conflict") {
        // Platform checks saved idempotency receipts before revision conflicts.
        // This response means the pinned old request has no successful receipt.
        this.attempts.delete(draft_id);
      }
      this.emit({ publishing_id: null, publication_error: { draft_id, message: error instanceof Error ? error.message : "Publication could not be confirmed. Try again." } });
      throw error;
    }
  }

  cancel(): void {
    this.generation += 1;
    this.loadAbort?.abort();
    this.publishAbort?.abort();
    this.loadAbort = null;
    this.publishAbort = null;
  }
}
