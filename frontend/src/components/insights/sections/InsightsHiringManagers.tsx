"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Briefcase, Building2, Loader2, Users } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { DefinitionNote, count, pct } from "./InsightsFormat";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Ranking hiring managerów — na `/api/insights/clients/hiring-managers`.
 *
 * Zastępuje `HiringManagersSection`, która wołała `/api/reports/hiring-managers`
 * (`require_roles(admin, head_of_recruitment, finance)`). Dla reszty ról ta
 * sekcja renderowała czerwone „Błąd ładowania. Wymaga roli admin /
 * head_of_recruitment.” na stronie otwartej pod D7 dla każdego zalogowanego.
 * Guard powierzchni legacy zostaje nietknięty — to osobny router, współdzielony
 * poza Insights.
 *
 * Legacy nie znał okresu w ogóle (liczył całą historię). Tutaj okno filtruje
 * rekrutacje po dacie utworzenia, a `contracts_active` pozostaje MIGAWKĄ NA
 * DZIŚ — statusy kontraktów nie mają historii, więc stanu z końca okna nie da
 * się odtworzyć. To musi być napisane przy liczbie, nie przemilczane.
 */
export function InsightsHiringManagers({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.hiringManagers(period),
    queryFn: () => insightsBoardApi.hiringManagers(period),
  });

  const managers = data?.managers ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: managers.length === 0,
  });

  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Users className="w-5 h-5 text-primary" />
        Top hiring managers
        {data && (
          <span className="ml-auto text-xs text-muted-foreground font-normal">
            {count(data.totals.managers)} osób · {count(data.totals.jobs_open)}{" "}
            otwartych rekrutacji
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
          <div className="py-8 flex items-center justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Top hiring managers"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          <Users className="w-12 h-12 mx-auto mb-2 opacity-40" />
          <p className="text-sm">
            Żadna rekrutacja z wybranego okresu nie ma przypisanego hiring
            managera. Wybierz go w polu „Hiring manager” przy tworzeniu
            rekrutacji, żeby zacząć zbierać statystyki.
          </p>
        </div>
      ) : (
        <>
          <div className="border border-border rounded-lg overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 border-b border-border">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">#</th>
                  <th className="text-left px-3 py-2 font-medium">
                    Hiring manager
                  </th>
                  <th className="text-left px-3 py-2 font-medium">Klient</th>
                  <th className="text-right px-3 py-2 font-medium">
                    Rekrutacje
                  </th>
                  <th className="text-right px-3 py-2 font-medium">Otwarte</th>
                  <th className="text-right px-3 py-2 font-medium">
                    Kontrakty
                  </th>
                  <th className="text-right px-3 py-2 font-medium">Aktywni</th>
                  <th className="text-right px-3 py-2 font-medium">
                    Kontrakt / rekrutacja
                  </th>
                </tr>
              </thead>
              <tbody>
                {managers.map((r, idx) => (
                  <tr
                    key={r.contact_id}
                    className="border-b border-border hover:bg-accent/30"
                  >
                    <td className="px-3 py-2 text-muted-foreground tabular-nums">
                      {idx + 1}
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium">{r.contact_name}</div>
                      {r.position && (
                        <div className="text-xs text-muted-foreground">
                          {r.position}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        href={`/clients/${r.client_id}`}
                        className="text-primary hover:underline flex items-center gap-1"
                      >
                        <Building2 className="w-3 h-3" />
                        {r.client_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">
                      {count(r.jobs_total)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {r.jobs_open > 0 ? (
                        <span className="text-green-700 dark:text-green-400">
                          <Briefcase className="w-3 h-3 inline mr-1" />
                          {count(r.jobs_open)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">
                          {count(r.jobs_open)}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {count(r.contracts_total)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-green-700 dark:text-green-400">
                      {count(r.contracts_active)}
                    </td>
                    {/* `null` = zero rekrutacji, czyli brak mianownika →
                        „—”, nigdy „0%”. */}
                    <td className="px-3 py-2 text-right tabular-nums">
                      {pct(r.contract_rate_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Przycięta lista bez licznika czyta się jako komplet. */}
          {data && data.truncated > 0 && (
            <p className="text-xs text-muted-foreground">
              Pokazano {count(managers.length)} z{" "}
              {count(managers.length + data.truncated)} hiring managerów —
              reszta odsiana limitem listy.
            </p>
          )}

          {data?.scope?.note && (
            <DefinitionNote>{data.scope.note}</DefinitionNote>
          )}
        </>
      )}
    </section>
  );
}
