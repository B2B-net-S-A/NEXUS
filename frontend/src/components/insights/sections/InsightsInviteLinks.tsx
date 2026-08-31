"use client";

import { useQuery } from "@tanstack/react-query";
import { Link2, Loader2, Target, Users } from "lucide-react";
import {
  insightsApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { DefinitionNote, count, pct } from "./InsightsFormat";
import { KpiCard, SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Skuteczność kanałów aplikacyjnych — na `/api/insights/recruitment/invite-links`.
 *
 * Zastępuje `InviteLinksSection`, która wołała `/api/reports/invite-links`
 * (`require_roles(admin, delivery_lead, head_of_recruitment, finance)`), więc
 * recruiter, sourcer, tac i `user` dostawali 403 na otwartej pod D7 stronie.
 * Guard powierzchni legacy zostaje nietknięty.
 *
 * Znika też cała gimnastyka `legacyPeriodFor` z `ZarzadPanel`: tamten endpoint
 * nie znał granulacji rocznej ani przesunięcia okna, więc panel musiał
 * ostrzegać `Degraded`em, że pokazuje BIEŻĄCY okres pod cudzą etykietą. Ten
 * przyjmuje to samo okno co reszta strony.
 */
export function InsightsInviteLinks({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.inviteLinks(period),
    queryFn: () => insightsApi.inviteLinks(period),
  });

  const channels = data?.channels ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: channels.length === 0,
  });

  if (viewState === "loading") {
    return (
      <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      </section>
    );
  }

  if (isBlockingViewState(viewState)) {
    return (
      <SectionError
        label="Linki aplikacyjne"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }

  const totals = data?.totals;

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Link2 className="w-5 h-5 text-primary" />
        Linki aplikacyjne
      </h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="Linki"
          value={count(totals?.links)}
          icon={Link2}
          color="blue"
        />
        <KpiCard
          label="Aplikacje"
          value={count(totals?.applications)}
          icon={Users}
          color="green"
        />
        <KpiCard
          label="Unikalni kandydaci"
          value={count(totals?.candidates)}
          icon={Users}
          color="purple"
        />
        {/* `conversion_pct` z zerowym mianownikiem to `null`, nie `0` — kafel
            renderuje wtedy „—”. Legacy podstawiał tu 0%, czyli twierdził, że
            kanały miały zerową konwersję, gdy nie było ani jednego linku. */}
        <KpiCard
          label="Konwersja"
          value={pct(totals?.conversion_pct)}
          icon={Target}
          color="orange"
        />
      </div>

      <div className="bg-card rounded-xl border border-border shadow-xs">
        <div className="px-6 py-4 border-b border-border space-y-2">
          <h3 className="text-sm font-semibold text-foreground">
            Skuteczność kanałów
          </h3>
          {/* Okno filtruje LINKI, a licznik aplikacji jest kumulatywny na
              linku. Bez tego zdania „Aplikacje” czyta się jako „aplikacje
              w tym okresie”, a jest sumą liczników linków ZAŁOŻONYCH w oknie. */}
          {data?.window_scope?.note && (
            <DefinitionNote>{data.window_scope.note}</DefinitionNote>
          )}
        </div>

        {viewState === "empty" ? (
          <div className="px-6 py-12 text-center text-sm text-muted-foreground">
            Nie wygenerowano żadnych linków w wybranym okresie.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wider text-muted-foreground bg-muted/40">
                <tr>
                  <th className="text-left px-6 py-3 font-medium">Kanał</th>
                  <th className="text-right px-6 py-3 font-medium">Linki</th>
                  <th className="text-right px-6 py-3 font-medium">
                    Aplikacje
                  </th>
                  {/* Ta liczba to aplikacje ÷ linki × 100, więc nagłówek musi
                      pasować do jednostki obok („250,0%”, nie „2,5”) i do
                      etykiety kafla wyżej. */}
                  <th className="text-right px-6 py-3 font-medium">
                    Konwersja
                  </th>
                  <th className="text-left px-6 py-3 font-medium">
                    Ostatnio użyty
                  </th>
                </tr>
              </thead>
              <tbody>
                {channels.map((ch) => (
                  <tr
                    key={ch.channel}
                    className="border-t border-border hover:bg-muted/30"
                  >
                    <td className="px-6 py-3 font-medium text-foreground">
                      {ch.channel}
                      {/* Kubełek linków nieopisanych bywa mylony z kanałem
                          nazwanym „Bez etykiety” — flaga z serwera rozstrzyga. */}
                      {ch.unlabelled && (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          (linki bez etykiety)
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums">
                      {count(ch.links_count)}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums">
                      {count(ch.applications)}
                    </td>
                    <td className="px-6 py-3 text-right tabular-nums">
                      {pct(ch.conversion_pct)}
                    </td>
                    <td className="px-6 py-3 text-muted-foreground">
                      {ch.last_used_at
                        ? new Date(ch.last_used_at).toLocaleDateString(
                            "pl-PL",
                            {
                              day: "2-digit",
                              month: "short",
                              year: "numeric",
                            },
                          )
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
