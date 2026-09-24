/**
 * Skrót pipeline'u z wiersza listy rekrutacji: te same 8 kolumn co Tablica
 * (Rekrutacja v5, decyzja Artura 23.09.2026) — Nowi · Screening ·
 * Zweryfikowany · QC CV · CV wysłane · Rozmowa u klienta · Umowa ·
 * Zatrudniony.
 *
 * Kolumnę etapu rozstrzyga WYŁĄCZNIE `placeStage` z `lib/board-stages.ts`
 * (lustro `board_column_for` w backendzie, wspólny fixture
 * `__fixtures__/board-stage-cases.json`) — ta sama reguła co na Tablicy, nie
 * własna kopia po kodzie etapu. Bez niej etap „QC CV" / „Przepuszczony przez
 * DZ" (kod techniczny `interview` albo `new`) liczyłby się do
 * „Zweryfikowanych" albo „Nowych".
 *
 * Osobny moduł, a nie funkcja lokalna w `JobsListV2` — test wiąże się z TĄ SAMĄ
 * funkcją, której używa komponent (wzorzec `jobs-url-filters.ts`). Czyta go też
 * dok podglądu (`JobReadinessDock`), więc lista i dok mówią tymi samymi grupami.
 *
 * Dane wejściowe: `GET /api/jobs?include_stage_counts=true` — każdy wiersz
 * dostaje `stage_columns` (kolumny szablonu z liczbami, te same co tablica)
 * i legacy `stage_breakdown: {<stage>: count}` jednym dodatkowym GROUP BY na
 * całą stronę wyników (`backend/app/api/jobs.py::list_jobs`), zero zapytań
 * per wiersz.
 */

import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import {
  BOARD_COLUMN_LABEL,
  BOARD_COLUMN_ORDER,
  placeStage,
  type BoardColumnKey,
} from "@/lib/board-stages";

/**
 * Kolumna szablonu z liczbą, bez kart — `stage_columns` z wiersza listy.
 * Te same pola co `KanbanColumn` tablicy (`GET /api/pipeline/kanban/{id}`).
 */
export type StageColumnSummary = Omit<KanbanColumn, "items"> & {
  items?: KanbanColumn["items"];
};

/**
 * Skrót pipeline'u z wiersza listy. `stage_columns` jest źródłem prawdy (nazwa
 * etapu rozpoznaje „QC CV", „Wysłać do Cpro", „Umowa wysłana"…); legacy
 * `stage_breakdown` (po samym enumie) zostaje fallbackiem dla odpowiedzi sprzed
 * tego pola.
 */
export interface PipelineStageSummary {
  stage_columns?: readonly StageColumnSummary[] | null;
  stage_breakdown?: Record<string, number> | null;
}

/** Kolumna Tablicy bez paska zamkniętych. */
export type FunnelGroupKey = Exclude<BoardColumnKey, "closed">;

export interface FunnelGroup {
  key: FunnelGroupKey;
  label: string;
  count: number;
}

export const FUNNEL_GROUP_ORDER: readonly FunnelGroupKey[] =
  BOARD_COLUMN_ORDER.filter((k): k is FunnelGroupKey => k !== "closed");

export const FUNNEL_GROUP_LABELS: Record<FunnelGroupKey, string> = {
  new: BOARD_COLUMN_LABEL.new,
  screening: BOARD_COLUMN_LABEL.screening,
  verified: BOARD_COLUMN_LABEL.verified,
  cv_qc: BOARD_COLUMN_LABEL.cv_qc,
  cv_sent: BOARD_COLUMN_LABEL.cv_sent,
  client_interview: BOARD_COLUMN_LABEL.client_interview,
  contract: BOARD_COLUMN_LABEL.contract,
  hired: BOARD_COLUMN_LABEL.hired,
};

/** Skróty kolumn — raz w nagłówku kolumny „Etapy" listy (pełna nazwa w `title`). */
export const FUNNEL_GROUP_SHORT: Record<FunnelGroupKey, string> = {
  new: "Now",
  screening: "Scr",
  verified: "Zwe",
  cv_qc: "QC",
  cv_sent: "Wys",
  client_interview: "Roz",
  contract: "Um",
  hired: "Zat",
};

function isStageSummary(
  input: PipelineStageSummary | Record<string, number>,
): input is PipelineStageSummary {
  return (
    Array.isArray((input as PipelineStageSummary).stage_columns) ||
    typeof (input as PipelineStageSummary).stage_breakdown === "object"
  );
}

function stageColumnsOf(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): readonly StageColumnSummary[] | null {
  if (!input || !isStageSummary(input) || !Array.isArray(input.stage_columns)) {
    return null;
  }
  return input.stage_columns;
}

function stageBreakdownOf(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): Record<string, number> | null {
  if (!input) return null;
  if (isStageSummary(input)) return input.stage_breakdown ?? null;
  return input;
}

/**
 * Skrót pipeline'u z wiersza listy albo `undefined`, gdy wiersz go nie niesie
 * (np. odpowiedź bez `include_stage_counts`) — konsumenci renderują wtedy
 * „brak danych", nie zera.
 */
export function stageSummaryOf(
  row: PipelineStageSummary | null | undefined,
): PipelineStageSummary | undefined {
  if (!row) return undefined;
  if (row.stage_columns == null && row.stage_breakdown == null) return undefined;
  return { stage_columns: row.stage_columns, stage_breakdown: row.stage_breakdown };
}

/** Każdy wpis (kolumna szablonu albo legacy enum) z kolumną Tablicy. */
function placedEntries(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): Array<{ column: BoardColumnKey; name: string | null; count: number }> {
  const columns = stageColumnsOf(input);
  if (columns) {
    return columns.map((col) => ({
      column: placeStage(col).column,
      name: col.name ?? col.stage ?? null,
      count: typeof col.count === "number" ? col.count : 0,
    }));
  }
  const breakdown = stageBreakdownOf(input);
  if (!breakdown) return [];
  return Object.entries(breakdown)
    .filter(([, count]) => typeof count === "number")
    .map(([stage, count]) => ({
      column: placeStage({ stage }).column,
      name: null,
      count,
    }));
}

/**
 * Wiersz listy → osiem kolumn Tablicy w stałej kolejności (zawsze wszystkie
 * klucze, 0 gdy nikogo — stały kształt upraszcza render). Odrzuceni i wycofani
 * (kolumna `closed`) są POZA ośmioma grupami — liczy ich `funnelRejectedTotal`.
 *
 * Nieznany kod etapu (przyszła wartość enuma) wpada tam, gdzie wpadłby na
 * Tablicy (`placeStage` → „Nowi") — lista nie może pokazać innej liczby niż
 * tablica.
 */
export function buildStageFunnel(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): FunnelGroup[] {
  const totals = Object.fromEntries(
    FUNNEL_GROUP_ORDER.map((key) => [key, 0]),
  ) as Record<FunnelGroupKey, number>;
  for (const entry of placedEntries(input)) {
    if (entry.column === "closed") continue;
    totals[entry.column] += entry.count;
  }
  return FUNNEL_GROUP_ORDER.map((key) => ({
    key,
    label: FUNNEL_GROUP_LABELS[key],
    count: totals[key],
  }));
}

/** Suma ośmiu grup — "ile kandydatów jest gdziekolwiek w tej rekrutacji". */
export function funnelTotal(groups: readonly FunnelGroup[]): number {
  return groups.reduce((sum, g) => sum + g.count, 0);
}

/** Odrzuceni + wycofani (+ rezerwa) — poza ośmioma grupami, liczeni osobno. */
export function funnelRejectedTotal(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): number {
  return placedEntries(input)
    .filter((entry) => entry.column === "closed")
    .reduce((sum, entry) => sum + entry.count, 0);
}

/** Krótki opis do `title` (tooltip) paska — pomija grupy zerowe. */
export function funnelTooltip(groups: readonly FunnelGroup[]): string {
  const nonZero = groups.filter((g) => g.count > 0);
  if (nonZero.length === 0) return "Brak kandydatów w tej rekrutacji.";
  return nonZero.map((g) => `${g.label}: ${g.count}`).join(" · ");
}

/** Etap szablonu (pełna nazwa) z liczbą — treść tooltipa grupy na liście. */
export interface FunnelStageDetail {
  name: string;
  count: number;
}

/**
 * Pełne nazwy etapów szablonu wchodzących w każdą z ośmiu kolumn, z liczbami
 * — zwarta liczba w wierszu listy rozwija się tooltipem do tego, co widać na
 * tablicy („QC CV: Przepuszczony przez DZ 2 · Wysłać do Cpro 1"). Grupuje ta
 * sama reguła co `buildStageFunnel`, więc suma nazw równa się liczbie
 * w komórce. Bez `stage_columns` nazw nie znamy — puste listy.
 */
export function funnelGroupStages(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): Record<FunnelGroupKey, FunnelStageDetail[]> {
  const out = Object.fromEntries(
    FUNNEL_GROUP_ORDER.map((key) => [key, [] as FunnelStageDetail[]]),
  ) as Record<FunnelGroupKey, FunnelStageDetail[]>;
  if (!stageColumnsOf(input)) return out;
  for (const entry of placedEntries(input)) {
    if (entry.column === "closed") continue;
    out[entry.column].push({ name: entry.name ?? "", count: entry.count });
  }
  return out;
}

/** `title` jednej grupy: „Nowi: Nowy 2 · Ogłoszenia 1" albo nazwa + suma. */
export function funnelGroupTitle(
  group: FunnelGroup,
  stages: readonly FunnelStageDetail[],
): string {
  if (stages.length === 0) return `${group.label}: ${group.count}`;
  return `${group.label}: ${stages.map((s) => `${s.name} ${s.count}`).join(" · ")}`;
}
