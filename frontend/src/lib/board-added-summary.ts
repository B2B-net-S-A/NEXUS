/**
 * „Kto ilu dodał” w okienku „Zespół rekrutacji” (prośba z zespołu, decyzja Artura
 * z 16.11.2026, wariant C). Zasady:
 * docs/claude/rekrutacja-tablica/kto-ilu-dodal-w-zespole-rekrutacji.md
 *
 * Liczy DODANIA do tej rekrutacji: osobę z pierwszego wpisu etapu pary
 * (`added_to_job_by_id`), od otwarcia, także zamkniętych. To co innego niż
 * filtr „Kto dodał” (`board-added-by.ts`), który liczy osobę karty („Biorę”,
 * weryfikacja) i tylko osoby w toku — dlatego wiersz tabeli nie włącza filtra.
 */
import { placeStage, type BoardColumnKey, type StageLike } from "@/lib/board-stages";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";

export interface AddedSummaryItem {
  candidate_id: number;
  added_to_job_by_id?: number | null;
  added_to_job_by_name?: string | null;
  added_to_job_at?: string | null;
  entry_source?: string | null;
}

interface SummaryColumn extends StageLike {
  items: readonly AddedSummaryItem[];
}

export interface TeamMember {
  user_id: number;
  name: string;
}

export interface AddedSummaryRow {
  /** `user:12`, `system` (silnik „Nowi”), `none` (stary wpis bez osoby). */
  key: string;
  kind: "user" | "system" | "none";
  userId: number | null;
  name: string;
  added: number;
  /** Dodani dziś i w sześciu poprzednich dniach (kalendarz firmy). */
  last7: number;
  inProgress: number;
  /** W toku od „Zweryfikowanego” w prawo. */
  pastScreening: number;
  /** W toku od „CV wysłane” w prawo. */
  atClient: number;
}

export interface AddedSummary {
  rows: AddedSummaryRow[];
  total: number;
  /** Dodani przez ludzi (bez silnika i wpisów bez osoby). */
  byPeople: number;
}

const PAST_SCREENING: ReadonlySet<BoardColumnKey> = new Set([
  "verified",
  "cv_qc",
  "cv_sent",
  "client_interview",
  "contract",
  "hired",
]);
const AT_CLIENT: ReadonlySet<BoardColumnKey> = new Set([
  "cv_sent",
  "client_interview",
  "contract",
  "hired",
]);
const LAST_DAYS = 7;

function dayIndex(day: string): number {
  return Math.round(Date.parse(`${day}T00:00:00Z`) / 86_400_000);
}

function emptyRow(
  key: string,
  kind: AddedSummaryRow["kind"],
  userId: number | null,
  name: string,
): AddedSummaryRow {
  return { key, kind, userId, name, added: 0, last7: 0, inProgress: 0, pastScreening: 0, atClient: 0 };
}

/**
 * Wiersze: osoby z największą liczbą dodań, potem osoby z zespołu z zerem,
 * na końcu silnik „Nowi” i wpisy bez osoby. Osoba zespołu z zerem zostaje,
 * żeby było widać, kto jeszcze nikogo nie dodał.
 */
export function addedToJobSummary(
  columns: readonly SummaryColumn[],
  team: readonly TeamMember[],
  now: Date = new Date(),
): AddedSummary {
  const today = dayIndex(warsawToday(now));
  const rows = new Map<string, AddedSummaryRow>();
  for (const member of team) {
    const key = `user:${member.user_id}`;
    if (!rows.has(key)) rows.set(key, emptyRow(key, "user", member.user_id, member.name));
  }
  const seen = new Set<number>();
  for (const col of columns) {
    const column = placeStage(col).column;
    for (const item of col.items) {
      if (seen.has(item.candidate_id)) continue;
      seen.add(item.candidate_id);
      let key: string;
      if (item.added_to_job_by_id != null) {
        key = `user:${item.added_to_job_by_id}`;
        if (!rows.has(key)) {
          rows.set(
            key,
            emptyRow(
              key,
              "user",
              item.added_to_job_by_id,
              item.added_to_job_by_name?.trim() || "Osoba bez nazwy",
            ),
          );
        }
      } else if (item.entry_source === "system") {
        key = "system";
        if (!rows.has(key)) rows.set(key, emptyRow(key, "system", null, "Automat „Nowi”"));
      } else {
        key = "none";
        if (!rows.has(key)) rows.set(key, emptyRow(key, "none", null, "Bez danych"));
      }
      const row = rows.get(key)!;
      row.added += 1;
      const day = warsawDateOf(item.added_to_job_at ?? null);
      if (day && today - dayIndex(day) < LAST_DAYS) row.last7 += 1;
      if (column === "closed") continue;
      row.inProgress += 1;
      if (PAST_SCREENING.has(column)) row.pastScreening += 1;
      if (AT_CLIENT.has(column)) row.atClient += 1;
    }
  }
  const rank = (row: AddedSummaryRow) => (row.kind === "user" ? 0 : row.kind === "system" ? 1 : 2);
  const sorted = Array.from(rows.values()).sort(
    (a, b) => rank(a) - rank(b) || b.added - a.added || a.name.localeCompare(b.name, "pl"),
  );
  return {
    rows: sorted,
    total: seen.size,
    byPeople: sorted.filter((r) => r.kind === "user").reduce((sum, r) => sum + r.added, 0),
  };
}
