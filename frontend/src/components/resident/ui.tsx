/** Small shared pieces so every resident screen uses the same vocabulary. */
import type { ReactNode } from "react";
import type { StatusCopy } from "./lib/status";
import { IconAlert, IconCheck, IconInfo } from "./icons";

export function StatusPill({ status }: { status: StatusCopy }) {
  return <span className={`r-pill ${status.tone}`}>{status.label}</span>;
}

export function Message({ tone, children, action }: { tone: "info" | "ok" | "warn" | "bad"; children: ReactNode; action?: ReactNode }) {
  const icon = tone === "ok" ? <IconCheck size={20} /> : tone === "info" ? <IconInfo size={20} /> : <IconAlert size={20} />;
  return (
    <div className={`r-msg ${tone}`} role={tone === "bad" ? "alert" : "status"}>
      {icon}
      <div className="r-msg-body">
        <div>{children}</div>
        {action}
      </div>
    </div>
  );
}

/** Fixed bottom bar for a flow's primary action. Pair with `<main className="r-main has-actionbar">`. */
export function ActionBar({ children }: { children: ReactNode }) {
  return (
    <div className="r-actionbar">
      <div>{children}</div>
    </div>
  );
}

export function ScreenHead({ title, lede }: { title: string; lede?: ReactNode }) {
  return (
    <header className="r-head">
      <h1 className="r-title" tabIndex={-1} data-screen-title>
        {title}
      </h1>
      {lede ? <p className="r-lede">{lede}</p> : null}
    </header>
  );
}

/** A large tappable choice row (home actions, categories, support types). */
export function Choice({
  icon,
  title,
  sub,
  trailing,
  selected,
  hero,
  onClick,
  role,
}: {
  icon: ReactNode;
  title: string;
  sub?: ReactNode;
  trailing?: ReactNode;
  selected?: boolean;
  hero?: boolean;
  onClick: () => void;
  role?: "radio";
}) {
  return (
    <button
      type="button"
      className={`r-choice${hero ? " hero" : ""}`}
      onClick={onClick}
      role={role}
      aria-checked={role === "radio" ? !!selected : undefined}
      aria-pressed={role === "radio" || selected === undefined ? undefined : selected}
    >
      <span className="r-choice-icon">{icon}</span>
      <span className="r-choice-text">
        <span className="r-choice-title">{title}</span>
        {sub ? <span className="r-choice-sub">{sub}</span> : null}
      </span>
      {trailing ?? <span />}
    </button>
  );
}
