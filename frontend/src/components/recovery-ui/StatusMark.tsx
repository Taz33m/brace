export type StatusTone = "neutral" | "pending" | "verified" | "attention" | "danger" | "muted" | "info";
export type StatusShape = "filled" | "hollow" | "ring" | "hatched";
/** What model.ts tone helpers return; spread it into <StatusMark {...mark} label=… />. */
export type ToneMark = { tone: StatusTone; shape: StatusShape };

export type StatusMarkProps = { tone: StatusTone; shape?: StatusShape; label: string; className?: string };

/** A compact 9px mark plus its text label. Status is never carried by colour alone. */
export function StatusMark({ tone, shape = "filled", label, className }: StatusMarkProps) {
  return (
    <span className={["r-status", `r-tone-${tone}`, className].filter(Boolean).join(" ")}>
      <span className={`r-mark r-mark--${shape}`} aria-hidden="true" />
      <span className="r-status-label">{label}</span>
    </span>
  );
}
