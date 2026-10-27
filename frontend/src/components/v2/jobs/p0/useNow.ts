"use client";

import { useEffect, useState } from "react";

/** Bieżący czas odświeżany co `everyMs` — licznik „P0 · 23 h” na wiszącej karcie. */
export function useNow(everyMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}
