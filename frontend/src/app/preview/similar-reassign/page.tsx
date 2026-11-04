"use client";

/**
 * Harness panelu „Podobne rekrutacje” (przepięcia jednym kliknięciem,
 * 25.09.2026) — produkcyjny `SimilarJobsPanel` na ZASIANYM cache react-query,
 * bez API i bez logowania. Interceptor odrzuca każde żądanie axiosa, więc
 * kliknięcie „Przepnij” kończy się komunikatem błędu — to podgląd wyglądu.
 *
 * W polu wyszukiwania wpisz „analityk kappa”, żeby zobaczyć wyniki. Dane są
 * fikcyjne — repo jest publiczne.
 *
 * Karta osoby (klik w nazwisko po zaznaczeniu rekrutacji) ma zasiane fakty,
 * dopasowanie i notatki. „Kamil Demo” celowo NIE ma zasianych danych — widać
 * na nim stany awarii każdej sekcji.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import { SimilarJobsPanel } from "@/components/v2/jobs/SimilarJobsPanel";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { jobProposalsKeys, type ProposalFacts } from "@/lib/job-proposals-api";
import type { MatchBreakdown } from "@/lib/match-breakdown";
import {
  similarJobsKey,
  similarPeopleWithRestKey,
  similarPersonScoreKey,
  similarSearchKey,
  type SentPerson,
  type SimilarJobItem,
} from "@/lib/similar-jobs-api";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 5;
// Wymaganie wpisane zdaniem — karta ma je pominąć (tylko technologie).
const PROSE_MUST = "umiejętność dekompozycji wymagań na zadania";

function job(id: number, title: string, overrides: Partial<SimilarJobItem> = {}): SimilarJobItem {
  return {
    id,
    title,
    reference_number: `DEMO-${id}`,
    status: "closed",
    closed_at: null,
    client_name: "Klient Demo",
    similarity: 70,
    sent_count: 0,
    linked: false,
    ...overrides,
  };
}

function person(candidate_id: number, name: string, overrides: Partial<SentPerson> = {}): SentPerson {
  return {
    candidate_id,
    name,
    furthest_stage: "cv_sent",
    sent_at: "2026-09-12",
    outcome: "in_progress",
    already_in_job: false,
    selectable: true,
    sent: true,
    ...overrides,
  };
}

/**
 * Zasiane dane mają znacznik czasu dzień w przód: zapytanie, które zmienia
 * klucz po `staleTime` (wyszukiwarka, kolejna rekrutacja), nie próbuje ich
 * odświeżać — sieć jest wyłączona, więc odświeżenie pokazałoby awarię.
 */
function seedFresh(qc: QueryClient, key: readonly unknown[], data: unknown): void {
  qc.setQueryData(key, data, { updatedAt: Date.now() + 86_400_000 });
}

interface PersonSeed {
  facts: Partial<ProposalFacts>;
  /** `null` = para bez pomiaru („Ocena niepełna”). */
  score: number | null;
  breakdown: MatchBreakdown;
  notes: Array<{ content: string; author_name: string; created_at: string; pinned?: boolean }>;
}

const PEOPLE: Record<number, PersonSeed> = {
  10: {
    facts: {
      title: "Analityk Systemowy",
      years_experience: 8,
      city: "Warszawa",
      max_onsite_days_per_week: 2,
      expected_rate_hourly: 150,
      availability_status: "open_to_offers",
    },
    score: 86,
    breakdown: { total: 86, measurement: "measured", matching_must: ["SQL", "UML", "BPMN"], gap_must: [] },
    notes: [
      {
        content: "Po rozmowie u klienta czeka na odpowiedź. Otwarta na inne projekty w bankowości.",
        author_name: "Marta N.",
        created_at: "2026-09-18T09:30:00Z",
      },
    ],
  },
  11: {
    facts: {
      title: "Analityk Biznesowo-Systemowy",
      company: "Firma Demo",
      years_experience: 6,
      city: "Kraków",
      max_onsite_days_per_week: 0,
      expected_rate_hourly: 140,
      client_history: {
        job_id: 1725,
        title: "Analityk Systemowy",
        furthest_stage: "client_interview",
        furthest_stage_label: "Rozmowa z klientem",
        outcome: "in_progress",
        last_moved_at: "2026-09-03T10:00:00Z",
      },
      cv_uploaded_on: "2023-04-02",
    },
    score: 74,
    breakdown: {
      total: 74,
      measurement: "measured",
      matching_must: ["SQL", "UML"],
      gap_must: ["BPMN", PROSE_MUST],
    },
    notes: [
      {
        content: "Woli pracę w pełni zdalną, do biura najwyżej raz w miesiącu.",
        author_name: "Tomasz R.",
        created_at: "2026-08-30T12:00:00Z",
        pinned: true,
      },
      {
        content: "Rozmowa u klienta 03.09 — dobre wrażenie, czekamy na decyzję.",
        author_name: "Marta N.",
        created_at: "2026-09-04T08:15:00Z",
      },
    ],
  },
  12: {
    facts: { title: "Tester manualny", years_experience: 4, city: "Łódź" },
    score: 38,
    breakdown: { total: 38, measurement: "measured", matching_must: ["SQL"], gap_must: ["UML", "BPMN"] },
    notes: [],
  },
  13: {
    facts: { title: "Analityk Systemowy", years_experience: 5, city: "Gdańsk", expected_rate_hourly: 135 },
    score: null,
    breakdown: { total: null, measurement: "missing_index" },
    notes: [],
  },
  14: {
    facts: { title: "Starszy Analityk", years_experience: 12, city: "Poznań" },
    score: 81,
    breakdown: { total: 81, measurement: "measured", matching_must: ["SQL", "UML", "BPMN"], gap_must: [] },
    notes: [],
  },
  15: { facts: {}, score: 62, breakdown: { total: 62, measurement: "measured" }, notes: [] },
  16: {
    facts: { title: "Analityk Systemowy", years_experience: 9, city: "Wrocław", expected_rate_hourly: 160 },
    score: 79,
    breakdown: { total: 79, measurement: "measured", matching_must: ["SQL", "UML"], gap_must: ["BPMN"] },
    notes: [],
  },
};

function seedPeople(qc: QueryClient): void {
  for (const [key, seed] of Object.entries(PEOPLE)) {
    const id = Number(key);
    const facts: ProposalFacts = {
      candidate_id: id,
      title: null,
      company: null,
      years_experience: null,
      city: null,
      max_onsite_days_per_week: null,
      remote_modes: [],
      availability_status: null,
      availability_date: null,
      expected_rate_hourly: null,
      expected_rate_currency: "PLN",
      expected_rate_redacted: false,
      client_history: null,
      ...seed.facts,
    };
    seedFresh(qc, jobProposalsKeys.facts(JOB_ID, [id]), [facts]);
    seedFresh(qc, similarPersonScoreKey(JOB_ID, id), {
      scores: seed.score === null ? {} : { [String(id)]: seed.score },
      breakdowns: { [String(id)]: seed.breakdown },
      non_technology_must: [PROSE_MUST],
    });
    seedFresh(qc, candidateQueryKeys.quickView(id), {
      recent_notes: seed.notes.map((note, index) => ({ id: id * 10 + index, ...note })),
    });
  }
}

/** Kształt zakładki „Podobne rekrutacje”: wysłani do klienta + „pozostali”. */
function seedPeopleOf(qc: QueryClient, otherId: number, people: SentPerson[]): void {
  seedFresh(qc, similarPeopleWithRestKey(JOB_ID, otherId), {
    people,
    restTotal: people.filter((p) => p.sent === false).length,
  });
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { staleTime: Infinity, retry: false, refetchOnMount: false, refetchOnWindowFocus: false },
    },
  });
  seedFresh(qc, similarJobsKey(JOB_ID), {
    job_id: JOB_ID,
    reassigned_count: 2,
    linked: [job(1500, "Analityk Biznesowy", { linked: true, sent_count: 2, similarity: null })],
    suggestions: [
      job(1725, "Analityk Systemowy", { similarity: 78, sent_count: 3, other_count: 1 }),
      job(1794, "Analityk Systemowy x3", { status: "published", similarity: 71, sent_count: 2 }),
      job(2770, "Analityk Biznesowy Senior", { similarity: 58, sent_count: 0 }),
    ],
  });
  seedPeopleOf(qc, 1725, [
    person(10, "Ewa Przykładowa"),
    person(11, "Tomasz Testowy", { furthest_stage: "client_interview", sent_at: "2026-09-03" }),
    person(12, "Marek Fikcyjny", { outcome: "rejected_by_client", sent_at: "2026-08-20" }),
    // „Pozostali z tej rekrutacji”: doszła do Screeningu, klient jej nie widział.
    person(18, "Lena Szkicowa", { furthest_stage: "screening", sent_at: null, sent: false }),
  ]);
  seedPeopleOf(qc, 1794, [
    person(13, "Agata Demonstracyjna"),
    person(14, "Oskar Wzorcowy", { furthest_stage: "hired", outcome: "hired", selectable: false }),
    person(10, "Ewa Przykładowa"),
  ]);
  seedPeopleOf(qc, 2770, []);
  seedPeopleOf(qc, 1500, [
    person(15, "Kamil Bezdanych", { already_in_job: true, selectable: false }),
  ]);
  seedFresh(qc, similarSearchKey(JOB_ID, "analityk kappa"), [
    job(1837, "Analityk Systemowy", { sent_count: 4, similarity: null }),
    job(2931, "Analityk Biznesowy", { sent_count: 1, similarity: null }),
  ]);
  seedPeopleOf(qc, 1837, [
    person(16, "Piotr Wzorcowy", { sent_at: "2026-07-11" }),
    person(17, "Kamil Demo", { furthest_stage: "client_interview" }),
  ]);
  seedPeople(qc);
  return qc;
}

export default function SimilarReassignPreview() {
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    // Fikcyjna rekruterka: z dostępem do profili nazwisko jest linkiem,
    // a karta osoby ma „Otwórz profil”.
    useAuthStore.setState({
      user: {
        id: 7,
        email: "preview@example.com",
        name: "Marta Nowak",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      hydrated: true,
    });
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <div className="min-h-dvh bg-background p-6">
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={() => setOpen(true)}
          >
            Otwórz „Podobne rekrutacje”
          </button>
          <SimilarJobsPanel jobId={JOB_ID} open={open} onOpenChange={setOpen} />
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}
