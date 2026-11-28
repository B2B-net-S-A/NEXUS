"use client";

import { useEffect } from "react";
import { useParams, usePathname } from "next/navigation";
import { IS_STAGING } from "@/components/StagingBadge";
import { useAuthStore } from "@/store/auth";
import {
  apiSupportsCorrelation,
  apiUsageAnalyticsKey,
  probeTelemetryCapability,
} from "@/lib/telemetry-capability";
import {
  routePattern,
  setUsageScreen,
  startUsageAnalytics,
  stopUsageAnalytics,
} from "@/lib/usage-analytics";

/**
 * Pomiar użycia ekranów (PostHog Cloud EU). Startuje tylko dla zalogowanej osoby,
 * poza „Podglądem jako”, poza stagingiem i harnessami `/preview/*`, i tylko gdy API
 * dało klucz (flaga `USAGE_ANALYTICS_ENABLED`). `lib/usage-analytics.ts`.
 */
export function UsageAnalytics() {
  const pathname = usePathname() ?? "/";
  const params = useParams() ?? {};
  const userId = useAuthStore(state => state.user?.id);
  const role = useAuthStore(state => state.user?.role);
  const impersonating = useAuthStore(state => state.realUser !== null);
  const harness = pathname.startsWith("/preview");
  const screen = routePattern(pathname, params);

  useEffect(() => {
    setUsageScreen(screen);
  }, [screen]);

  useEffect(() => {
    if (!userId || !role || impersonating || harness || IS_STAGING) {
      stopUsageAnalytics();
      return;
    }
    let cancelled = false;
    // Po udanej sondzie klucz już jest; nowa sonda byłaby zbędnym żądaniem do API.
    const probed = apiSupportsCorrelation() ? Promise.resolve() : probeTelemetryCapability();
    void probed.then(() => {
      const key = apiUsageAnalyticsKey();
      if (!cancelled && key) void startUsageAnalytics({ key, userId, role });
    });
    return () => {
      cancelled = true;
    };
  }, [userId, role, impersonating, harness]);

  return null;
}
