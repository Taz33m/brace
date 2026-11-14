import { useLayoutEffect, useRef } from "react";

/**
 * Each mounted flow gets a separate signal. Capture it before async work and check it after
 * every await: a new invitation can replace the resident cookie while an old upload is pending.
 * Layout cleanup invalidates the old flow before the replacement screen starts its effects.
 * A new signal on setup also keeps cancelled work cancelled through StrictMode effect replay.
 * This guards follow-up work; the ResidentApi does not support cancelling an in-flight request.
 */
export function useFlowLifetime() {
  const lifetime = useRef<AbortSignal | null>(null);
  useLayoutEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller.signal;
    return () => controller.abort();
  }, []);
  return lifetime;
}
