/**
 * My updates: the resident's own repairs, reports and requests, plus published notices.
 * Only what the snapshot already scopes to this household; nothing is added here.
 *
 * Repair wording rules (from lib/status): a proposed task never looks booked, a schedule shows
 * only when the server confirmed one, and a checked repair always carries the
 * "not occupancy clearance" note.
 */
import type { ReactNode } from "react";
import type { PublishedNotice, ResidentReport, ResidentTask, SupportReceipt, TaskStatus } from "../contract";
import {
  NOT_OCCUPANCY_CLEARANCE,
  categoryLabel,
  reportStatus,
  supportLabel,
  supportStatus,
  taskStatus,
} from "../lib/status";
import { formatAgo, formatWhen, parseWhen } from "../lib/time";
import { Message, ScreenHead, StatusPill } from "../ui";
import { IconClock, IconPin } from "../icons";
import { TaskTimeline } from "./TaskTimeline";
import type { UpdatesScreenProps } from "./types";

const time = (v: string | null) => parseWhen(v)?.getTime() ?? 0;
const newestFirst = <T,>(items: T[], at: (item: T) => string): T[] =>
  [...items].sort((a, b) => time(at(b)) - time(at(a)));

/** Statuses where a confirmed date is still ahead of the work, so "Scheduled for" makes sense. */
const SCHEDULE_RELEVANT: TaskStatus[] = ["approved", "accepted", "in_progress"];
/** Statuses where the work is not booked yet unless the server says otherwise. */
const NOT_BOOKED: TaskStatus[] = ["proposed", "approved", "accepted"];

export function UpdatesScreen({ home, fresh_ids, go }: UpdatesScreenProps) {
  const tasks = newestFirst(home.tasks, (t) => t.updated_at);
  const reports = newestFirst(home.reports, (r) => r.received_at);
  const requests = newestFirst(home.support_requests, (s) => s.received_at);
  const notices = newestFirst(home.notices, (n) => n.published_at);
  const rowClass = (id: string) => `r-row${fresh_ids.has(id) ? " is-new" : ""}`;

  const repairs = (
    <Section key="repairs" id="upd-repairs" title="Repairs">
      {tasks.length ? (
        <ul className="r-list">
          {tasks.map((t) => (
            <TaskRow key={t.task_id} task={t} className={rowClass(t.task_id)} />
          ))}
        </ul>
      ) : (
        <div className="r-empty">
          <p>When the property team plans repair work for your home, its progress shows here.</p>
        </div>
      )}
    </Section>
  );

  const reportSection = (
    <Section key="reports" id="upd-reports" title="Your reports">
      {reports.length ? (
        <ul className="r-list">
          {reports.map((r) => (
            <ReportRow key={r.report_id} report={r} className={rowClass(r.report_id)} />
          ))}
        </ul>
      ) : (
        <div className="r-empty">
          <p>Problems you report about your home show here, with what the property team decides.</p>
          <button type="button" className="r-btn" onClick={() => go({ name: "report" })}>
            Report a problem
          </button>
        </div>
      )}
    </Section>
  );

  const requestSection = (
    <Section key="requests" id="upd-requests" title="Your requests">
      {requests.length ? (
        <ul className="r-list">
          {requests.map((s) => (
            <RequestRow key={s.request_id} request={s} className={rowClass(s.request_id)} />
          ))}
        </ul>
      ) : (
        <div className="r-empty">
          <p>Need somewhere to stay, help getting in, or updates in another form? Ask, and the property team's reply shows here.</p>
          <button type="button" className="r-btn" onClick={() => go({ name: "support" })}>
            Request support
          </button>
        </div>
      )}
    </Section>
  );

  const noticeSection = (
    <Section key="notices" id="upd-notices" title="Notices">
      {notices.length ? (
        <ul className="r-list">
          {notices.map((n) => (
            <NoticeRow key={n.notice_id} notice={n} className={rowClass(n.notice_id)} />
          ))}
        </ul>
      ) : (
        <div className="r-empty">
          <p>When the property team posts news about your building, like water or power shut-offs, it shows here.</p>
        </div>
      )}
    </Section>
  );

  // Most actionable first. With no repairs yet, the resident's own reports lead.
  const ordered =
    tasks.length === 0 && reports.length > 0
      ? [reportSection, repairs, requestSection, noticeSection]
      : [repairs, reportSection, requestSection, noticeSection];

  return (
    <main className="r-main">
      <ScreenHead
        title="My updates"
        lede={
          <>
            Newest first. Information last updated{" "}
            <time dateTime={home.updated_at}>{formatAgo(home.updated_at)}</time>.
          </>
        }
      />
      {ordered}
    </main>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="r-section" aria-labelledby={id}>
      <h2 id={id} className="r-title-sm">{title}</h2>
      {children}
    </section>
  );
}

function TaskRow({ task, className }: { task: ResidentTask; className: string }) {
  const scheduled = task.confirmed_schedule && SCHEDULE_RELEVANT.includes(task.status) ? task.confirmed_schedule : null;
  const notBooked = !task.confirmed_schedule && NOT_BOOKED.includes(task.status);
  return (
    <li className={className}>
      <h3 className="r-row-title">{task.title}</h3>
      <div>
        <StatusPill status={taskStatus(task)} />
      </div>
      {task.public_status_detail ? <p className="r-row-body">{task.public_status_detail}</p> : null}
      {scheduled ? (
        <p className="r-inline r-row-fact">
          <IconClock size={18} />
          <span>
            Scheduled for <time dateTime={scheduled}>{formatWhen(scheduled)}</time>
          </span>
        </p>
      ) : notBooked ? (
        <p className="r-meta">No date booked yet.</p>
      ) : null}
      {task.status !== "cancelled" ? (
        <div className="r-row-steps">
          <TaskTimeline task={task} />
        </div>
      ) : null}
      {task.status === "verified" ? <Message tone="warn">{NOT_OCCUPANCY_CLEARANCE}</Message> : null}
      <p className="r-meta">
        Updated <time dateTime={task.updated_at}>{formatAgo(task.updated_at)}</time>
      </p>
    </li>
  );
}

function ReportRow({ report, className }: { report: ResidentReport; className: string }) {
  const where = report.location?.label ?? report.location_description;
  const photos = report.media.filter((m) => m.mime_type.startsWith("image/"));
  return (
    <li className={className}>
      <h3 className="r-row-title">{categoryLabel(report.category)}</h3>
      <div>
        <StatusPill status={reportStatus(report.status)} />
      </div>
      {report.text ? <p className="r-row-body r-clamp-2">{report.text}</p> : null}
      {where ? (
        <p className="r-meta r-inline">
          <IconPin size={16} />
          <span>{where}</span>
        </p>
      ) : null}
      {report.public_status_detail ? <p className="r-row-body">{report.public_status_detail}</p> : null}
      {photos.length ? (
        <div className="r-thumbs" aria-label={`${photos.length} ${photos.length === 1 ? "photo" : "photos"}`} role="group">
          {photos.slice(0, 4).map((m) => (
            <img key={m.media_id} src={m.url} alt={m.alt} width={56} height={56} loading="lazy" decoding="async" />
          ))}
          {photos.length > 4 ? <span className="r-thumbs-more r-num">+{photos.length - 4}</span> : null}
        </div>
      ) : null}
      <p className="r-meta">
        Sent <time dateTime={report.received_at}>{formatWhen(report.received_at)}</time> · Report{" "}
        <span className="r-num">{report.report_id}</span>
      </p>
    </li>
  );
}

function RequestRow({ request, className }: { request: SupportReceipt; className: string }) {
  return (
    <li className={className}>
      <h3 className="r-row-title">{supportLabel(request.category)}</h3>
      <div>
        <StatusPill status={supportStatus(request.status)} />
      </div>
      {request.description ? <p className="r-row-body r-clamp-2">{request.description}</p> : null}
      {request.public_status_detail ? <p className="r-row-body">{request.public_status_detail}</p> : null}
      <p className="r-meta">
        Sent <time dateTime={request.received_at}>{formatWhen(request.received_at)}</time> · Request{" "}
        <span className="r-num">{request.request_id}</span>
      </p>
    </li>
  );
}

function NoticeRow({ notice, className }: { notice: PublishedNotice; className: string }) {
  return (
    <li className={className}>
      <h3 className="r-row-title">{notice.title}</h3>
      <p className="r-row-body r-prewrap">{notice.body}</p>
      <p className="r-meta">
        {notice.published_by} · <time dateTime={notice.published_at}>{formatWhen(notice.published_at)}</time>
      </p>
    </li>
  );
}
