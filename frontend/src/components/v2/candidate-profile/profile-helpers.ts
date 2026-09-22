/**
 * Czyste reguły profilu kandydata — wydzielone, żeby dało się je testować
 * bez montowania ciężkiego profilu (kilkanaście zapytań).
 */
import {
  getCurrentTitle,
  type CandidateLite,
} from "@/components/v2/pages/candidate-list-helpers";

/** „1 rok”, „3 lata”, „8 lat”, „22 lata” — polska odmiana liczebnika. */
export function yearsLabel(years: number): string {
  const n = Math.floor(years);
  if (n === 1) return "1 rok";
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${n} lata`;
  }
  return `${n} lat`;
}

/**
 * Linia pod nazwiskiem: „stanowisko · N lat doświadczenia”. Świadomie BEZ
 * lokalizacji i dostępności — te fakty mają jedno miejsce: pasek faktów.
 */
export function candidateHeadline(
  candidate: CandidateLite & { years_it_experience?: number | null },
): string | null {
  const parts: string[] = [];
  const title = getCurrentTitle(candidate);
  if (title) parts.push(title);
  const years = candidate.years_it_experience;
  if (typeof years === "number" && Number.isFinite(years) && years > 0) {
    parts.push(`${yearsLabel(years)} doświadczenia`);
  }
  return parts.length ? parts.join(" · ") : null;
}

export type HeaderWarning =
  | { kind: "blacklist" }
  | { kind: "risk" }
  | null;

/**
 * Jedna odznaka ostrzegawcza w nagłówku. Priorytet: czarna lista >
 * zatrudniony u naszego klienta > ryzyko rezygnacji.
 *
 * Zatrudnienie u klienta ma własny, głośny baner nad nagłówkiem (z listą
 * klientów i linkiem do kontraktora) — więc w tej sytuacji odznaka NIE
 * powtarza tej samej informacji, ale też nie ustępuje miejsca ryzyku: baner
 * jest ważniejszy i ma zostać jedynym sygnałem.
 */
export function pickHeaderWarning(input: {
  status?: string | null;
  employmentState?: string | null;
  riskLevel?: string | null;
}): HeaderWarning {
  if (input.status === "blacklisted") return { kind: "blacklist" };
  if (input.employmentState === "employed_at_client") return null;
  if (input.riskLevel === "medium" || input.riskLevel === "high") {
    return { kind: "risk" };
  }
  return null;
}

export interface RecruitmentHistoryItem {
  job_id?: number | null;
  id?: number | null;
  job_status?: string | null;
  latest_stage?: string | null;
  [key: string]: unknown;
}

const ENDED_STAGES = new Set(["rejected", "withdrawn"]);

/** Rekrutacja zakończona dla tej osoby: zamknięta albo odrzucenie/wycofanie. */
export function isRecruitmentEnded(item: RecruitmentHistoryItem): boolean {
  if (item.job_status === "closed") return true;
  return ENDED_STAGES.has(String(item.latest_stage ?? ""));
}

/** Aktywne na górze, zakończone osobno (zwinięte „Zakończone (n)”). */
export function splitRecruitments<T extends RecruitmentHistoryItem>(
  history: T[],
): { active: T[]; ended: T[] } {
  const active: T[] = [];
  const ended: T[] = [];
  for (const item of Array.isArray(history) ? history : []) {
    (isRecruitmentEnded(item) ? ended : active).push(item);
  }
  return { active, ended };
}

interface VerifiedSkillAggregate {
  skill?: string | null;
  level?: string | null;
}

/**
 * Umiejętności potwierdzone na screeningu — z profilu (`verified_tech`)
 * i z agregatu screeningów (`verified_skills_aggregate`, poziom „confirmed”).
 * Zwraca nazwy w oryginalnym zapisie, bez duplikatów (bez wielkości liter).
 */
export function screeningConfirmedSkills(
  verifiedTech: unknown,
  aggregate: VerifiedSkillAggregate[] | null | undefined,
): string[] {
  const out = new Map<string, string>();
  const push = (value: unknown) => {
    if (typeof value !== "string") return;
    const trimmed = value.trim();
    if (!trimmed) return;
    const key = trimmed.toLowerCase();
    if (!out.has(key)) out.set(key, trimmed);
  };
  if (Array.isArray(verifiedTech)) {
    for (const item of verifiedTech) {
      if (typeof item === "string") push(item);
      else if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        push(record.name ?? record.tech ?? record.skill);
      }
    }
  }
  for (const entry of aggregate ?? []) {
    if (entry?.level === "confirmed") push(entry.skill);
  }
  return [...out.values()];
}
