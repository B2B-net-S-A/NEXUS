/**
 * Treść komórek tabeli kandydatów (22.09.2026) — czyste funkcje, bez Reacta.
 *
 * Zasada wszystkich kolumn: brak danych to „brak" (wyszarzony), nigdy pusta
 * komórka ani zgadnięta wartość. Dawny stos plakietek „brak lokalizacji /
 * stażu / stawki" zastępuje dokładnie to słowo w kolumnie, której dotyczy.
 */

import { formatRelativeTime } from "@/lib/utils";

export interface CandidateRowRecruitment {
  job_id: number;
  job_title: string;
  client_name?: string | null;
  stage: string;
  moved_at?: string | null;
  moved_by_name?: string | null;
}

export interface CandidateRowAvailabilitySource {
  availability_status?: string | null;
  availability_date?: string | null;
  notice_period?: number | null;
  notice_period_unit?: "days" | "weeks" | "months" | null;
  employment?: { state?: string | null; client_name?: string | null } | null;
}

/** Polskie etykiety etapów pipeline'u (klucze API listy). */
export const STAGE_LABELS: Record<string, string> = {
  posting: "Ogłoszenia",
  new: "Nowy",
  prep_call: "Prep call",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview",
  cv_sent: "CV wysłane",
  client_interview: "Rozmowa u klienta",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Wycofany",
};

const TERMINAL_STAGES = new Set(["rejected", "withdrawn", "hired"]);

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

const ddmm = (iso: string): string | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}` : null;
};

/**
 * Dostępność w jednej krótkiej frazie: data „od 01.10" wygrywa, potem okres
 * wypowiedzenia, potem deklaracja. `null` = nie wiemy.
 */
export function availabilityCellText(c: CandidateRowAvailabilitySource): string | null {
  if (c.availability_date) {
    const d = ddmm(c.availability_date);
    if (d) return `od ${d}`;
  }
  if (c.notice_period != null && c.notice_period > 0 && c.notice_period_unit) {
    const units = { days: "dni", weeks: "tyg.", months: "mies." } as const;
    return `za ${c.notice_period} ${units[c.notice_period_unit]}`;
  }
  switch (c.availability_status) {
    case "actively_looking":
      return "szuka aktywnie";
    case "open_to_offers":
      return "otwarty na oferty";
    case "not_looking":
      return "nie szuka";
    default:
      return null;
  }
}

/**
 * Rekrutacje w toku (bez etapów końcowych), od najświeższego ruchu — to samo
 * źródło dla skrótu w komórce i listy po najechaniu.
 */
export function activeRecruitments(
  recruitments: readonly CandidateRowRecruitment[] | null | undefined,
): CandidateRowRecruitment[] {
  return (recruitments ?? [])
    .filter((r) => !TERMINAL_STAGES.has(r.stage))
    .sort(
      (a, b) => (b.moved_at ? Date.parse(b.moved_at) : 0) - (a.moved_at ? Date.parse(a.moved_at) : 0),
    );
}

export interface ProcessCell {
  /** Główna linia („2 procesy · CV wysłane", „Pracuje u nas · PKO BP"). */
  text: string;
  tone: "employed" | "process";
}

function processesWord(n: number): string {
  if (n === 1) return "proces";
  const lastDigit = n % 10;
  const lastTwo = n % 100;
  return lastDigit >= 2 && lastDigit <= 4 && !(lastTwo >= 12 && lastTwo <= 14)
    ? "procesy"
    : "procesów";
}

/**
 * „W procesie": zatrudnienie u klienta ma pierwszeństwo (to najważniejsza
 * informacja przed wysłaniem profilu), potem liczba aktywnych rekrutacji
 * z etapem najświeższego ruchu. Zamknięte rekrutacje się nie liczą.
 */
export function processCell(
  employment: CandidateRowAvailabilitySource["employment"],
  recruitments: readonly CandidateRowRecruitment[] | null | undefined,
): ProcessCell | null {
  if (employment?.state === "employed_at_client") {
    return {
      text: employment.client_name ? `Pracuje u nas · ${employment.client_name}` : "Pracuje u nas",
      tone: "employed",
    };
  }
  const active = activeRecruitments(recruitments);
  if (active.length === 0) return null;
  const latest = active[0];
  return {
    text: `${active.length} ${processesWord(active.length)} · ${stageLabel(latest.stage)}`,
    tone: "process",
  };
}

/** „Ostatni kontakt" — względnie; `null` = nigdy nie kontaktowany (w NEXUSIE). */
export function lastContactText(lastContactedAt: string | null | undefined): string | null {
  if (!lastContactedAt) return null;
  return formatRelativeTime(lastContactedAt);
}

/**
 * Stawka B2B z profilu („160 zł/h") — ta sama, po której filtruje lista.
 * Waluta inna niż PLN zostaje podana wprost.
 */
export function rateCellText(candidate: {
  expected_rate_hourly?: number | string | null;
  expected_rate_currency?: string | null;
}): string | null {
  const raw = candidate.expected_rate_hourly;
  const amount = typeof raw === "string" ? Number(raw) : raw;
  if (amount == null || !Number.isFinite(amount) || amount <= 0) return null;
  const currency = (candidate.expected_rate_currency || "PLN").trim().toUpperCase();
  const value = amount.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
  return currency === "PLN" ? `${value} zł/h` : `${value} ${currency}/h`;
}

/** „1 kandydat", „248 kandydatów" — liczba z formą rzeczownika. */
export function candidatesCountLabel(n: number): string {
  return `${n.toLocaleString("pl-PL")} ${n === 1 ? "kandydat" : "kandydatów"}`;
}
