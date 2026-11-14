import type { ReactNode } from "react";

/** Conspicuous hatched banner. Used only by the preview, to mark synthetic fixture data. */
export function FixtureBanner({ children }: { children: ReactNode }) {
  return (
    <div role="note" className="r-fixture">
      <span className="r-fixture-hatch" aria-hidden="true" />
      <span className="r-fixture-text">{children}</span>
      <span className="r-fixture-hatch" aria-hidden="true" />
    </div>
  );
}
