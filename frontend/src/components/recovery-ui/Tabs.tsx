import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export type TabItem<V extends string> = { value: V; label: string; count?: number };

export type TabsProps<V extends string> = {
  tabs: readonly TabItem<V>[];
  value: V;
  onChange: (v: V) => void;
  ariaLabel: string;
  idBase: string;
  /** Extra: every panel is in the DOM (inactive ones `hidden`), so every tab may point at its panel. */
  allPanelsRendered?: boolean;
};

export const tabId = (idBase: string, value: string) => `${idBase}-tab-${value}`;
export const tabPanelId = (idBase: string, value: string) => `${idBase}-panel-${value}`;

/** role="tablist" with roving tabindex. ArrowLeft/ArrowRight wrap; Home/End jump. Selection follows focus. */
export function Tabs<V extends string>({ tabs, value, onChange, ariaLabel, idBase, allPanelsRendered = false }: TabsProps<V>) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  // If the value matches no tab, keep the first one reachable by Tab.
  const focusable = tabs.some((t) => t.value === value) ? value : tabs[0]?.value;

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (tabs.length === 0) return;
    const current = tabs.findIndex((t) => t.value === value);
    let next: number;
    switch (e.key) {
      case "ArrowRight":
        next = current < 0 ? 0 : (current + 1) % tabs.length;
        break;
      case "ArrowLeft":
        next = current < 0 ? tabs.length - 1 : (current - 1 + tabs.length) % tabs.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = tabs.length - 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    const target = tabs[next].value;
    refs.current.get(target)?.focus();
    if (target !== value) onChange(target);
  };

  return (
    <div role="tablist" aria-label={ariaLabel} className="r-tabs" onKeyDown={onKeyDown}>
      {tabs.map((t) => {
        const selected = t.value === value;
        return (
          <button
            key={t.value}
            ref={(el) => {
              if (el) refs.current.set(t.value, el);
              else refs.current.delete(t.value);
            }}
            type="button"
            role="tab"
            id={tabId(idBase, t.value)}
            aria-selected={selected}
            aria-controls={selected || allPanelsRendered ? tabPanelId(idBase, t.value) : undefined}
            tabIndex={t.value === focusable ? 0 : -1}
            className="r-tab"
            onClick={() => {
              if (!selected) onChange(t.value);
            }}
          >
            {t.label}
            {t.count != null && (
              <span className="r-tab-count">
                <span className="r-sr-only">(</span>
                {t.count}
                <span className="r-sr-only">)</span>
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export type TabPanelProps = {
  idBase: string;
  value: string;
  children: ReactNode;
  className?: string;
  /**
   * Extra: render every panel and hide the inactive ones with the `hidden` attribute, so their local state
   * (drafts, open forms, errors) survives a tab switch. Omit it to render only the selected tab's panel.
   */
  hidden?: boolean;
};

/** The panel for one tab. Either render only the selected tab's panel, or render all and pass `hidden`. */
export function TabPanel({ idBase, value, children, className, hidden = false }: TabPanelProps) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId(idBase, value)}
      aria-labelledby={tabId(idBase, value)}
      tabIndex={hidden ? -1 : 0}
      hidden={hidden}
      className={["r-tabpanel", className].filter(Boolean).join(" ")}
    >
      {children}
    </div>
  );
}
