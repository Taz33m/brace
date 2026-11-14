/**
 * Home: what happened, the property team's latest word, and three ways forward.
 * Kept short so the three actions sit on a 390x844 screen without scrolling past the notice.
 */
import type { PublishedNotice, ResidentHome, ResidentTask } from "../contract";
import { taskStatus } from "../lib/status";
import { formatAgo, formatWhen, parseWhen } from "../lib/time";
import { Choice } from "../ui";
import { IconAlert, IconChevron, IconClock, IconReport, IconSupport, IconUpdates } from "../icons";
import type { HomeScreenProps } from "./types";

/** Bodies longer than this are clamped on Home and point to the full list. */
const LONG_NOTICE = 160;

const time = (v: string) => parseWhen(v)?.getTime() ?? 0;

function newestNotice(notices: PublishedNotice[]): PublishedNotice | null {
  return notices.reduce<PublishedNotice | null>((best, n) => (!best || time(n.published_at) > time(best.published_at) ? n : best), null);
}

/** Items still moving: reports not confirmed/closed, requests not closed, repairs not checked/cancelled. */
function openCount(home: ResidentHome): number {
  const reports = home.reports.filter((r) => r.status !== "verified" && r.status !== "dismissed").length;
  const support = home.support_requests.filter((s) => s.status !== "closed").length;
  const tasks = home.tasks.filter((t) => t.status !== "verified" && t.status !== "cancelled").length;
  return reports + support + tasks;
}

function latestTask(tasks: ResidentTask[]): ResidentTask | null {
  return tasks.reduce<ResidentTask | null>((best, t) => (!best || time(t.updated_at) > time(best.updated_at) ? t : best), null);
}

export function HomeScreen({ home, fresh_ids, go }: HomeScreenProps) {
  const notice = newestNotice(home.notices);
  const open = openCount(home);
  const task = latestTask(home.tasks);
  const hasMore = notice ? notice.body.length > LONG_NOTICE || home.notices.length > 1 : false;

  return (
    <main className="r-main">
      <header className="r-head">
        <h1 className="r-title r-incident" tabIndex={-1} data-screen-title>
          <span className="r-incident-mark" aria-hidden="true">
            <IconAlert size={24} strokeWidth={2} />
          </span>
          <span>{home.incident_name}</span>
        </h1>
        <p className="r-meta r-inline">
          <IconClock size={16} />
          <span>
            Information last updated <time dateTime={home.updated_at}>{formatAgo(home.updated_at)}</time>
          </span>
        </p>
      </header>

      <section className="r-section" aria-labelledby="home-notice-h">
        <h2 id="home-notice-h" className="r-title-sm">From the property team</h2>
        {notice ? (
          <div className="r-list">
            <article className={`r-row${fresh_ids.has(notice.notice_id) ? " is-new" : ""}`}>
              <h3 className="r-row-title">{notice.title}</h3>
              <p className="r-row-body r-clamp-3">{notice.body}</p>
              <p className="r-meta">
                {notice.published_by} · <time dateTime={notice.published_at}>{formatWhen(notice.published_at)}</time>
              </p>
            </article>
            {hasMore ? (
              <button type="button" className="r-row r-row-link" onClick={() => go({ name: "updates" })}>
                <span>Read all updates</span>
                <IconChevron size={20} />
              </button>
            ) : null}
          </div>
        ) : (
          <p className="r-meta">No notices from the property team yet.</p>
        )}
      </section>

      <nav className="r-choices" aria-label="What do you want to do?">
        <Choice
          hero
          icon={<IconReport size={30} />}
          title="Report a problem"
          sub="Water, roof, smoke, power or access"
          trailing={<IconChevron className="r-trail-icon" size={22} />}
          onClick={() => go({ name: "report" })}
        />
        <Choice
          hero
          icon={<IconSupport size={30} />}
          title="Request support"
          sub="Somewhere to stay, access, help with updates"
          trailing={<IconChevron className="r-trail-icon" size={22} />}
          onClick={() => go({ name: "support" })}
        />
        <Choice
          hero
          icon={<IconUpdates size={30} />}
          title="My updates"
          sub={
            task ? (
              <span className="r-clamp-2">
                Latest: {task.title} — {taskStatus(task).label}
              </span>
            ) : (
              "Your reports, requests, repairs and notices"
            )
          }
          trailing={
            open > 0 ? (
              <span className="r-pill info r-num">{open} open</span>
            ) : (
              <IconChevron className="r-trail-icon" size={22} />
            )
          }
          onClick={() => go({ name: "updates" })}
        />
      </nav>
    </main>
  );
}
