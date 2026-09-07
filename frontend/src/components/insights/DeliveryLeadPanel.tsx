"use client";

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import {
  InsightsSection,
  InsightsSectionNav,
} from "@/components/insights/InsightsSectionNav";
import {
  readPeriodFromParams,
  writePeriodToParams,
} from "@/lib/insights-period-url";
import { buildDeliveryLeadsCsvExport } from "@/lib/insights-csv";
import { InsightsHiringManagers } from "@/components/insights/sections/InsightsHiringManagers";
import { InsightsClientsHitRatio } from "@/components/insights/sections/InsightsClientsHitRatio";
import { InsightsDeliveryLeads } from "@/components/insights/sections/InsightsDeliveryLeads";
import { InsightsPlacementsByClient } from "@/components/insights/sections/InsightsPlacementsByClient";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

/**
 * Domyślne okno zakładki — JEDNA stała dla odczytu z URL-a i dla „Resetu".
 *
 * ROK, nie miesiąc. Ranking Delivery Leadów stoi na rekrutacjach ZAMKNIĘTYCH
 * w oknie, a tych w pojedynczym miesiącu jest kilkanaście na cały zespół —
 * hit ratio liczone z takiej próbki skacze o dziesiątki punktów i wygląda jak
 * awaria, a nie jak wynik. DynaReporter pokazywał tu domyślnie wszystkie dane
 * z tego samego powodu.
 */
const DEFAULT_PERIOD: InsightsPeriodParams = { period: "year", offset: 0 };

const SECTIONS = [
  { id: "ranking", label: "Ranking DL" },
  { id: "placementy", label: "Placementy wg klientów" },
  { id: "hit-ratio", label: "Hit ratio per klient" },
  { id: "hiring-managerowie", label: "Hiring managerowie" },
];

export function DeliveryLeadPanel() {
  // URL jest jedynym źródłem prawdy okresu — back/forward odtwarza wybór,
  // a link da się udostępnić. Ten sam wzorzec co w `RekrutacjaPanel`; dawny
  // `PeriodSelector` oferował okna KROCZĄCE („Ostatnie 30 dni"), podczas gdy
  // `/api/insights/*` liczy KALENDARZOWO — etykieta obiecywała co innego niż
  // liczby pod nią.
  const router = useRouter();
  const searchParams = useSearchParams();

  // Odczyt i zapis okresu żyją w JEDNYM module dla trzech zakładek —
  // trzy kopie tej logiki zgubiły wcześniej daty granulacji „Wszystko".
  const period: InsightsPeriodParams = useMemo(
    () => readPeriodFromParams(searchParams, DEFAULT_PERIOD),
    [searchParams],
  );

  const setPeriod = useCallback(
    (next: InsightsPeriodParams) => {
      const params = writePeriodToParams(searchParams, next);
      router.push(`/insights?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  // Etykieta okna pochodzi z SERWERA, nie z arytmetyki we froncie — inaczej
  // dwie strony liczyłyby granice miesiąca osobno i rozjechałyby się przy DST.
  // Klucz jest ten sam co w sekcji rankingu, więc react-query deduplikuje
  // zapytanie zamiast wołać endpoint drugi raz.
  const { data: deliveryLeads } = useQuery({
    queryKey: insightsQueryKeys.deliveryLeads(period),
    queryFn: () => insightsBoardApi.deliveryLeads(period),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Zapytania, wakaty, placementy i hit ratio per Delivery Lead. Ranking
          klientów i MRR są w zakładce Rada Nadzorcza.
        </p>
        <PeriodPicker
          value={period}
          onChange={setPeriod}
          defaultValue={DEFAULT_PERIOD}
          resolved={deliveryLeads?.period ?? null}
          csv={buildDeliveryLeadsCsvExport(deliveryLeads)}
        />
      </div>

      {/* D7 (Artur, 2026-08-31): CZTERY bramki rolowe zdjęte —
          canSeeClientFinance / canSeeHiringManagers / canSeeSales /
          canSeeHitRatio. To były gołe wywołania `hasRole` w ciele panelu, czyli
          lustro ról, którego NIE znajdzie sweep szukający `RequireRole` ani
          tablic `roles:`. Jeśli kiedyś wrócisz do zawężania — zacznij od
          decyzji §0 D7, nie stąd. */}

      <InsightsSectionNav items={SECTIONS} ariaLabel="Sekcje Delivery Leada" />

      <InsightsSection id="ranking">
        <InsightsDeliveryLeads period={period} />
      </InsightsSection>

      <InsightsSection id="placementy">
        <InsightsPlacementsByClient period={period} />
      </InsightsSection>

      <InsightsSection id="hit-ratio">
        <InsightsClientsHitRatio period={period} />
      </InsightsSection>

      {/* Ma już odpowiednik w `/api/insights/*`. Legacy
          `/api/reports/hiring-managers` stoi na trzech rolach (admin / HoR /
          finance) i dla reszty zwracał 403, który ta sekcja renderowała jako
          czerwone „Błąd ładowania. Wymaga roli admin / head_of_recruitment." —
          na zakładce otwartej pod D7 dla KAŻDEJ zalogowanej roli. Guard tamtego
          routera zostaje nietknięty (jest współdzielony poza Insights);
          liczenie jest wspólne (`app/services/insights_hiring_managers.py`).
          Dodatkowo legacy nie znał okresu w ogóle — liczył całą historię pod
          etykietą wybranego okna. */}
      <InsightsSection id="hiring-managerowie">
        <InsightsHiringManagers period={period} />
      </InsightsSection>
    </div>
  );
}
