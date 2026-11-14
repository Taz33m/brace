/**
 * Interfaces between the ResidentExperience shell and its screens.
 * The shell owns server state (home snapshot, connection) and in-memory drafts; screens own
 * presentation and the submission interaction for their own flow.
 */
import type { ReportInput, ReportReceipt, ResidentApi, ResidentHome, SupportInput, SupportReceipt } from "../contract";
import type { Connection } from "../useResidentSession";
import type { SubmissionKeeper } from "../lib/idempotency";

export type Screen =
  | { name: "home" }
  | { name: "report" }
  | { name: "report_receipt"; receipt: ReportReceipt }
  | { name: "support" }
  | { name: "support_receipt"; receipt: SupportReceipt }
  | { name: "updates" };

/** A photo the resident added to a report. Lives in memory only (never localStorage). */
export interface PhotoItem {
  local_id: string;
  /** Prepared (resized/JPEG) file that will be uploaded. Null while preparing. */
  file: File | null;
  /** Object URL for the thumbnail. Revoked by whoever removes the item. */
  preview_url: string | null;
  state: "preparing" | "ready" | "uploading" | "uploaded" | "failed";
  /** One key per photo, reused on every retry of that photo's upload. */
  idempotency_key: string;
  upload_id: string | null;
  error: string | null;
}

export type ObservedChoice = "now" | "earlier" | "unknown";

export interface ReportDraft {
  category: ReportInput["category"] | null;
  /** Only ever a location_id from home.selectable_locations with binding "verified_unit". */
  selected_location_id: string | null;
  location_description: string;
  text: string;
  observed_choice: ObservedChoice | null;
  /** datetime-local value when observed_choice is "earlier". */
  observed_local: string;
  photos: PhotoItem[];
}

export interface SupportDraft {
  category: SupportInput["category"] | null;
  description: string;
}

export const emptyReportDraft = (): ReportDraft => ({
  category: null,
  selected_location_id: null,
  location_description: "",
  text: "",
  observed_choice: null,
  observed_local: "",
  photos: [],
});

export const emptySupportDraft = (): SupportDraft => ({ category: null, description: "" });

export interface HomeScreenProps {
  home: ResidentHome;
  /** Entity IDs touched by a recent live event, for a brief "just changed" highlight. */
  fresh_ids: ReadonlySet<string>;
  go: (screen: Screen) => void;
}

export interface ReportFlowProps {
  api: ResidentApi;
  home: ResidentHome;
  connection: Connection;
  draft: ReportDraft;
  set_draft: (update: (d: ReportDraft) => ReportDraft) => void;
  /** Shell-owned, so a retry after leaving and re-entering the screen reuses the same key. */
  keeper: SubmissionKeeper;
  /** Shell-owned "just now" stamp, reused across retries of the same intended report. */
  now_stamp: { current: string | null };
  /** Server confirmed the report. Shell clears the draft, refreshes home, shows the receipt. */
  on_submitted: (receipt: ReportReceipt) => void;
  on_cancel: () => void;
  /** A 401 from any call: shell switches to the expired state. */
  on_expired: () => void;
}

export interface ReceiptScreenProps {
  home: ResidentHome;
  receipt: { kind: "report"; receipt: ReportReceipt } | { kind: "support"; receipt: SupportReceipt };
  go: (screen: Screen) => void;
}

export interface SupportFlowProps {
  api: ResidentApi;
  home: ResidentHome;
  connection: Connection;
  draft: SupportDraft;
  set_draft: (update: (d: SupportDraft) => SupportDraft) => void;
  /** Shell-owned, so a retry after leaving and re-entering the screen reuses the same key. */
  keeper: SubmissionKeeper;
  on_submitted: (receipt: SupportReceipt) => void;
  on_cancel: () => void;
  on_expired: () => void;
}

export interface UpdatesScreenProps {
  home: ResidentHome;
  fresh_ids: ReadonlySet<string>;
  go: (screen: Screen) => void;
}
