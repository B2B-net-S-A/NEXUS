"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useHrConfig, type HrConfig } from "@/lib/api/hr";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

/**
 * Wspólne wejście ekranów „Ludzi w NEXUSIE”: czeka na sesję i stan modułów.
 * O dostępie do danych i tak rozstrzyga serwer na każdej trasie.
 */
export function HrConfigGate({ children }: { children: (config: HrConfig) => React.ReactNode }) {
  const hydrated = useAuthStore((state) => state.hydrated);
  const user = useAuthStore((state) => state.user);
  const config = useHrConfig(hydrated && Boolean(user));
  const state = resolveViewState({
    isLoading: !hydrated || config.isLoading,
    isError: config.isError,
    error: config.error,
    isSuccess: config.isSuccess,
  });
  if (state === "loading") {
    return <div className="p-6 text-sm text-muted-foreground">Ładowanie…</div>;
  }
  if (state !== "ready" || !config.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        onRetry={() => config.refetch()}
      />
    );
  }
  // Wyłączony program (`HR_PROGRAM_ENABLED`) wygląda jak nieistniejąca strona.
  if (!config.data.program) return <QueryStateNotice state="not_found" />;
  return <>{children(config.data)}</>;
}
