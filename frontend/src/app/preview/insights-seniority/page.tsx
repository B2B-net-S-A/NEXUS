"use client";

/**
 * Harness sekcji Ścieżka rozwoju — WYŁĄCZNIE zasiane mocki, zero zapytań.
 *
 * Powstał dla ostrzeżenia o SPADKU poziomu. Tej powierzchni nie da się obejrzeć
 * inaczej: sekcja jest za logowaniem, a regresja wymaga danych, których w bazie
 * nie ma i których nie da się wyklikać — poziom spada dopiero wtedy, gdy ktoś
 * przepisze historię atrybucji, a dziennik zauważy to w nocnym przebiegu.
 *
 * Trzy przypadki obok siebie, bo różnicę między nimi łatwo zepsuć niezauważenie:
 *
 * 1. **Bez regresji → NIC.** Nie pusta ramka „0 spadków”, bo pusta ramka uczy
 *    ignorować to miejsce, a wtedy realny spadek też przejdzie niezauważony.
 * 2. **Jedna osoba** — komunikat w liczbie pojedynczej, obie liczby placementów
 *    („14 → 9”). Samo „spadł na seniora” nie mówi, o ile.
 * 3. **Kilka osób naraz** — tak wygląda skutek importu, który przepisał
 *    atrybucję hurtem. To jest typowa, a nie brzegowa sytuacja.
 *
 * Kontrast jest tu rzeczą do OBEJRZENIA: ostrzeżenie stoi na parze
 * `bg-warning-muted` / `text-warning-muted-foreground`, a nie na `bg-warning`
 * + `text-warning-foreground` (ok. 1,9:1 w jasnym motywie — ten sam regres
 * naprawiano już w banerze kampanii).
 *
 * Gałęzi AWARII tu NIE MA — świadomie, tak jak w `/preview/dl-alerts`:
 * przypadek błędu wymagałby, żeby komponent poleciał po dane, a jego własne
 * `queryFn` wygrywa z domyślnym z QueryClienta. Na wdrożonym środowisku takie
 * zapytanie wróciłoby 401, a interceptor axiosa przerzuciłby CAŁĄ stronę na
 * /login — publiczny podgląd wylogowałby oglądającego.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { InsightsSeniority } from "@/components/insights/sections/InsightsSeniority";
import type {
  SeniorityRegression,
  SeniorityResponse,
} from "@/lib/insights-api";

const BASE: SeniorityResponse = {
  as_of: "2026-09-01",
  thresholds: {
    senior_placements: 6,
    senior_window_months: 6,
    expert_placements: 12,
    expert_window_months: 6,
    senior_alt_placements: 12,
    senior_alt_window_months: 12,
    expert_alt_placements: 24,
    expert_alt_window_months: 12,
  },
  window: {
    senior: { months: 6, start_month: "2026-04", end_month: "2026-09" },
    expert: { months: 6, start_month: "2026-04", end_month: "2026-09" },
  },
  entries: [
    {
      user_id: 1,
      name: "Marcin Kraszewski",
      role: "recruiter",
      level: "expert",
      total_placements: 121,
      first_placement_month: "2024-02",
      placements_in_senior_window: 9,
      placements_in_expert_window: 9,
      placements_to_next_level: null,
      progress_pct: null,
      senior_since: "2024-07",
      expert_since: "2025-01",
    },
    {
      user_id: 2,
      name: "Malwina Jobda",
      role: "recruiter",
      level: "senior",
      total_placements: 71,
      first_placement_month: "2024-05",
      placements_in_senior_window: 4,
      placements_in_expert_window: 4,
      placements_to_next_level: 8,
      progress_pct: 33.3,
      senior_since: "2024-11",
      expert_since: null,
    },
    {
      user_id: 3,
      name: "Igor Twardowski",
      role: "sourcer",
      level: "junior",
      total_placements: 3,
      first_placement_month: "2026-05",
      placements_in_senior_window: 3,
      placements_in_expert_window: 3,
      placements_to_next_level: 3,
      progress_pct: 50,
      senior_since: null,
      expert_since: null,
    },
  ],
  totals: { users: 3, levels: { junior: 1, senior: 1, expert: 1 } },
  coverage: {
    unattributed_placements: 0,
    outside_pool_placements: 417,
    note:
      "Poziom liczymy wyłącznie z placementów przypisanych do aktywnych kont " +
      "w rolach sourcer / TAC / rekruter.",
  },
  regressions: [],
};

const ONE: SeniorityRegression = {
  user_id: 1,
  name: "Marcin Kraszewski",
  level: "senior",
  previous_level: "expert",
  total_placements: 9,
  previous_total_placements: 14,
  observed_at: "2026-08-30T02:00:00+00:00",
  thresholds_fingerprint: "6-6-12-6-12-12-24-12",
};

const MANY: SeniorityRegression[] = [
  ONE,
  {
    user_id: 2,
    name: "Malwina Jobda",
    level: "junior",
    previous_level: "senior",
    total_placements: 4,
    previous_total_placements: 11,
    observed_at: "2026-08-30T02:00:00+00:00",
    thresholds_fingerprint: "6-6-12-6-12-12-24-12",
  },
  {
    user_id: 3,
    name: "Kinga Szmulik",
    level: "junior",
    previous_level: "expert",
    total_placements: 2,
    previous_total_placements: 19,
    observed_at: "2026-08-30T02:00:00+00:00",
    thresholds_fingerprint: "6-6-12-6-12-12-24-12",
  },
];

function Preview({
  title,
  why,
  regressions,
}: {
  title: string;
  why: string;
  regressions: SeniorityRegression[];
}) {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { staleTime: Infinity, retry: false, refetchOnMount: false },
      },
    });
    // Klucz MUSI być zasiany. Niezasiany nie ma `dataUpdatedAt`, więc
    // `staleTime: Infinity` go nie powstrzymuje i poleciałoby prawdziwe
    // zapytanie — na wdrożonym środowisku 401 i przerzucenie na /login.
    qc.setQueryData(["insights", "recruitment", "seniority"], {
      ...BASE,
      regressions,
    });
    return qc;
  }, [regressions]);

  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{why}</p>
      </div>
      <QueryClientProvider client={queryClient}>
        <InsightsSeniority />
      </QueryClientProvider>
    </section>
  );
}

export default function InsightsSeniorityPreview() {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 p-8">
      <header>
        <h1 className="text-lg font-semibold">
          Ścieżka rozwoju — podgląd ostrzeżenia o spadku poziomu
        </h1>
        <p className="text-sm text-muted-foreground">
          Zahardkodowane dane, zero zapytań do API. Przełącz motyw
          jasny/ciemny — kontrast ostrzeżenia jest tu rzeczą do obejrzenia.
        </p>
      </header>

      <Preview
        title="Bez regresji (stan normalny)"
        why="Żadnej ramki. Pusta ramka „0 spadków” uczy ignorować to miejsce, więc realny spadek też przeszedłby niezauważony."
        regressions={[]}
      />

      <Preview
        title="Jedna osoba"
        why="Liczba pojedyncza i OBIE liczby placementów — samo „spadł na seniora” nie mówi, o ile."
        regressions={[ONE]}
      />

      <Preview
        title="Kilka osób naraz"
        why="Tak wygląda skutek importu, który przepisał atrybucję hurtem. Sytuacja typowa, nie brzegowa."
        regressions={MANY}
      />
    </main>
  );
}
