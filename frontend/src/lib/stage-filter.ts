/**
 * Filtr „Dodany na etap · Dodany przez · Dodany od – do” na liście kandydatów
 * (prośba rekrutera 19.10.2026, decyzja Artura: rozbudowa panelu „Etap
 * w rekrutacji”, nie drugi filtr).
 *
 * Etap wybiera się jak kolumnę Tablicy („QC CV”, „Zweryfikowany”…), nie kod
 * etapu — „QC CV” to nazwa etapu szablonu z kodem `interview`, więc dawna
 * lista 14 kodów go nie miała. Kolumnę na etapy szablonu zamienia serwer
 * (`candidate_stage_column.py`, ta sama reguła co Tablica). „Dodany przez” to
 * osoba, która przesunęła kandydata NA ten etap (`stage_moved_by`, ten sam
 * wiersz etapu co data).
 */
import type { MultiSelectFilterOption } from "@/components/v2/filters/MultiSelectFilter";
import { BOARD_COLUMN_LABEL, BOARD_COLUMN_ORDER, type BoardColumnKey } from "@/lib/board-stages";
import { formatWarsawDay } from "@/lib/added-to-base";
import type { CandidateFilters } from "@/lib/url-filters";

/** Kolumny Tablicy i pasek zamkniętych — kolejność jak na Tablicy. */
export const STAGE_COLUMN_VALUES: readonly BoardColumnKey[] = [...BOARD_COLUMN_ORDER, "closed"];

const STAGE_COLUMN_SET = new Set<string>(STAGE_COLUMN_VALUES);

export function isStageColumn(value: string): value is BoardColumnKey {
  return STAGE_COLUMN_SET.has(value);
}

export const STAGE_COLUMN_OPTIONS: ReadonlyArray<MultiSelectFilterOption<BoardColumnKey>> =
  STAGE_COLUMN_VALUES.map((value) => ({ value, label: BOARD_COLUMN_LABEL[value] }));

export function stageColumnLabel(value: string): string {
  return isStageColumn(value) ? BOARD_COLUMN_LABEL[value] : value;
}

function dayParts(isoDay: string): [string, string, string] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDay);
  return m ? [m[1], m[2], m[3]] : null;
}

/**
 * „01.10 – 15.10.2026” (ten sam rok), „15.12.2025 – 05.01.2026”, „od 01.10.2026”,
 * „do 15.10.2026”; `null`, gdy nie ma żadnej granicy.
 */
export function stageDateRangeLabel(from: string, to: string): string | null {
  const a = from ? dayParts(from) : null;
  const b = to ? dayParts(to) : null;
  if (a && b) {
    const start = a[0] === b[0] ? `${a[2]}.${a[1]}` : `${a[2]}.${a[1]}.${a[0]}`;
    return `${start} – ${b[2]}.${b[1]}.${b[0]}`;
  }
  if (a) return `od ${a[2]}.${a[1]}.${a[0]}`;
  if (b) return `do ${b[2]}.${b[1]}.${b[0]}`;
  return null;
}

/** Czy lista pyta o etap — wtedy odpowiedź niesie `stage_match` przy osobie. */
export function hasStageFilter(
  filters: Pick<
    CandidateFilters,
    | "stageColumns"
    | "pipelineStage"
    | "stageMovedByIds"
    | "stageMovedAfter"
    | "stageMovedBefore"
    | "stageClientIds"
  >,
): boolean {
  return (
    filters.stageColumns.length > 0 ||
    filters.pipelineStage.length > 0 ||
    filters.stageMovedByIds.length > 0 ||
    Boolean(filters.stageMovedAfter || filters.stageMovedBefore) ||
    filters.stageClientIds.length > 0
  );
}

/** Przejście, które spełniło filtr etapu (`stage_match` w odpowiedzi listy). */
export interface StageMatch {
  column: string;
  moved_at?: string | null;
  moved_by_name?: string | null;
  job_id: number;
  job_title?: string | null;
  job_working_title?: string | null;
  job_client_reference?: string | null;
  client_name?: string | null;
}

/** Pierwsza linia komórki: „QC CV · 05.10.2026”. */
export function stageMatchHeadline(match: Pick<StageMatch, "column" | "moved_at">): string {
  const day = formatWarsawDay(match.moved_at ?? null);
  const column = stageColumnLabel(match.column);
  return day ? `${column} · ${day}` : column;
}

/** Kto przesunął; wiersz bez osoby to import z Traffita albo automat. */
export function stageMatchMover(match: Pick<StageMatch, "moved_by_name">): string {
  return match.moved_by_name?.trim() || "Import systemowy";
}
