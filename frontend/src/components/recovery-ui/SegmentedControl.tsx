export type SegmentedOption<V extends string> = { value: V; label: string; disabled?: boolean };

export type SegmentedControlProps<V extends string> = {
  options: readonly SegmentedOption<V>[];
  value: V;
  onChange: (v: V) => void;
  ariaLabel: string;
};

/** A sunken pill group; the active segment is a dark ink pill. Each segment is an aria-pressed button. */
export function SegmentedControl<V extends string>({ options, value, onChange, ariaLabel }: SegmentedControlProps<V>) {
  return (
    <div role="group" aria-label={ariaLabel} className="r-seg">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            className="r-seg-btn"
            aria-pressed={active}
            disabled={o.disabled}
            onClick={() => {
              if (!active) onChange(o.value);
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
