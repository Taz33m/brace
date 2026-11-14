import type { SupportReceipt } from "../../../docs/recovery-handoffs/shared-contract";
import { RecoveryApiError } from "./client";

export interface SupportReply {
  expected_revision: number;
  status: "under_review" | "responded" | "closed";
  public_status_detail: string;
}
export interface SupportReplyResult {
  request: SupportReceipt;
  case_revision: number;
  analysis_revision: number;
  duplicate: boolean;
}
export async function respondToSupport(caseId: string, requestId: string, body: SupportReply, key: string,
  signal?: AbortSignal): Promise<SupportReplyResult> {
  let response: Response;
  try {
    response = await fetch(`/api/recovery/cases/${encodeURIComponent(caseId)}/support-requests/${encodeURIComponent(requestId)}/respond`, {
      method: "POST", credentials: "same-origin", cache: "no-store", signal,
      headers: { "Content-Type": "application/json", Accept: "application/json", "Idempotency-Key": key },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new RecoveryApiError(0, { code: "network_error", message: "Could not confirm your response. Retry to check the same update.", retryable: true });
  }
  let result: unknown;
  try { result = await response.json(); } catch { /* Keep proxy details out of the portal. */ }
  if (!response.ok) {
    const detail = (result as { error?: { code?: unknown; message?: unknown; retryable?: unknown } } | undefined)?.error;
    throw new RecoveryApiError(response.status, {
      code: typeof detail?.code === "string" ? detail.code : "support_update_failed",
      message: typeof detail?.message === "string" ? detail.message : "Could not update this support request. Try again.",
      retryable: detail?.retryable === true || response.status >= 500,
    });
  }
  const value = result as Partial<SupportReplyResult> | undefined;
  if (!value || value.request?.request_id !== requestId || value.request.status !== body.status
      || value.request.public_status_detail !== body.public_status_detail
      || !Number.isSafeInteger(value.case_revision) || value.case_revision! <= body.expected_revision
      || !Number.isSafeInteger(value.analysis_revision) || value.analysis_revision! < 1
      || typeof value.duplicate !== "boolean") {
    throw new RecoveryApiError(502, { code: "invalid_response", message: "Your update could not be confirmed. Retry the same response.", retryable: true });
  }
  return value as SupportReplyResult;
}
