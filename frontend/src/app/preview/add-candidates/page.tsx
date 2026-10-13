"use client";

/**
 * Harness okna „Dodaj kandydatów do pipeline” — imiennicy (13.10.2026).
 *
 * Renderuje PRODUKCYJNE `AddCandidatesQuickModal` na zasianym cache
 * react-query: bez frazy, „Anna Przykładowa” (trzy imienniczki, jedna
 * z zamkniętą kartą w tej rekrutacji, jedna z tym samym numerem) i numer
 * „000 000 102”. Zapis (dodanie, „Przywróć”) odcina strażnik sieci harnessów.
 * Dane są fikcyjne.
 */

import { useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import type {
  CandidateSearchItem,
  CandidateSearchResponse,
  InJobMatch,
  SearchTextInterpretation,
} from "@/lib/candidate-search-api";
import type { CompetenceCategoryOut } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 7301;
const JOB_TITLE = "Architekt środowisk chmurowych · Azure · 6+ lat";
const DAY_MS = 86_400_000;
// Okno trzyma wynik 30 s (`staleTime`) — zasiew „z przyszłości” nie wygasa.
const SEED_FRESH = { updatedAt: Date.now() + DAY_MS };

const CATEGORIES: CompetenceCategoryOut[] = [
  ["infrastructure_operations", "Infra & Operations & Security / Data & AI"],
  ["software_development", "Development"],
  ["security_quality", "QA"],
  ["management_delivery", "Management & Delivery (PM & BA)"],
].map(([slug, name], index) => ({
  id: index + 1,
  slug,
  name_pl: name,
  name_en: name,
  description: "",
  keywords: [],
  display_order: index,
}));

function candidate(id: number, extra: Partial<CandidateSearchItem>): CandidateSearchItem {
  return {
    id,
    name: "Anna",
    lastname: "Przykładowa",
    email: null,
    phone: null,
    location: "Warszawa, PL",
    status: "active",
    availability_status: null,
    source: "traffit",
    competence_category: "infrastructure_operations",
    competence_category_id: 1,
    availability_date: null,
    years_it_experience: null,
    tags: null,
    skills: null,
    languages: null,
    ai_summary: null,
    avatar_url: null,
    relevance_score: 0,
    has_cv: true,
    has_linkedin: false,
    is_champion: false,
    created_at: "2023-05-10T09:00:00Z",
    updated_at: "2026-09-20T09:00:00Z",
    eligibility: null,
    employment_marker: null,
    last_recruitment: null,
    ...extra,
  };
}

const ANNA_WARSAW = candidate(9101, {
  email: "anna.przykladowa@example.com",
  phone: "+48 000 000 101",
  last_recruitment: {
    job_id: 7001,
    job_title: "Administrator Azure",
    stage_label: "Odrzucony",
    column: "closed",
    moved_on: "2026-03-18",
  },
});

const ANNA_CRACOW = candidate(9102, {
  email: "a.przykladowa.dev@example.com",
  phone: "+48 000 000 102",
  location: "Kraków, PL",
  source: "pracuj.pl",
  competence_category: "software_development",
  created_at: "2026-09-04T09:00:00Z",
  last_recruitment: null,
});

const ANNA_DUPLICATE = candidate(9103, {
  email: null,
  phone: "000-000-101",
  created_at: "2021-02-01T09:00:00Z",
  last_recruitment: {
    job_id: 6120,
    job_title: "Administrator sieci",
    stage_label: "CV Wysłane",
    column: "cv_sent",
    moved_on: "2022-06-07",
  },
});

const ANNA_IN_JOB: InJobMatch = {
  id: 9104,
  name: "Anna",
  lastname: "Przykładowa",
  email: "anna.p.cloud@example.com",
  phone: "+48 000 000 103",
  location: "Gdańsk, PL",
  card_label: "Odrzucony 08.10.2026 (Jan Testowy)",
  card_column: "closed",
  closed: {
    candidate_name: "Anna Przykładowa",
    state_version: 2,
    restore_stage: "new",
    restore_stage_def_id: null,
  },
};

const OTHERS: CandidateSearchItem[] = [
  candidate(9110, {
    name: "Jan",
    lastname: "Testowy",
    email: "jan.testowy@example.com",
    phone: "+48 000 000 110",
    location: "Poznań, PL",
    competence_category: "software_development",
  }),
  candidate(9111, {
    name: "Ewa",
    lastname: "Wzorcowa",
    email: "ewa.wzorcowa@example.com",
    phone: null,
    location: "Wrocław, PL",
    competence_category: "security_quality",
    source: "linkedin",
  }),
];

function interpretation(
  kind: SearchTextInterpretation["kind"],
  phone: string | null = null,
): SearchTextInterpretation {
  return {
    kind,
    mode: "literal",
    rule: kind === "phone" ? "phone" : "multi_token_name",
    name: kind === "name" ? ["Anna", "Przykładowa"] : [],
    email: null,
    phone,
    skills: [],
    locations: [],
    other: [],
  };
}

function response(
  items: CandidateSearchItem[],
  extra: Partial<CandidateSearchResponse> = {},
): CandidateSearchResponse {
  return {
    total: items.length,
    page: 1,
    page_size: 25,
    items,
    facets: { competence_categories: [] },
    meta: { ai_status: "ok", took_ms: 12, text_mode_applied: "literal", interpretation: null },
    in_job_matches: [],
    ...extra,
  };
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  qc.setQueryData(["competence-categories-active"], CATEGORIES, SEED_FRESH);
  qc.setQueryData(
    ["add-candidates-quick", JOB_ID, ""],
    response([ANNA_WARSAW, ANNA_CRACOW, ANNA_DUPLICATE, ...OTHERS], {
      total: 1284,
      meta: { ai_status: "ok", took_ms: 12, text_mode_applied: "none", interpretation: null },
    }),
    SEED_FRESH,
  );
  qc.setQueryData(
    ["add-candidates-quick", JOB_ID, "Anna Przykładowa"],
    response([ANNA_WARSAW, ANNA_CRACOW, ANNA_DUPLICATE], {
      meta: {
        ai_status: "ok",
        took_ms: 12,
        text_mode_applied: "literal",
        interpretation: interpretation("name"),
      },
      in_job_matches: [ANNA_IN_JOB],
    }),
    SEED_FRESH,
  );
  qc.setQueryData(
    ["add-candidates-quick", JOB_ID, "000 000 102"],
    response([ANNA_CRACOW], {
      meta: {
        ai_status: "ok",
        took_ms: 12,
        text_mode_applied: "literal",
        interpretation: interpretation("phone", "000000102"),
      },
    }),
    SEED_FRESH,
  );
  return qc;
}

export default function AddCandidatesPreviewPage() {
  const client = useMemo(seededClient, []);
  const [open, setOpen] = useState(true);
  const [ready, setReady] = useState(false);

  // Head of Recruitment: widzi „Profil” i „Scal…”.
  useEffect(() => {
    useAuthStore.setState({
      user: {
        id: 41,
        email: "preview@example.com",
        name: "Anna Wzorcowa",
        role: "head_of_recruitment",
        roles: ["head_of_recruitment"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      realUser: null,
      hydrated: true,
    });
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="mx-auto max-w-3xl space-y-3 bg-background p-6">
          <h1 className="text-lg font-semibold">Harness: okno „Dodaj kandydatów do pipeline”</h1>
          <p className="text-sm text-muted-foreground">
            Wpisz „Anna Przykładowa” (imienniczki, osoba w rekrutacji, ten sam numer) albo
            „000 000 102” (szukanie po numerze).
          </p>
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={() => setOpen(true)}
          >
            Otwórz okno
          </button>
          <AddCandidatesQuickModal
            open={open}
            onClose={() => setOpen(false)}
            jobId={JOB_ID}
            jobTitle={JOB_TITLE}
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
