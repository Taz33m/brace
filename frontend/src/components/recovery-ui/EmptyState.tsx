import type { ReactNode } from "react";

export type EmptyStateProps = { title: string; children?: ReactNode; action?: ReactNode };

/** A quiet centred message for an empty list or a missing input. */
export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <div className="r-empty">
      <p className="r-empty-title">{title}</p>
      {children != null && <div className="r-empty-body">{children}</div>}
      {action != null && <div className="r-empty-action">{action}</div>}
    </div>
  );
}
