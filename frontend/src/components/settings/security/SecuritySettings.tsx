"use client";

/**
 * Ustawienia → System → Bezpieczeństwo (tylko admin, 27.11.2026, raport
 * „Tarcza NEXUSA”): Przegląd i Rutyny, zakładka w adresie `?zakladka=`
 * jak w Importach. „Uruchom pełny skan” otwiera workflow `security-weekly`
 * w GitHub Actions (tam jest przycisk „Run workflow”) — NEXUS nie trzyma
 * tokenu, który może uruchamiać workflowy.
 */

import { useQuery } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useUrlWriter } from "@/lib/url-selection";
import { isForbiddenError } from "@/lib/view-state";

import { SECURITY_OVERVIEW_KEY, type SecurityOverview } from "./security-model";
import { SecurityOverviewPanel } from "./SecurityOverviewPanel";
import { SecurityRoutinesPanel } from "./SecurityRoutinesPanel";

export type SecurityTab = "przeglad" | "rutyny";
export const SECURITY_TAB_PARAM = "zakladka";

export function SecuritySettings() {
  const searchParams = useSearchParams();
  const pathname = usePathname() ?? "/settings";
  const { replaceUrl } = useUrlWriter();
  const tab: SecurityTab = searchParams?.get(SECURITY_TAB_PARAM) === "rutyny" ? "rutyny" : "przeglad";

  const query = useQuery({
    queryKey: SECURITY_OVERVIEW_KEY,
    queryFn: async () => (await api.get<SecurityOverview>("/api/security/overview")).data,
    refetchInterval: 60_000,
  });

  const select = (next: string) => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set(SECURITY_TAB_PARAM, next);
    replaceUrl(`${pathname}?${params.toString()}`);
  };

  const overdue = query.data?.routines_overdue ?? 0;
  const tabs = [
    { value: "przeglad", label: "Przegląd" },
    { value: "rutyny", label: overdue ? `Rutyny (${overdue} po terminie)` : "Rutyny" },
  ];

  return (
    <div className="space-y-4">
      <div className="relative">
        <TabbedNav tabs={tabs} value={tab} onValueChange={select} ariaLabel="Bezpieczeństwo" />
        {query.data ? (
          <Button size="sm" asChild className="mt-2 sm:absolute sm:right-0 sm:top-1 sm:mt-0">
            <a href={query.data.workflow_url} target="_blank" rel="noreferrer">
              Uruchom pełny skan
            </a>
          </Button>
        ) : null}
      </div>
      {query.isError ? (
        <QueryStateNotice
          state={isForbiddenError(query.error) ? "forbidden" : "error"}
          description={isForbiddenError(query.error) ? "Ekran Bezpieczeństwo widzi tylko administrator." : undefined}
          onRetry={() => void query.refetch()}
        />
      ) : query.isPending ? (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-busy="true">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : tab === "rutyny" ? (
        <SecurityRoutinesPanel today={query.data.today} />
      ) : (
        <SecurityOverviewPanel data={query.data} />
      )}
    </div>
  );
}

export default SecuritySettings;
