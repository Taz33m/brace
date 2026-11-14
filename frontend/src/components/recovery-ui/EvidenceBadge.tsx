export type EvidenceBadgeProps = {
  label: string;
  /** Short kind, e.g. "Resident photo". Shown as a small caps prefix. */
  kindLabel?: string;
  /** Already-formatted date text. */
  date?: string;
  selected?: boolean;
  onClick?: () => void;
  title?: string;
};

/** A compact evidence chip. A <button aria-pressed> when clickable, otherwise a plain span. */
export function EvidenceBadge({ label, kindLabel, date, selected = false, onClick, title }: EvidenceBadgeProps) {
  const inner = (
    <>
      {kindLabel && <span className="r-evidence-kind">{kindLabel}</span>}
      <span className="r-evidence-label">{label}</span>
      {date && <span className="r-evidence-date">{date}</span>}
    </>
  );
  const classes = ["r-evidence", selected && "is-selected"].filter(Boolean).join(" ");
  if (onClick) {
    return (
      <button type="button" className={classes} aria-pressed={selected} title={title} onClick={onClick}>
        {inner}
      </button>
    );
  }
  return (
    <span className={classes} title={title}>
      {inner}
    </span>
  );
}
