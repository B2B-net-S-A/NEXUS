/**
 * Fikcyjne dane panelu „Ranking kandydatów” — harness `/preview/ranking-panel`
 * i testy. Osoby, rekrutacje i liczby są zmyślone (repo jest publiczne).
 */
import type {
  RankingMeasurement,
  RankingPanelState,
  RankingPreview,
  RankingPreviewJob,
  RankingPreviewPerson,
} from "@/lib/api";

const PUBLISHED = { semantic: 60, skills: 10, location: 5, threshold: 70 };

export const PREVIEW_JOBS: RankingPreviewJob[] = [
  { job_id: 9001, title: "Senior Java Developer (przykład)", location: "Kraków, hybryda", positives: 3 },
  { job_id: 9002, title: "Tester automatyzujący (przykład)", location: "zdalnie", positives: 4 },
  { job_id: 9003, title: "Analityk biznesowy (przykład)", location: "Warszawa", positives: 2 },
];

function person(
  id: number,
  name: string,
  city: string | null,
  sem: number,
  sk: number,
  loc: number,
  matched: number,
  positive = false,
): RankingPreviewPerson {
  return {
    candidate_id: id,
    vector_rank: id - 100,
    name,
    city,
    positive,
    layers: {
      semantic: [sem, 1, true],
      skills: [sk, 1, true],
      salary: [0.65, 1, false],
      location: [loc, 1, true],
      availability: [0.65, 1, false],
    },
    extra: null,
    factor: 1,
    matched_must: matched,
    must_total: 4,
  };
}

export const PREVIEW: RankingPreview = {
  job_id: 9001,
  title: "Senior Java Developer (przykład)",
  location: "Kraków, hybryda",
  positives: 3,
  renormalize: false,
  people: [
    person(101, "Anna Przykładowa", "Kraków", 0.96, 0.5, 1, 2),
    person(102, "Piotr Testowy", "Katowice", 0.93, 0.4, 0.65, 2),
    person(103, "Tomasz Fikcyjny", "Gdańsk", 0.92, 0.6, 0, 3),
    person(104, "Katarzyna Przykładowa", "Kraków", 0.88, 1, 1, 4, true),
    person(105, "Jan Zmyślony", "Kraków", 0.9, 0.3, 1, 1),
    person(106, "Aleksandra Wzorcowa", "Kraków", 0.86, 0.9, 1, 4, true),
    person(107, "Michał Próbny", "Kraków", 0.89, 0.2, 1, 1),
    person(108, "Ewa Przykładowa", null, 0.84, 1, 0.65, 4, true),
    person(109, "Paweł Testowy", "Wrocław", 0.85, 0.7, 0, 3),
    person(110, "Zofia Fikcyjna", "Kraków", 0.8, 0.8, 1, 3),
    person(111, "Marek Wzorcowy", "Łódź", 0.82, 0.1, 0.5, 0),
    person(112, "Ola Zmyślona", "Kraków", 0.78, 0.6, 1, 2),
  ],
};

export const MEASUREMENT_DONE: RankingMeasurement = {
  id: 3,
  status: "done",
  error: null,
  progress: { done: 120, target: 120 },
  draft: { semantic: 60, skills: 30, location: 5, threshold: 70 },
  baseline: { panel: PUBLISHED, threshold: 70 },
  fresh: true,
  created_at: "2026-10-21T18:36:00+02:00",
  finished_at: "2026-10-21T18:40:12+02:00",
  result: {
    jobs: 120,
    duration_s: 252,
    before: { page1_hit: 85.8, median_first: 4, top50_share: 61, mrr: 0.416, proposals: 1240 },
    after: { page1_hit: 88.3, median_first: 3, top50_share: 60, mrr: 0.431, proposals: 1105 },
    max_drop_pt: 1,
    needs_reason: false,
    biggest_changes: [
      { job_id: 9002, title: "Tester automatyzujący (przykład)", before: 14, after: 4 },
      { job_id: 9004, title: "Administrator SAP (przykład)", before: 2, after: 7 },
    ],
  },
};

export function panelState(overrides: Partial<RankingPanelState> = {}): RankingPanelState {
  return {
    published: {
      weights: PUBLISHED,
      shares: { semantic: 66.67, skills: 11.11, location: 5.56, salary: 16.67, availability: 0 },
      source: "built_in",
      profile_id: null,
      updated_at: null,
      threshold_source: "env",
    },
    draft: null,
    fixed: { salary: 15, availability: 0 },
    limits: { threshold_min: 50, threshold_max: 90 },
    scoped_profiles: [],
    history: [
      {
        id: 1,
        created_at: "2026-10-19T09:00:00+02:00",
        kind: "admin_edit",
        actor_name: "Admin Przykładowy",
        profile_id: 4,
        before: {},
        after: {
          name: "Wagi testowe",
          weights: { semantic: 45, skills: 25, salary: 10, location: 8, availability: 2, champion_fit: 10 },
        },
        reason: null,
        measurement: null,
      },
    ],
    measurement: null,
    can_edit: true,
    ...overrides,
  };
}

export const DRAFT_STATE: RankingPanelState = panelState({
  draft: {
    weights: { semantic: 60, skills: 30, location: 5, threshold: 70 },
    shares: { semantic: 54.55, skills: 27.27, location: 4.55, salary: 13.64, availability: 0 },
    updated_at: "2026-10-21T18:35:00+02:00",
    updated_by_name: "Olga Przykładowa",
    restored_from: null,
  },
  measurement: MEASUREMENT_DONE,
});
