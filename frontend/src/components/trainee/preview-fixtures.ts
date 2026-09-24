/**
 * Dane fikcyjne harnessów `/preview/trainee` i `/preview/trainees` (0373).
 * Repo jest publiczne — żadnych prawdziwych nazwisk ani numerów.
 */

import type {
  TraineeCallBody,
  TraineeItem,
  TraineeItemFacts,
  TraineeItemResponse,
  TraineeOpenJob,
  TraineeOutcomeBody,
  TraineeOverview,
  TraineeQualitySampleItem,
  TraineeRules,
  TraineeRulesPreview,
  TraineeToday,
} from "@/lib/api/trainee";
import { recountToday } from "@/lib/trainee-call";

export const PREVIEW_LIST_DATE = "2026-09-24";
export const PREVIEW_NOW = new Date("2026-09-24T10:55:00");
export const PREVIEW_TRAINEE_NAME = "Ola Kamińska";

const EMPTY_FACTS: TraineeItemFacts = {
  min_rate_hourly: null,
  rate_updated_at: null,
  b2b_willingness: null,
  accepts_below_min_rate: null,
  remote_modes: [],
  max_onsite_days: null,
  accepts_more_office_days: null,
  office_cities: [],
  work_time_preference: null,
  availability_status: "unknown",
  availability_date: null,
};

type Seed = [
  name: string,
  role: string,
  company: string,
  city: string,
  phone: string,
  fits: number,
  openFits: number,
  stack: string[],
  missing: TraineeItem["reasons"]["missing"],
  facts?: Partial<TraineeItemFacts>,
];

const OPEN_SEEDS: Seed[] = [
  ["Tomasz Zieliński", "Senior Java Developer", "Comarch", "Kraków", "+48 601 234 518", 6, 2, ["Java", "Spring", "Kafka"], ["rate_stale", "work_time", "availability", "work_mode"], { min_rate_hourly: 140, rate_updated_at: "2025-03-12T09:00:00Z" }],
  ["Magdalena Kowal", "DevOps Engineer (Azure)", "Asseco", "Warszawa", "+48 512 880 314", 5, 1, ["Azure", "Kubernetes", "Terraform"], ["rate_missing", "b2b"]],
  ["Piotr Nowicki", "Analityk biznesowy", "Sii", "Gdańsk", "+48 698 102 447", 4, 1, ["analiza wymagań", "UML", "bankowość"], ["rate_missing", "availability"]],
  ["Agnieszka Lis", "Tester automatyzujący", "Capgemini", "Wrocław", "+48 790 331 206", 4, 0, ["Selenium", "Playwright", "Java"], ["work_mode", "availability"], { min_rate_hourly: 120, rate_updated_at: "2026-01-20T09:00:00Z" }],
  ["Michał Dąbrowski", ".NET Developer", "Atos", "Łódź", "+48 505 774 190", 3, 1, ["C#", ".NET", "Azure"], ["rate_missing"]],
  ["Karolina Wysocka", "Data Engineer", "Allegro", "Poznań", "+48 660 218 953", 3, 0, ["Python", "Spark", "Databricks"], ["rate_stale", "below_min_consent"], { min_rate_hourly: 160, rate_updated_at: "2024-11-05T09:00:00Z" }],
  ["Rafał Mazur", "Kierownik projektu IT", "Orange", "Warszawa", "+48 733 409 861", 3, 0, ["PM", "Scrum", "telekomunikacja"], ["availability", "b2b", "office_consent"]],
  ["Joanna Pawlak", "Frontend Developer (React)", "Netguru", "Katowice", "+48 579 640 125", 2, 1, ["React", "TypeScript"], ["rate_missing", "work_mode"]],
];

const FIRST = ["Anna", "Jan", "Ewa", "Marek", "Kasia", "Paweł", "Zofia", "Adam", "Iga", "Leon"];
const LAST = ["Nowak", "Wójcik", "Kamiński", "Lewandowska", "Zając", "Szymańska", "Król", "Wróbel", "Dudek", "Stępień"];
const ROLES = ["Java Developer", "QA Engineer", "Scrum Master", "Python Developer", "Analityk systemowy", "DevOps Engineer"];
const CITIES = ["Warszawa", "Kraków", "Wrocław", "Poznań", "Gdańsk", "Łódź"];
const CLOSED_OUTCOMES: Array<TraineeItem["outcome"]> = [
  ...Array<TraineeItem["outcome"]>(15).fill("call"),
  ...Array<TraineeItem["outcome"]>(11).fill("noanswer"),
  ...Array<TraineeItem["outcome"]>(3).fill("later"),
  ...Array<TraineeItem["outcome"]>(2).fill("wrong"),
  "declined",
];

function seedItem(id: number, seed: Seed, position: number): TraineeItem {
  const [name, role, company, city, phone, fits, openFits, stack, missing, facts] = seed;
  return {
    id,
    candidate_id: 5000 + id,
    position,
    name,
    role,
    company,
    city,
    phone,
    in_base_since: 2022 + (id % 4),
    last_contact_at: new Date(2025, (id * 3) % 12, 10).toISOString(),
    attempts: 0,
    retry_after: null,
    outcome: null,
    closed_at: null,
    later_date: null,
    reasons: { fits, open_fits: openFits, stack, missing },
    facts: { ...EMPTY_FACTS, ...facts },
  };
}

function fillerItem(id: number, position: number, outcome: TraineeItem["outcome"] | null): TraineeItem {
  const name = `${FIRST[id % FIRST.length]} ${LAST[(id * 7) % LAST.length]}`;
  const closed = outcome != null;
  const callFacts: Partial<TraineeItemFacts> =
    outcome === "call"
      ? {
          b2b_willingness: id % 9 === 0 ? "employment_only" : "b2b",
          min_rate_hourly: 110 + (id % 6) * 10,
          remote_modes: ["hybrid"],
          work_time_preference: "full_time_only",
          availability_status: id % 5 === 0 ? "unknown" : "actively_looking",
        }
      : {};
  return {
    id,
    candidate_id: 5000 + id,
    position,
    name,
    role: ROLES[id % ROLES.length],
    company: "Firma testowa",
    city: CITIES[id % CITIES.length],
    phone: `+48 600 ${String(100 + id).padStart(3, "0")} ${String(200 + id).padStart(3, "0")}`,
    in_base_since: 2023,
    last_contact_at: null,
    attempts: outcome === "noanswer" ? 2 : 0,
    retry_after: null,
    outcome,
    closed_at: closed ? new Date(2026, 8, 24, 8, 10 + (id % 50)).toISOString() : null,
    later_date: outcome === "later" ? "2026-09-29" : null,
    reasons: { fits: 2, open_fits: id % 3 === 0 ? 1 : 0, stack: ["Java"], missing: ["rate_missing"] },
    facts: { ...EMPTY_FACTS, ...callFacts },
  };
}

/** Lista na dziś w połowie dnia: 32 zamknięte, 38 otwartych (jedna po 1. próbie). */
export function previewToday(): TraineeToday {
  const items: TraineeItem[] = [];
  OPEN_SEEDS.forEach((seed, i) => items.push(seedItem(i + 1, seed, i + 1)));
  let id = 100;
  for (let i = 0; i < 30; i += 1) items.push(fillerItem(id++, items.length + 1, null));
  // Jedna osoba po pierwszej próbie — wraca na koniec „Do zrobienia”.
  items[items.length - 1] = {
    ...items[items.length - 1],
    attempts: 1,
    outcome: "noanswer",
    retry_after: "2026-09-24T13:42:00",
  };
  for (const outcome of CLOSED_OUTCOMES) items.push(fillerItem(id++, items.length + 1, outcome));
  return recountToday({
    list_date: PREVIEW_LIST_DATE,
    status: "ready",
    program: { day: 12, total_days: 40, status: "active" },
    counts: { total: 70, closed: 0, open: 70, call: 0, noanswer: 0, later: 0, wrong: 0, declined: 0 },
    day_completed: false,
    answered_pct: 41,
    team_answered_pct: 35,
    items,
  });
}

/** Ten sam dzień po zamknięciu wszystkich pozycji. */
export function previewDoneToday(): TraineeToday {
  const today = previewToday();
  const outcomes: Array<TraineeItem["outcome"]> = ["call", "noanswer", "call", "declined", "call", "wrong", "call", "later"];
  const items = today.items.map((item, i) =>
    item.closed_at
      ? item
      : fillerItem(item.id, item.position, outcomes[i % outcomes.length]),
  );
  return recountToday({ ...today, items, day_completed: true });
}

export const PREVIEW_OPEN_JOBS: TraineeOpenJob[] = [
  { job_id: 4812, title: "Senior Java Developer", recruiter_name: "Marta Nowak", matched_skills: ["Java", "Spring", "Kafka"] },
  { job_id: 4790, title: "Java Developer (Kotlin mile widziany)", recruiter_name: "Paweł Grabowski", matched_skills: ["Java", "Spring"] },
];

const AVAILABILITY_STATUS: Record<NonNullable<TraineeCallBody["availability"]>, string> = {
  now: "actively_looking",
  within_1m: "open_to_offers",
  within_3m: "open_to_offers",
  later: "not_looking",
};

const UNIT_TO_HOURS: Record<"hour" | "day" | "month", number> = { hour: 1, day: 8, month: 168 };

/** Zapis rozmowy w harnessie — ta sama odpowiedź co API, na stanie lokalnym. */
export function applyPreviewCall(
  today: TraineeToday,
  itemId: number,
  body: TraineeCallBody,
): { today: TraineeToday; response: TraineeItemResponse } {
  const items = today.items.map((item) => {
    if (item.id !== itemId) return item;
    const rate = body.min_rate
      ? Math.round(body.min_rate.value / UNIT_TO_HOURS[body.min_rate.unit])
      : item.facts.min_rate_hourly;
    return {
      ...item,
      outcome: "call" as const,
      closed_at: PREVIEW_NOW.toISOString(),
      retry_after: null,
      facts: {
        ...item.facts,
        b2b_willingness: body.b2b_willingness,
        min_rate_hourly: rate,
        accepts_below_min_rate: body.accepts_below_min_rate,
        remote_modes: body.remote_modes,
        max_onsite_days: body.max_onsite_days,
        accepts_more_office_days: body.accepts_more_office_days,
        office_cities: body.office_cities,
        work_time_preference: body.work_time_preference,
        availability_status: body.availability
          ? AVAILABILITY_STATUS[body.availability]
          : item.facts.availability_status,
      },
    };
  });
  return finish(today, items, itemId);
}

/** Wynik bez rozmowy w harnessie (1. próba „Nie odbiera” odkłada o 3 h). */
export function applyPreviewOutcome(
  today: TraineeToday,
  itemId: number,
  body: TraineeOutcomeBody,
): { today: TraineeToday; response: TraineeItemResponse } {
  const items = today.items.map((item) => {
    if (item.id !== itemId) return item;
    if (body.outcome === "noanswer" && item.attempts === 0) {
      return {
        ...item,
        attempts: 1,
        outcome: "noanswer" as const,
        retry_after: new Date(PREVIEW_NOW.getTime() + 3 * 3600 * 1000).toISOString(),
      };
    }
    return {
      ...item,
      attempts: body.outcome === "noanswer" ? 2 : item.attempts,
      outcome: body.outcome,
      closed_at: PREVIEW_NOW.toISOString(),
      retry_after: null,
      later_date: body.later_date ?? null,
    };
  });
  return finish(today, items, itemId);
}

function finish(
  today: TraineeToday,
  items: TraineeItem[],
  itemId: number,
): { today: TraineeToday; response: TraineeItemResponse } {
  const next = recountToday({ ...today, items });
  const dayCompleted = next.counts.open === 0;
  const result = { ...next, day_completed: dayCompleted };
  return {
    today: result,
    response: { item: items.find((i) => i.id === itemId) as TraineeItem, day_completed: dayCompleted },
  };
}

// ── Panel HoR ────────────────────────────────────────────────────────────────

export function previewOverview(): TraineeOverview {
  const program = (day: number, decisionDue = false) => ({
    start_date: "2026-09-01",
    workdays: 40,
    extended_days: 0,
    daily_list_size: 70,
    status: "active",
    day,
    total_days: 40,
    end_date: "2026-10-27",
    decision_due: decisionDue,
  });
  return {
    trainees: [
      { user_id: 7, name: "Kasia Wróbel", is_active: true, program: program(40, true), days_with_list: 40, days_completed: 37, calls_per_day: 27, answered_pct: 38, complete_profiles_pct: 91, handed_over: 11, handed_in_process: 4, quality: { checked: 10, issues: 0 }, flag_low_answer: false },
      { user_id: 8, name: "Ola Kamińska", is_active: true, program: program(12), days_with_list: 12, days_completed: 11, calls_per_day: 29, answered_pct: 41, complete_profiles_pct: 94, handed_over: 3, handed_in_process: 1, quality: { checked: 5, issues: 0 }, flag_low_answer: false },
      { user_id: 9, name: "Bartek Sowa", is_active: true, program: program(12), days_with_list: 12, days_completed: 7, calls_per_day: 18, answered_pct: 22, complete_profiles_pct: 80, handed_over: 0, handed_in_process: 0, quality: { checked: 5, issues: 1 }, flag_low_answer: false },
      { user_id: 10, name: "Natalia Król", is_active: true, program: program(5), days_with_list: 5, days_completed: 5, calls_per_day: 4, answered_pct: 6, complete_profiles_pct: 97, handed_over: 0, handed_in_process: 0, quality: { checked: 3, issues: 2 }, flag_low_answer: true },
    ],
    team_answered_pct: 35,
    pool: {
      size: 8420,
      open_fit: 1310,
      by_category: [
        { name: "Software development", count: 3120 },
        { name: "Infrastruktura i operacje", count: 1980 },
        { name: "Data i AI", count: 1540 },
        { name: "Bezpieczeństwo i jakość", count: 1100 },
        { name: "Zarządzanie i delivery", count: 680 },
      ],
      computed_at: "2026-09-24T06:00:00Z",
    },
    month: { verified_rates: 1184, handed_over: 18, in_process: 6 },
  };
}

export function previewQualitySample(): TraineeQualitySampleItem[] {
  return [
    { item_id: 901, candidate_id: 7001, name: "Leon Dudek", phone: "+48 600 301 401", called_at: "2026-09-22T10:14:00Z", facts: { b2b_willingness: "b2b", min_rate_hourly: 150, remote_modes: ["remote"] }, verdict: null, note: null },
    { item_id: 902, candidate_id: 7002, name: "Iga Stępień", phone: "+48 600 302 402", called_at: "2026-09-22T11:40:00Z", facts: { b2b_willingness: "would_switch", min_rate_hourly: 120 }, verdict: "issue", note: "Kandydatka mówi, że stawki nie podawała." },
    { item_id: 903, candidate_id: 7003, name: "Adam Zając", phone: "+48 600 303 403", called_at: "2026-09-23T09:05:00Z", facts: { b2b_willingness: "employment_only" }, verdict: "ok", note: null },
  ];
}

export const PREVIEW_RULES: TraineeRules = {
  min_fits: 2,
  window_months: 18,
  rate_stale_months: 6,
  verified_recently_days: 90,
  process_active_days: 30,
  my_people_contact_days: 30,
  trainee_recall_days: 60,
  missing_rate: true,
  missing_availability: true,
  missing_work_mode: true,
  missing_consents: true,
  missing_b2b: true,
  missing_work_time: true,
};

/** Podgląd puli — w harnessie maleje z każdą zaostrzoną regułą, żeby było widać ruch. */
export function previewRulesPreview(rules: TraineeRules | null): TraineeRulesPreview {
  const base = previewOverview().pool ?? { size: 0, open_fit: 0, by_category: [] };
  if (!rules) return base;
  const factor =
    (2 / Math.max(1, rules.min_fits)) *
    Math.min(1.5, rules.window_months / 18) *
    (0.55 + 0.075 * [rules.missing_rate, rules.missing_availability, rules.missing_work_mode, rules.missing_consents, rules.missing_b2b, rules.missing_work_time].filter(Boolean).length);
  const scale = (n: number) => Math.round(n * factor);
  return {
    size: scale(base.size),
    open_fit: scale(base.open_fit),
    by_category: base.by_category.map((c) => ({ ...c, count: scale(c.count) })),
  };
}
