// Zakładka „Podobni” na profilu kandydata (22.10.2026).
//
// Backend: `app/api/candidate_similar.py`, reguła w
// `services/similar_candidates.py`. Podobny ≠ pasujący: lista nie zależy od
// żadnej rekrutacji, a sprawdzenie pod rekrutację (umiejętności krytyczne,
// karta w rekrutacji) to osobne zapytanie. Dodanie idzie wspólną trasą
// `proposals/bulk` ze źródłem `similar_candidates` — osoba bez krytycznej
// wchodzi tylko ze zdaniem w `reasons` (inaczej 422 `critical_reason_required`).

import { api } from "@/lib/api";

export type SimilarityLevel = "very" | "similar" | "partial";

/** Fakty osoby do porównania — te same pola dla osoby z profilu i podobnych. */
export interface SimilarPerson {
  id: number;
  name: string | null;
  lastname: string | null;
  title: string | null;
  company: string | null;
  city: string | null;
  location: string | null;
  years_it_experience: number | null;
  competence_category: string | null;
  rate_hourly: number | null;
  rate_currency: string | null;
  availability_status: string | null;
  availability_date: string | null;
  active_processes: number;
}

export interface SimilarCandidate extends SimilarPerson {
  score: number;
  level: SimilarityLevel;
  /** Kanoniczne nazwy (małe litery) — do pokazania przez słownik umiejętności. */
  shared_skills: string[];
  only_source_skills: string[];
  only_candidate_skills: string[];
}

export interface SimilarCandidatesResponse {
  candidate_id: number;
  /** `no_vector` — osoba nie ma jeszcze wektora CV; `unavailable` — wyszukiwarka nie odpowiedziała. */
  status: "ok" | "no_vector" | "unavailable";
  total: number;
  /** Osoba z profilu — druga kolumna porównania. */
  source: SimilarPerson;
  items: SimilarCandidate[];
}

export interface SimilarFilters {
  hideNotLooking: boolean;
  withoutProcess: boolean;
  rateMax: number | null;
  city: string;
}

export const DEFAULT_SIMILAR_FILTERS: SimilarFilters = {
  hideNotLooking: true,
  withoutProcess: false,
  rateMax: null,
  city: "",
};

/** Strona zakładki = najwięcej osób, o które pyta jedna ocena dopasowania. */
export const SIMILAR_PAGE_SIZE = 20;

export type CriticalStatus = "met" | "missing" | "unknown";

export interface CriticalItem {
  label: string;
  status: CriticalStatus;
  /** `profile` / `cv` / `note`. */
  sources: string[];
}

export interface CandidateCheck {
  candidate_id: number;
  critical: CriticalItem[];
  missing: string[];
  in_job: { label: string; column: string; closed: boolean } | null;
}

export interface JobCheck {
  job_id: number;
  critical_labels: string[];
  candidates: CandidateCheck[];
}

/** Najwięcej par osoba × rekrutacja w jednym sprawdzeniu (`CHECK_MAX_PAIRS`). */
export const SIMILAR_CHECK_MAX_PAIRS = 200;

export const similarCandidatesApi = {
  list: (
    candidateId: number,
    filters: SimilarFilters,
    offset: number,
    signal?: AbortSignal,
  ): Promise<SimilarCandidatesResponse> =>
    api
      .get<SimilarCandidatesResponse>(`/api/candidates/${candidateId}/similar`, {
        params: {
          hide_not_looking: filters.hideNotLooking,
          without_process: filters.withoutProcess,
          ...(filters.rateMax ? { rate_max: filters.rateMax } : {}),
          ...(filters.city.trim() ? { city: filters.city.trim() } : {}),
          offset,
          limit: SIMILAR_PAGE_SIZE,
        },
        signal,
      })
      .then((r) => r.data),
  check: (
    candidateId: number,
    jobIds: number[],
    candidateIds: number[],
  ): Promise<JobCheck[]> =>
    api
      .post<{ jobs: JobCheck[] }>(`/api/candidates/${candidateId}/similar/check`, {
        job_ids: jobIds,
        candidate_ids: candidateIds,
      })
      .then((r) => r.data.jobs),
};

/** Podpis stopnia podobieństwa mówi o profilu, nie o osobie — bez zgadywania rodzaju z imienia. */
export const SIMILARITY_LEVEL_LABEL: Record<SimilarityLevel, string> = {
  very: "Bardzo podobny profil",
  similar: "Podobny profil",
  partial: "Częściowo podobny",
};

const SOURCE_LABEL: Record<string, string> = {
  profile: "profil",
  cv: "CV",
  note: "notatka",
};

export function criticalSourcesText(sources: string[]): string {
  return sources.map((s) => SOURCE_LABEL[s] ?? s).join(", ");
}

/** Wynik sprawdzenia jednej osoby pod rekrutację — jedna reguła dla tabeli i okna. */
export type CheckVerdict =
  | { kind: "in_job"; label: string; closed: boolean }
  | { kind: "missing"; missing: string[] }
  | { kind: "met"; met: number; total: number }
  | { kind: "no_critical" };

export function checkVerdict(check: CandidateCheck | undefined | null): CheckVerdict | null {
  if (!check) return null;
  if (check.in_job) {
    return { kind: "in_job", label: check.in_job.label, closed: check.in_job.closed };
  }
  if (check.missing.length > 0) return { kind: "missing", missing: check.missing };
  const checkable = check.critical.filter((c) => c.status !== "unknown");
  if (check.critical.length === 0) return { kind: "no_critical" };
  return {
    kind: "met",
    met: checkable.filter((c) => c.status === "met").length,
    total: checkable.length,
  };
}

export function verdictText(verdict: CheckVerdict): string {
  switch (verdict.kind) {
    case "in_job":
      return verdict.closed ? "Zamknięta karta w tej rekrutacji" : "Już w tej rekrutacji";
    case "missing":
      return verdict.missing.length === 1
        ? `Brak krytycznej: ${verdict.missing[0]}`
        : `Brak ${verdict.missing.length} krytycznych: ${verdict.missing.join(", ")}`;
    case "met":
      return verdict.total > 0
        ? `Spełnia krytyczne ${verdict.met}/${verdict.total}`
        : "Krytyczne do sprawdzenia w rozmowie";
    case "no_critical":
      return "Rekrutacja bez krytycznych";
  }
}
