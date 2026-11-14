import { Button } from "./Button";

export type InlineErrorProps = {
  message: string;
  onRetry?: () => void;
  retrying?: boolean;
  onDismiss?: () => void;
};

/** A visible, persistent error with optional Retry and Dismiss. role="alert". */
export function InlineError({ message, onRetry, retrying = false, onDismiss }: InlineErrorProps) {
  return (
    <div role="alert" className="r-error">
      <span className="r-error-glyph" aria-hidden="true">
        !
      </span>
      <span className="r-error-text">{message}</span>
      {(onRetry || onDismiss) && (
        <span className="r-error-actions">
          {onRetry && (
            <Button variant="danger" onClick={onRetry} pending={retrying} pendingLabel="Retrying…">
              Retry
            </Button>
          )}
          {onDismiss && (
            <button type="button" className="r-icon-btn" aria-label="Dismiss error" title="Dismiss" onClick={onDismiss} disabled={retrying}>
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
          )}
        </span>
      )}
    </div>
  );
}
