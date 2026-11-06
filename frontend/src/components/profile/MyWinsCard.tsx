"use client";

/**
 * Profil → „Twoje wygrane” (decyzja Artura 06.11.2026): miejsca na podium
 * zamkniętych okresów Ligi i wyścigów, z kwotą, którą rozliczono. Dane
 * z `competition_winners` przez `GET /api/competitions/my-wins`.
 */

import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Trophy } from "lucide-react";

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { monthYearPl } from "@/lib/date-pl";

export interface MyWin {
  competition_type: string;
  label: string;
  period: string;
  rank: number;
  metric_value: number;
  prize_pln: number;
}

export const myWinsQueryKey = ["competitions", "my-wins"] as const;

/** „październik 2026” dla miesiąca, „Q4 2026” zostaje jak jest. */
export function winPeriodLabel(period: string): string {
  return /^\d{4}-\d{2}$/.test(period) ? monthYearPl(period) : period;
}

export function winPrizeLabel(prize: number): string | null {
  if (!prize) return null;
  return `${String(prize).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} zł`;
}

export function MyWinsCard() {
  const query = useQuery({
    queryKey: myWinsQueryKey,
    queryFn: () => api.get<{ items: MyWin[] }>("/api/competitions/my-wins").then((r) => r.data.items),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  // Bez dostępu do Insights karta nie ma czego pokazać — to nie awaria.
  if (query.isError && isAxiosError(query.error) && query.error.response?.status === 403) return null;

  return (
    <section
      aria-label="Twoje wygrane"
      data-tour="profile.my-wins"
      className="bg-card dark:bg-muted rounded-2xl shadow-xs border border-border dark:border-border p-4 sm:p-6"
    >
      <div className="flex items-center gap-2 mb-4">
        <Trophy className="w-5 h-5 text-muted-foreground" aria-hidden="true" />
        <h2 className="text-xl font-semibold text-foreground dark:text-foreground">Twoje wygrane</h2>
      </div>

      {query.isLoading && <p className="text-sm text-muted-foreground">Ładowanie…</p>}

      {query.isError && (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się pobrać wygranych.")}
        </p>
      )}

      {query.isSuccess && query.data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Jeszcze bez miejsca na podium w Lidze ani w wyścigach.
        </p>
      )}

      {query.isSuccess && query.data.length > 0 && (
        <ul className="divide-y divide-border">
          {query.data.map((win) => {
            const prize = winPrizeLabel(win.prize_pln);
            return (
              <li
                key={`${win.competition_type}-${win.period}`}
                className="flex items-center justify-between gap-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">
                    {win.rank}. miejsce · {win.label}
                  </p>
                  <p className="text-xs text-muted-foreground">{winPeriodLabel(win.period)}</p>
                </div>
                {prize && (
                  <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-bold text-primary tabular-nums">
                    {prize}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default MyWinsCard;
