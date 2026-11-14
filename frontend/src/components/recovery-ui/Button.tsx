import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "default" | "quiet" | "danger";

export type ButtonProps = {
  variant?: ButtonVariant;
  /** While pending the button is disabled, sets aria-busy and shows `pendingLabel ?? "Saving…"`. */
  pending?: boolean;
  pendingLabel?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>;

/** A real <button>. Defaults to type="button" so it never submits a form by accident. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", pending = false, pendingLabel, className, disabled, type = "button", children, ...rest },
  ref,
) {
  const classes = ["r-btn", `r-btn--${variant}`, className].filter(Boolean).join(" ");
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={classes}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
    >
      {pending ? (
        <>
          <span className="r-spinner" aria-hidden="true" />
          {pendingLabel ?? "Saving…"}
        </>
      ) : (
        children
      )}
    </button>
  );
});
