/**
 * My updates: the resident's own repairs, reports and requests, plus published notices.
 * Only what the snapshot already scopes to this household; nothing is added here.
 *
 * Repair wording rules (from lib/status): a proposed task never looks booked, a schedule shows
 * only when the server confirmed one, and a checked repair always carries the
 * "not occupancy clearance" note.
 */
import { useId, useState, type ReactNode } from "react";
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
import { PhotoGallery } from "../PhotoGallery";
import "./updates.css";

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
    <Section key="repairs" id="upd-repairs" title="Repairs" count={tasks.length}>
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
    <Section key="reports" id="upd-reports" title="Your reports" count={reports.length}>
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
    <Section key="requests" id="upd-requests" title="Your requests" count={requests.length}>
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
    <Section key="notices" id="upd-notices" title="Notices" count={notices.length}>
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

  const sections = {
    repairs: { id: "upd-repairs", label: "Repairs", count: tasks.length, content: repairs },
    reports: { id: "upd-reports", label: "Reports", count: reports.length, content: reportSection },
    requests: { id: "upd-requests", label: "Requests", count: requests.length, content: requestSection },
    notices: { id: "upd-notices", label: "Notices", count: notices.length, content: noticeSection },
  };
  // Bring a known property-team response into view; no unread or response-time inference.
  const hasResponse = requests.some((request) => request.status === "responded" && request.public_status_detail);
  const ordered = hasResponse
    ? [sections.requests, sections.reports, sections.repairs, sections.notices]
    : tasks.length === 0 && reports.length > 0
      ? [sections.reports, sections.repairs, sections.requests, sections.notices]
      : [sections.repairs, sections.reports, sections.requests, sections.notices];

  function jumpTo(id: string) {
    const heading = document.getElementById(id);
    heading?.scrollIntoView({ block: "start" });
    heading?.focus({ preventScroll: true });
  }

  return (
    <main className="r-main">
      <ScreenHead
        title="My updates"
        lede={
          <>
            Newest within each section. Reports and requests are ordered by when you sent them.
            {" "}Information last updated{" "}
            <time dateTime={home.updated_at}>{formatAgo(home.updated_at)}</time>.
          </>
        }
      />
      <nav className="r-updates-nav" aria-label="Update sections">
        {ordered.map((section) => (
          <button key={section.id} type="button" onClick={() => jumpTo(section.id)} aria-controls={section.id}>
            <span>{section.label}</span><span className="r-updates-count r-num">{section.count}</span>
          </button>
        ))}
      </nav>
      {ordered.map((section) => section.content)}
    </main>
  );
}

function Section({ id, title, count, children }: { id: string; title: string; count: number; children: ReactNode }) {
  return (
    <section className="r-section" aria-labelledby={id}>
      <h2 id={id} className="r-title-sm r-updates-heading" tabIndex={-1}>
        {title} <span className="r-updates-count r-num">{count}</span>
      </h2>
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
      {report.text ? <ExpandableText text={report.text} label="report" /> : null}
      {where ? (
        <p className="r-meta r-inline">
          <IconPin size={16} />
          <span>{where}</span>
        </p>
      ) : null}
      {report.public_status_detail ? <p className="r-row-body r-prewrap">{report.public_status_detail}</p> : null}
      {photos.length ? (
        <PhotoGallery compact label={`Photos for ${categoryLabel(report.category).toLowerCase()} report`}
          photos={photos.map((photo) => ({ id: photo.media_id, url: photo.url, alt: photo.alt }))} />
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
      {request.description ? <ExpandableText text={request.description} label="request" /> : null}
      {request.public_status_detail ? request.status === "received" ? (
        <p className="r-row-body r-prewrap">{request.public_status_detail}</p>
      ) : (
        <div className="r-team-response">
          <h4 className="r-team-response-label">From the property team</h4>
          <p className="r-row-body r-prewrap">{request.public_status_detail}</p>
        </div>
      ) : null}
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
        Property team · <time dateTime={notice.published_at}>{formatWhen(notice.published_at)}</time>
      </p>
    </li>
  );
}

function ExpandableText({ text, label }: { text: string; label: "report" | "request" }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const long = text.length > 220 || text.split("\n").length > 3;
  return (
    <div className="r-expandable-text">
      <p id={id} className={`r-row-body r-prewrap${long && !expanded ? " r-clamp-3" : ""}`}>{text}</p>
      {long ? (
        <button type="button" className="r-btn quiet r-expand-toggle" aria-expanded={expanded} aria-controls={id}
          onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show less" : `Read full ${label}`}
        </button>
      ) : null}
    </div>
  );
}
