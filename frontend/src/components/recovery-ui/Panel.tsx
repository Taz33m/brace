import { useId, useState } from "react";
import type { ReactNode } from "react";

export type PanelProps = {
  title: ReactNode;
  /** Optional header content, e.g. a count or a status mark. */
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  headingLevel?: 2 | 3;
};

/** A floating paper card with a header row: title, optional aside, optional collapse caret. */
export function Panel({ title, aside, children, className, collapsible = false, defaultCollapsed = false, headingLevel = 2 }: PanelProps) {
  const [collapsed, setCollapsed] = useState(collapsible && defaultCollapsed);
  const id = useId();
  const headingId = `${id}-title`;
  const bodyId = `${id}-body`;
  const actionId = `${id}-action`;
  const isCollapsed = collapsible && collapsed;
  const Heading = headingLevel === 3 ? "h3" : "h2";
  const classes = ["r-panel", collapsible && "is-collapsible", isCollapsed && "is-collapsed", className].filter(Boolean).join(" ");

  return (
    <section className={classes} aria-labelledby={headingId}>
      <header className="r-panel-head">
        <Heading id={headingId} className="r-panel-title">
          {title}
        </Heading>
        {(aside != null || collapsible) && (
          <span className="r-panel-aside">
            {aside}
            {collapsible && (
              <button
                type="button"
                className="r-icon-btn"
                aria-expanded={!isCollapsed}
                aria-controls={isCollapsed ? undefined : bodyId}
                aria-labelledby={`${actionId} ${headingId}`}
                title={isCollapsed ? "Expand" : "Collapse"}
                onClick={() => setCollapsed((c) => !c)}
              >
                <span id={actionId} className="r-sr-only">
                  {isCollapsed ? "Expand" : "Collapse"}
                </span>
                <svg className="r-caret" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                  <path d="M3.5 6 8 10.5 12.5 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </span>
        )}
      </header>
      {!isCollapsed && (
        <div id={bodyId} className="r-panel-body">
          {children}
        </div>
      )}
    </section>
  );
}
