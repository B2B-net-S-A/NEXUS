"use client";

/**
 * „Performance per osoba" + plakietki ostrzeżeń — złożenie DWÓCH niezależnych
 * powierzchni w jeden widok.
 *
 * Osobne zapytania, celowo. Liczby performance (`/api/insights/team-table`)
 * i plakietki (`/api/insights/performance-flags`) mają osobne cykle życia
 * i osobne uprawnienia zapisu. Jedno wspólne zapytanie znaczyłoby, że awaria
 * plakietek przewraca tabelę wyników — a wyniki są tu rzeczą główną.
 *
 * Odwrotny kierunek jest równie ważny i dlatego jest tu `PerformanceFlagsLoadNotice`:
 * gdy padnie zapytanie o plakietki, przy KAŻDYM nazwisku po prostu nic się nie
 * pokaże. To wygląda dokładnie jak „nikt nie ma ostrzeżeń" — zdanie o zespole,
 * którego nikt nie wypowiedział. Pasek nad tabelą mówi wprost, że tej warstwy
 * nie udało się wczytać.
 */

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";

import type { InsightsPeriodParams } from "@/lib/insights-api";
import {
  insightsFlagsApi,
  performanceFlagsQueryKey,
} from "@/lib/insights-flags-api";
import { InsightsTeamTable } from "./InsightsTeamTable";
import {
  InsightsPerformanceFlags,
  PerformanceFlagsLoadNotice,
} from "./InsightsPerformanceFlag";
import { InsightsFlagAdmin } from "./InsightsFlagAdmin";

interface Props {
  period: InsightsPeriodParams;
}

export function InsightsTeamPerformance({ period }: Props) {
  const flagsQuery = useQuery({
    // Plakietki NIE zależą od okresu — ostrzeżenie jest stanem osoby „teraz",
    // a nie wynikiem w oknie. Klucz bez okresu oznacza też, że przełączenie
    // miesiąca nie odpala ich ponownie.
    queryKey: performanceFlagsQueryKey,
    queryFn: () => insightsFlagsApi.list(),
  });

  const flagsByUser = flagsQuery.data?.flags_by_user;
  const flagTypes = flagsQuery.data?.types;

  const renderFlags = useCallback(
    (userId: number) => {
      // Klucz jest STRINGIEM — JSON nie ma kluczy liczbowych. Indeksowanie
      // liczbą dałoby `undefined` przy każdym nazwisku i ciche zero plakietek.
      const flags = flagsByUser?.[String(userId)] ?? [];
      return (
        <>
          {flags.length > 0 && <InsightsPerformanceFlags flags={flags} />}
          {/* Kontrolka admina renderuje się TAKŻE przy zerze plakietek —
              inaczej pierwszego ostrzeżenia nie da się nadać nikomu. Dla
              nie-adminów zwraca `null`, więc wiersz zostaje czysty. */}
          <InsightsFlagAdmin
            userId={userId}
            userName={null}
            flags={flags}
            types={flagTypes ?? []}
          />
        </>
      );
    },
    [flagsByUser, flagTypes],
  );

  return (
    <div className="space-y-2">
      <PerformanceFlagsLoadNotice
        isPending={flagsQuery.isPending}
        isSuccess={flagsQuery.isSuccess}
        isError={flagsQuery.isError}
        error={flagsQuery.error}
        onRetry={() => void flagsQuery.refetch()}
      />
      <InsightsTeamTable period={period} renderFlags={renderFlags} />
    </div>
  );
}
