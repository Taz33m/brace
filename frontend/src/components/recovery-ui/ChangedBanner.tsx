import type { ReactNode } from "react";

export type ChangedTone = "changed" | "stale" | "superseded";

export type ChangedBannerProps = {
  title: string;
  children?: ReactNode;
  /** What no longer holds, shown struck through (e.g. the old scope). */
  previous?: ReactNode;
  tone?: ChangedTone;
  action?: ReactNode;
};

/** Hatched paper banner for something that no longer holds: changed scope, stale or superseded. Static, never animated. */
export function ChangedBanner({ title, children, previous, tone = "changed", action }: ChangedBannerProps) {
  return (
    <div role="status" className={`r-changed r-changed--${tone}`}>
      <span className="r-changed-strip" aria-hidden="true" />
      <p className="r-changed-title">{title}</p>
      {previous != null && previous !== false && (
        <p className="r-changed-prev">
          <span className="r-sr-only">No longer holds: </span>
          <s>{previous}</s>
        </p>
      )}
      {children != null && <div className="r-changed-body">{children}</div>}
      {action != null && <div className="r-changed-action">{action}</div>}
    </div>
  );
}
