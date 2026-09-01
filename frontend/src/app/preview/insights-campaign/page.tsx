"use client";

/**
 * Harness designu banera kampanii — WYŁĄCZNIE zasiane mocki, zero zapytań.
 *
 * Baner i plakietki ostrzeżeń to jedyne dwie nowe powierzchnie Rekrutacji,
 * których nie da się obejrzeć bez zalogowania i bez danych, których na razie
 * w bazie nie ma (kampanii nikt jeszcze nie założył). Bez harnessa jedynym
 * sposobem sprawdzenia, jak wyglądają, byłoby wdrożenie ich na produkcję
 * i założenie prawdziwej kampanii.
 *
 * Cztery przypadki obok siebie, bo różnicę między nimi łatwo zepsuć
 * niezauważenie:
 *
 * 1. **Brak kampanii → NIC.** Nie pusta ramka „0 / 0", która twierdziłaby,
 *    że kampania trwa i idzie fatalnie.
 * 2. **Awaria ≠ pustka.** 500 renderuje `SectionError`, a nie zniknięcie
 *    baneru — inaczej niedziałający serwer wygląda jak „odwołali kampanię".
 * 3. **Cel przekroczony pokazuje >100%**, a pasek dociera do końca toru —
 *    przycięta liczba zamieniłaby najlepszy wynik w „dokładnie wystarczający".
 * 4. **Cel zerowy daje „—", nie „0%"** — nie da się policzyć procentu, a zero
 *    twierdziłoby, że policzyliśmy i wyszło zero.
 *
 * Kontrast jest tu rzeczą do OBEJRZENIA, nie do przeczytania: baner stał
 * wcześniej na `bg-warning` + `text-warning-foreground`, czyli bieli na
 * bursztynie 50% L (ok. 1,9:1 w jasnym motywie). Ta strona istnieje między
 * innymi po to, żeby taki regres było widać jednym spojrzeniem.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { InsightsCampaignBanner } from "@/components/insights/sections/InsightsCampaignBanner";
import {
  insightsCampaignQueryKeys,
  type InsightsCampaign,
} from "@/lib/insights-campaign-api";

const BASE: InsightsCampaign = {
  id: 1,
  name: "Wakacyjna integracja, polećmy razem do ciepłych krajów!",
  emoji: "🏖️",
  start_date: "2026-07-01",
  end_date: "2026-09-30",
  target_net: 60,
  is_active: true,
  created_at: "2026-06-20T09:00:00+02:00",
  window: {
    kind: "custom",
    start: "2026-07-01T00:00:00+02:00",
    end: "2026-10-01T00:00:00+02:00",
    timezone: "Europe/Warsaw",
  },
  days_remaining: 30,
  has_started: true,
  placements: 49,
  resignations: 19,
  net: 30,
  progress_pct: 50,
  remaining_to_target: 30,
  placements_definition: "first_hired_per_candidate_job",
  placements_definition_note:
    "Placement = PIERWSZE wejście na etap „Zatrudniony” dla pary (kandydat, rekrutacja).",
  resignations_definition: "ended_engagement_by_effective_end_date_v2",
  resignations_definition_note:
    "Rezygnacja = kontrakt, którego dzień faktycznego zakończenia wypada w oknie kampanii. " +
    "Kontrakty zakończone liczą się zawsze; aktywne i kończące się — dopiero od dnia, " +
    "w którym ich data końca nadeszła.",
  net_definition_note: "netto = placementy − rezygnacje",
};

type Case =
  | { kind: "data"; campaign: InsightsCampaign }
  | { kind: "none" }
  | { kind: "error" };

function Preview({
  title,
  why,
  scenario,
}: {
  title: string;
  why: string;
  scenario: Case;
}) {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { staleTime: Infinity, retry: false, refetchOnMount: false },
      },
    });
    if (scenario.kind === "data") {
      qc.setQueryData(insightsCampaignQueryKeys.active(), scenario.campaign);
    } else if (scenario.kind === "none") {
      // `null` = nie ma aktywnej kampanii. To NIE jest to samo co awaria.
      qc.setQueryData(insightsCampaignQueryKeys.active(), null);
    }
    // Gałąź awarii świadomie NIE zasiewa klucza — zamiast tego podaje
    // odrzucający `queryFn`, żeby stan błędu był prawdziwy, a nie udawany.
    return qc;
  }, [scenario]);

  if (scenario.kind === "error") {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          queryFn: () => Promise.reject(new Error("500")),
        },
      },
    });
    return (
      <section className="flex flex-col gap-2">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-xs text-muted-foreground">{why}</p>
        </div>
        <QueryClientProvider client={qc}>
          <InsightsCampaignBanner />
        </QueryClientProvider>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{why}</p>
      </div>
      <QueryClientProvider client={queryClient}>
        <InsightsCampaignBanner />
      </QueryClientProvider>
    </section>
  );
}

export default function InsightsCampaignPreview() {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 p-8">
      <header>
        <h1 className="text-lg font-semibold">
          Baner kampanii — podgląd designu
        </h1>
        <p className="text-sm text-muted-foreground">
          Zahardkodowane dane, zero zapytań do API. Przełącz motyw jasny/ciemny
          — kontrast treści baneru jest tu rzeczą do obejrzenia, nie do
          przeczytania.
        </p>
      </header>

      <Preview
        title="Kampania w toku"
        why="49 placementów, 19 rezygnacji, netto 30 z celu 60 — układ 1:1 z DynaReporterem."
        scenario={{ kind: "data", campaign: BASE }}
      />

      <Preview
        title="Cel przekroczony"
        why="Liczba pokazuje 150%, pasek dociera do końca toru. Przycięcie zamieniłoby najlepszy wynik w „dokładnie wystarczający”."
        scenario={{
          kind: "data",
          campaign: {
            ...BASE,
            name: "Cel pobity",
            net: 90,
            placements: 100,
            resignations: 10,
            progress_pct: 150,
            remaining_to_target: -30,
          },
        }}
      />

      <Preview
        title="Cel zerowy"
        why="„—”, nie „0%”: procentu nie da się policzyć, a zero twierdziłoby, że policzyliśmy."
        scenario={{
          kind: "data",
          campaign: {
            ...BASE,
            name: "Kampania bez celu",
            target_net: 0,
            net: 12,
            progress_pct: null,
            remaining_to_target: -12,
          },
        }}
      />

      <Preview
        title="Brak aktywnej kampanii"
        why="Nie renderuje się NIC. Pusta ramka „0 / 0” twierdziłaby, że kampania trwa i idzie fatalnie."
        scenario={{ kind: "none" }}
      />

      <Preview
        title="Awaria (500)"
        why="Komunikat z ponowieniem, a nie zniknięcie baneru — inaczej niedziałający serwer wygląda jak „odwołali kampanię”."
        scenario={{ kind: "error" }}
      />
    </main>
  );
}
