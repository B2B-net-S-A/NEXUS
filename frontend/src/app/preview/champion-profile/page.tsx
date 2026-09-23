"use client";

/**
 * Harness designu edytora Profilu Championa — osiem sekcji (09.2026).
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
 *   2. profil już wypełniony po nowemu — ze stackiem i dyskwalifikatorami.
 *   3. sekcje 4 i 8 (23.09.2026): dziedzina z latami, certyfikaty, notatki
 *      z każdego źródła (weryfikacja tylko do odczytu, „z importu”, „do
 *      dopytania”, „dla kandydata”) i podsumowanie historii klienta. Ten
 *      przypadek ma klienta (`clientId={1}`), więc zasiewa też kartę klienta
 *      i regułę CV z tych samych fixture'ów co `/preview/client-playbook`.
 *
 * Oba przypadki mają `clientId={null}`, więc karta klienta w sekcji 6 się nie
 * renderuje (notka „Wybierz klienta…") — nic z `client-playbook` nie trzeba
 * zasiewać. Dane `documents` w fixture zostają: pole żyje w JSONB nadal.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { clientQuestionPoolQueryKey } from "@/lib/api/interviewCycle";
import { makeClientPlaybook } from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

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

const WITH_INSIGHTS: ChampionProfile = {
  ...FILLED_NEW,
  basics: { ...FILLED_NEW.basics, role_name: "Tester manualny — płatności kartowe" },
  experience: {
    domains: [
      { name: "płatności kartowe", level: "must", min_years: 2, note: "" },
      { name: "bankowość detaliczna", level: "nice", min_years: null, note: "" },
    ],
    certifications: [{ name: "ISTQB Foundation", level: "must", min_years: null, note: "" }],
    regulations: [{ name: "PSD2", level: "nice", min_years: null, note: "" }],
    notes: "Acquiring albo issuing — oba OK.",
  },
  insights: [
    {
      id: "verification:client",
      source: "client",
      topic: "needs",
      audience: "team",
      text: "W mailu „tester automatyzujący”, ale naprawdę 80% to testy manualne procesów kartowych.",
      origin: "verification",
      editable: false,
      author_name: "Anna Delivery",
      created_at: "2026-09-22T10:00:00Z",
    },
    {
      id: "legacy:client.consultant_insight",
      source: "consultant",
      topic: "team",
      audience: "team",
      text: "Zespół 6 osób, stand-up 9:30, dużo spotkań z biznesem.",
      origin: "legacy",
      editable: true,
    },
    {
      id: "n-1",
      source: "client",
      topic: "decision",
      audience: "team",
      text: "Decyduje lead QA; rozmowa techniczna 60 min, zadanie z przypadków testowych.",
      origin: "manual",
      editable: true,
      author_name: "Anna Delivery",
      created_at: "2026-09-22T11:00:00Z",
    },
    {
      id: "n-2",
      source: "consultant",
      topic: "pitch",
      audience: "candidate",
      text: "Stabilny projekt do końca 2027, 4 dni zdalnie.",
      origin: "manual",
      editable: true,
      author_name: "Anna Delivery",
      created_at: "2026-09-22T11:05:00Z",
    },
    {
      id: "n-3",
      source: "client",
      topic: "ask_client",
      audience: "team",
      text: "Ile etapów ma rekrutacja?",
      origin: "ai_intake",
      editable: true,
      done: false,
    },
    {
      id: "n-4",
      source: "client",
      topic: "ask_client",
      audience: "team",
      text: "Czy znajomość PSD2 jest konieczna?",
      origin: "ai_intake",
      editable: true,
      done: true,
    },
  ],
  client_history: {
    status: "ready",
    items: [
      {
        topic: "rejections",
        text: "Klient odrzucał kandydatów bez praktyki w procesach kartowych (chargeback, rozliczenia).",
        basis_count: 4,
      },
      {
        topic: "process",
        text: "Hiring manager docenia konkretne przykłady przypadków testowych z poprzednich projektów.",
        basis_count: 3,
      },
    ],
    debrief_questions: [
      "Jak testowałeś proces chargebacku?",
      "Czym różni się autoryzacja od rozliczenia transakcji?",
    ],
    event_count: 11,
    generated_at: "2026-09-23T07:30:00Z",
    message: null,
  },
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
      [3, WITH_INSIGHTS],
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
      // Pipeline v4: panel „Pytania klienta z rozmów" (pula z debriefów).
      qc.setQueryData(clientQuestionPoolQueryKey("job", jobId, 50), EMPTY_LIST);
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
    qc.setQueryData(["client-playbook", 1], makeClientPlaybook());
    qc.setQueryData(["client-cv-rule", 1], makeCvRule());
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-5xl flex-col gap-8 p-6">
        <header>
          <h1 className="text-lg font-semibold text-foreground">
            Profil Championa — osiem sekcji
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
            2. Profil wypełniony po nowemu — stack, dyskwalifikatory
          </h2>
          <ChampionProfileEditor jobId={2} canEdit clientId={null} />
        </section>

        <section
          className="rounded-xl border border-dashed border-border p-4"
          data-testid="case-experience-insights"
        >
          <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted-foreground">
            3. Doświadczenie poza stackiem + wiedza z rozmów + historia klienta
          </h2>
          <ChampionProfileEditor jobId={3} canEdit clientId={1} />
        </section>
      </main>
    </QueryClientProvider>
  );
}
