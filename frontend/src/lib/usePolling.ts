"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface PollState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  updatedAt: Date | undefined;
  reload: () => void;
}

/**
 * Fetch on mount, whenever ``key`` changes and every ``intervalMs`` (0 = once).
 * Keeps the last good data on errors so that tiles can show "stale" instead of blank.
 */
export function usePolling<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  key = "",
): PollState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date>();
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetcherRef
      .current(controller.signal)
      .then((result) => {
        setData(result);
        setError(undefined);
        setUpdatedAt(new Date());
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
    };
  }, [tick, key]);

  useEffect(() => {
    if (intervalMs <= 0) return;
    const id = setInterval(() => {
      setTick((t) => t + 1);
    }, intervalMs);
    return () => {
      clearInterval(id);
    };
  }, [intervalMs]);

  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);
  return { data, error, loading, updatedAt, reload };
}
