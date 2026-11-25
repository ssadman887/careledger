"use client";

import { useCallback, useMemo, useRef } from "react";

/**
 * One Idempotency-Key per user intent. The same key is reused if the user retries the same
 * submission (e.g. after a network error), so the server never records the payment twice.
 * Call `reset()` after a success to start a new intent.
 */
export function useIdempotencyKey(): { key: () => string; reset: () => void } {
  const ref = useRef<string | null>(null);
  const key = useCallback(() => {
    ref.current ??= newKey();
    return ref.current;
  }, []);
  const reset = useCallback(() => {
    ref.current = null;
  }, []);
  // Stable identity: callers list this object in effect dependencies.
  return useMemo(() => ({ key, reset }), [key, reset]);
}

export function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
