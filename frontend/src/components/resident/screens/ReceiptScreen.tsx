/**
 * Receipt after a report or support request. Shows only what the server returned: the stable ID,
 * received time, status and its public next step, and what the resident sent. Never promises an
 * inspection or appointment time.
 */
import type { ReactNode } from "react";
import type { ReportReceipt, SupportReceipt } from "../contract";
import type { ReceiptScreenProps, Screen } from "./types";
import { ActionBar, Message, ScreenHead, StatusPill } from "../ui";
import { IconCheck } from "../icons";
import { categoryLabel, reportStatus, supportLabel, supportStatus, type StatusCopy } from "../lib/status";
import { formatWhen } from "../lib/time";
import { PhotoGallery } from "../PhotoGallery";

export function ReceiptScreen(props: ReceiptScreenProps) {
  const { receipt, go } = props;
  return receipt.kind === "report" ? (
    <ReportReceiptView receipt={receipt.receipt} go={go} />
  ) : (
    <SupportReceiptView receipt={receipt.receipt} go={go} />
  );
}

function ReportReceiptView({ receipt, go }: { receipt: ReportReceipt; go: (s: Screen) => void }) {
  const r = receipt.report;
  const desc = r.location_description?.trim() || "";
  const where = r.location && desc ? `${r.location.label} — ${desc}` : r.location?.label || desc || "Not given";
  return (
    <ReceiptLayout
      title="Report received"
      lede="The property team has your report. Keep the report number in case you need to ask about it."
      duplicate={receipt.duplicate ? "We already had this report — it wasn't sent twice." : null}
      idLabel="Report number"
      id={r.report_id}
      receivedAt={r.received_at}
      status={reportStatus(r.status)}
      detail={r.public_status_detail}
      go={go}
    >
      <Fact label="Problem">{categoryLabel(r.category)}</Fact>
      <Fact label="Where">{where}</Fact>
      <Fact label="What happened" text>{r.text}</Fact>
      <Fact label="When you noticed it">{r.observed_at ? formatWhen(r.observed_at) : "Not sure"}</Fact>
      <Fact label="Photos">
        {r.media.length ? (
          <PhotoGallery photos={r.media.map(media => ({ id: media.media_id, url: media.url, alt: media.alt }))}
            label="Photos sent with this report" />
        ) : (
          "No photos"
        )}
      </Fact>
    </ReceiptLayout>
  );
}

function SupportReceiptView({ receipt, go }: { receipt: SupportReceipt; go: (s: Screen) => void }) {
  return (
    <ReceiptLayout
      title="Request received"
      lede="The property team has your request. Keep the request number in case you need to ask about it."
      duplicate={receipt.duplicate ? "We already had this request — it wasn't sent twice." : null}
      idLabel="Request number"
      id={receipt.request_id}
      receivedAt={receipt.received_at}
      status={supportStatus(receipt.status)}
      detail={receipt.public_status_detail}
      note="A request isn't a booking or a reservation. The property team will reply, and you'll see it in My updates."
      go={go}
    >
      <Fact label="Help with">{supportLabel(receipt.category)}</Fact>
      <Fact label="What you need" text>{receipt.description}</Fact>
    </ReceiptLayout>
  );
}

function ReceiptLayout(props: {
  title: string;
  lede: string;
  duplicate: string | null;
  idLabel: string;
  id: string;
  receivedAt: string;
  status: StatusCopy;
  detail: string;
  note?: string;
  go: (s: Screen) => void;
  children: ReactNode;
}) {
  return (
    <>
      <main className="r-main has-actionbar">
        <span className="rr-mark" aria-hidden="true">
          <IconCheck size={30} />
        </span>
        <ScreenHead title={props.title} lede={props.lede} />
        {props.duplicate ? <Message tone="info">{props.duplicate}</Message> : null}

        <section className="r-list" aria-label={`${props.idLabel} and status`}>
          <div className="r-row">
            <span className="r-meta">{props.idLabel}</span>
            <span className="rr-id">{props.id}</span>
            <span className="r-meta">
              Received {formatWhen(props.receivedAt)}
            </span>
          </div>
          <div className="r-row">
            <div>
              <StatusPill status={props.status} />
            </div>
            <p>{props.detail}</p>
          </div>
        </section>

        {props.note ? <Message tone="info">{props.note}</Message> : null}

        <section className="r-section" aria-labelledby="rr-h-sent">
          <h2 id="rr-h-sent" className="r-title-sm">What you sent</h2>
          <dl className="r-list rr-facts">{props.children}</dl>
        </section>
      </main>
      <ActionBar>
        <button type="button" className="r-btn secondary-narrow" onClick={() => props.go({ name: "home" })}>
          Back to home
        </button>
        <button type="button" className="r-btn primary" onClick={() => props.go({ name: "updates" })}>
          See my updates
        </button>
      </ActionBar>
    </>
  );
}

function Fact({ label, text, children }: { label: string; text?: boolean; children: ReactNode }) {
  return (
    <div className="r-row">
      <dt className="r-meta">{label}</dt>
      <dd className={text ? "rr-text" : undefined}>{children}</dd>
    </div>
  );
}
