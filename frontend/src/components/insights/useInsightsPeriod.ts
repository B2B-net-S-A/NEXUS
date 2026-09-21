"use client";

import { useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  readPeriodFromParams,
  writePeriodToParams,
} from "@/lib/insights-period-url";
import type { InsightsPeriodParams } from "@/lib/insights-api";

/**
 * Okres rozdziału / zakładki Insights czytany z URL-a.
 *
 * URL jest jedynym źródłem prawdy okresu — back/forward odtwarza wybór,
 * a link da się udostępnić. `fallback` to JEDNA stała dla odczytu i dla
 * „Resetu" w `PeriodPicker`: rozdzielone, „Reset" wracał do czegoś, od czego
 * widok nigdy nie zaczyna.
 */
export function useInsightsPeriod(fallback: InsightsPeriodParams): {
  period: InsightsPeriodParams;
  setPeriod: (next: InsightsPeriodParams) => void;
} {
  const router = useRouter();
  const searchParams = useSearchParams();

  const period = useMemo(
    () => readPeriodFromParams(searchParams, fallback),
    [searchParams, fallback],
  );

  const setPeriod = useCallback(
    (next: InsightsPeriodParams) => {
      const params = writePeriodToParams(searchParams, next);
      router.push(`/insights?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  return { period, setPeriod };
}
