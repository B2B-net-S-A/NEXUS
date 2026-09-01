"use client";

/**
 * Harness designu edytora Profilu Championa — siedem sekcji (09.2026).
 *
 * Renderuje PRAWDZIWY `ChampionProfileEditor`, ale przy renderze nie rusza
 * sieci: cache react-query jest zasiany z góry (`setQueryData` + `staleTime:
 * Infinity`), więc żaden `queryFn` się nie odpala. To warunek wejścia do
 * `PUBLIC_PATHS` w middleware.ts — stronę otwiera Playwright bez sesji.
 *
 * Zasiane są WSZYSTKIE zapytania, jakie robi edytor i jego podpanele
 * (`champion-profile`, `champion-consultant-suggestions`, `job-meeting-notes`,
 * `champion-suggestions`, `notes-attached`, `notes-unlinked`). Pominięcie
 * któregokolwiek daje 401 → przekierowanie na `/login`, czyli harness, którego
 * nie da się obejrzeć.
 *
 * Dwa przypadki obok siebie, bo różnią się dokładnie tym, co ta przebudowa
 * zmieniła:
 *   1. profil w kształcie SPRZED przebudowy (`project_context`, `sourcing`,
 *      płaskie `rate_value`) — serwer migruje go przy odczycie, więc edytor musi
 *      pokazać komplet danych w nowych sekcjach. Tu sekcja 3 jest PUSTA, bo
 *      stary szablon nie miał pola na stack: chip „Brak pozycji" mówi wprost,
 *      że wymagania są wtedy zgadywane z opisu.
 *   2. profil już wypełniony po nowemu — ze stackiem, dyskwalifikatorami
 *      i dokumentami.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";

// Kształt po migracji serwerowej — dokładnie to, co edytor dostaje z API dla
// oferty zaimportowanej w sierpniu 2026.
const MIGRATED_LEGACY: ChampionProfile = {
  ...EMPTY_CHAMPION_PROFILE,
  basics: {
    ...EMPTY_CHAMPION_PROFILE.basics,
    role_name: "Senior Java Developer",
    seniority_min_years: 8,
    rate_value: 122.5,
    work_mode: "hybrydowo",
    onsite_days_per_week: 2,
    candidate_location_pref: "Warszawa",
    language: "PL, EN B2+",
    start_date: "ASAP",
    contract_length: "3-5 miesięcy z przedłużeniem",
  },
  search: {
    keywords: "java, spring boot, kafka, mikroserwisy",
    target_companies: "Asseco, Comarch, Sygnity",
    disqualifiers: ["brak polskiego"],
    notes: "Nie zawężamy do bankowości.",
  },
  // Pusto — stary szablon nie miał sekcji na stack.
  stack: { must: [], nice: [], notes: "" },
  project: {
    about: "Rozbudowa platformy płatności dla banku. Zespół 8 osób.",
    responsibilities: "Rozwój API, code review, on-call co 6 tygodni.",
  },
  screening_questions: [
    {
      id: "q1",
      question: "Ile lat produkcyjnie z Kafką?",
      ideal_answer: "min. 2 lata, własne topiki i konsumenci",
      deal_breaker: "wyłącznie z tutoriali",
    },
  ],
  client: {
    ...EMPTY_CHAMPION_PROFILE.client,
    selling_points: "Greenfield, nowy zespół, długi kontrakt.",
    consultant_insight: "Zespół rozproszony, dużo spotkań rano.",
    historical_questions: "Pytali o Kafkę i o Kubernetes.",
    priority_rules: "Kandydaci z bankowością w pierwszej kolejności",
    cv_language: "PL",
    sectors: ["banking"],
  },
  documents: [],
};

const FILLED_NEW: ChampionProfile = {
  ...MIGRATED_LEGACY,
  stack: {
    must: [{ name: "Java" }, { name: "Spring Boot" }, { name: "Kafka" }],
    nice: [{ name: "Kubernetes" }, { name: "AWS" }],
    notes: "Java 17+, Java 8 nie interesuje",
  },
  documents: [
    { name: "NDA klienta", url: "https://b2bnetsa.sharepoint.com/nda" },
    { name: "Wzór CV klienta", url: "https://b2bnetsa.sharepoint.com/cv" },
  ],
};

const EMPTY_LIST: unknown[] = [];

export default function ChampionProfilePreviewPage() {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    for (const [jobId, profile] of [
      [1, MIGRATED_LEGACY],
      [2, FILLED_NEW],
    ] as const) {
      qc.setQueryData(["champion-profile", jobId], {
        job_id: jobId,
        job_title: "Senior Java Developer",
        champion_profile: profile,
      });
      qc.setQueryData(["champion-consultant-suggestions", jobId], EMPTY_LIST);
      qc.setQueryData(["job-meeting-notes", jobId], EMPTY_LIST);
      qc.setQueryData(["champion-suggestions", jobId], EMPTY_LIST);
      qc.setQueryData(["notes-attached", jobId], EMPTY_LIST);
      // Panel podobnych ról ma przełącznik „ten klient / wszyscy klienci", a
      // `crossClient` wchodzi w klucz — zasianie jednego wariantu zostawia drugi
      // niezasiany, więc pierwsze kliknięcie strzeliłoby do API.
      for (const crossClient of [false, true]) {
        qc.setQueryData(["champion-historical-matches", jobId, crossClient], {
          matches: [],
          consistent_must: [],
          consistent_nice: [],
        });
      }
    }
    qc.setQueryData(["notes-unlinked"], EMPTY_LIST);
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-5xl flex-col gap-8 p-6">
        <header>
          <h1 className="text-lg font-semibold text-foreground">
            Profil Championa — siedem sekcji
          </h1>
          <p className="text-xs text-muted-foreground">
            Harness designu. Wyłącznie zahardkodowane mocki, zero wywołań API.
          </p>
        </header>

        <section
          className="rounded-xl border border-dashed border-border p-4"
          data-testid="case-migrated-legacy"
        >
          <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted-foreground">
            1. Profil sprzed przebudowy, zmigrowany przy odczycie — sekcja 3 pusta
          </h2>
          <ChampionProfileEditor jobId={1} canEdit clientId={null} />
        </section>

        <section
          className="rounded-xl border border-dashed border-border p-4"
          data-testid="case-filled-new"
        >
          <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted-foreground">
            2. Profil wypełniony po nowemu — stack, dyskwalifikatory, dokumenty
          </h2>
          <ChampionProfileEditor jobId={2} canEdit clientId={null} />
        </section>
      </main>
    </QueryClientProvider>
  );
}
