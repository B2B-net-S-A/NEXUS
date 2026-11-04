/**
 * Tablica otwartych rekrutacji (strona główna kariery, etap 6) — czysta logika
 * filtrów. Makiety: https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h, plansze
 * 6b (desktop) i 6c (telefon).
 */
import type { CareerBoardCategory, CareerBoardJob, RemotePolicy } from "./api";

export const BOARD_CATEGORIES: readonly { id: CareerBoardCategory; label: string }[] = [
  { id: "development", label: "Development" },
  { id: "infra", label: "Infra & data" },
  { id: "qa", label: "QA" },
  { id: "management", label: "Management & delivery" },
];

export const BOARD_MODES: readonly { id: RemotePolicy; label: string }[] = [
  { id: "remote", label: "Zdalnie" },
  { id: "hybrid", label: "Hybryda" },
  { id: "onsite", label: "Stacjonarnie" },
];

/** Ile kart na start i po każdym „pokaż kolejne”. */
export const BOARD_PAGE = 12;

export function categoryLabel(id: CareerBoardCategory | null | undefined): string | null {
  return BOARD_CATEGORIES.find((c) => c.id === id)?.label ?? null;
}

/** Plakietki kategorii na stronie rekrutera (makieta 6d) — bez powtórzeń, w kolejności listy. */
export function categoryChips(jobs: readonly { category?: CareerBoardCategory | null }[]): string[] {
  const out: string[] = [];
  for (const job of jobs) {
    const label = categoryLabel(job.category);
    if (label && !out.includes(label)) out.push(label);
  }
  return out;
}

export interface BoardFilters {
  category: CareerBoardCategory | null;
  query: string;
  modes: readonly RemotePolicy[];
}

export const NO_FILTERS: BoardFilters = { category: null, query: "", modes: [] };

function fold(value: string): string {
  return value
    .toLocaleLowerCase("pl-PL")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l");
}

/** Słowa zapytania („java, kraków kafka”) — każde musi wystąpić w karcie. */
function terms(query: string): string[] {
  return fold(query)
    .split(/[\s,;]+/)
    .filter(Boolean);
}

function matchesText(job: CareerBoardJob, words: string[]): boolean {
  if (words.length === 0) return true;
  const haystack = fold(
    [job.title, job.subtitle, job.city, ...(job.must ?? []), ...(job.nice ?? [])]
      .filter(Boolean)
      .join(" "),
  );
  return words.every((w) => haystack.includes(w));
}

function matchesMode(job: CareerBoardJob, modes: readonly RemotePolicy[]): boolean {
  return modes.length === 0 || (job.remote_policy !== null && modes.includes(job.remote_policy));
}

/** Karty po filtrach, w kolejności z API (od najnowszej rekrutacji). */
export function filterBoard(jobs: readonly CareerBoardJob[], f: BoardFilters): CareerBoardJob[] {
  const words = terms(f.query);
  return jobs.filter(
    (job) =>
      (f.category === null || job.category === f.category) &&
      matchesText(job, words) &&
      matchesMode(job, f.modes),
  );
}

/**
 * Liczniki przy kategoriach — po szukaniu i trybie, bez samej kategorii,
 * żeby liczba przy przycisku mówiła, ile kart pokaże jego kliknięcie.
 */
export function categoryCounts(
  jobs: readonly CareerBoardJob[],
  f: BoardFilters,
): { all: number } & Record<CareerBoardCategory, number> {
  const pool = filterBoard(jobs, { ...f, category: null });
  const counts = { all: pool.length, development: 0, infra: 0, qa: 0, management: 0 };
  for (const job of pool) if (job.category) counts[job.category] += 1;
  return counts;
}

/** „1 otwarta”, „3 otwarte”, „24 otwarte”, „25 otwartych”, „12 otwartych”. */
export function openCountLabel(n: number): string {
  if (n === 1) return "1 otwarta";
  const last = n % 10;
  const lastTwo = n % 100;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return `${n} otwarte`;
  return `${n} otwartych`;
}

/** Linia pod kartą: „Warszawa · Hybryda”, „Zdalnie” (od 29.10.2026 w pisowni marki, nie terminala). */
export function boardTagLine(job: Pick<CareerBoardJob, "city" | "remote_policy">): string {
  const mode = BOARD_MODES.find((m) => m.id === job.remote_policy)?.label ?? null;
  const city = job.remote_policy === "remote" ? null : job.city?.trim();
  return [city, mode].filter(Boolean).join(" · ");
}
