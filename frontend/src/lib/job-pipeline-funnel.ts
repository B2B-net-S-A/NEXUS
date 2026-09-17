/**
 * Grupowanie surowych etapów pipeline'u (`CandidateStage.stage`, patrz
 * `STAGE_LABEL` w `app/dashboard/delivery-lead/_components/tabs/ActiveJobsTab.tsx`)
 * w sześć grup mini-lejka listy rekrutacji (makieta „01 Lista”, krok C2-flow #4):
 * nowi · screening · zweryfikowani · u klienta · umowa · zatrudnieni.
 *
 * Osobny moduł, a nie funkcja lokalna w `JobsListV2` — test wiąże się z TĄ SAMĄ
 * funkcją, której używa komponent (wzorzec `jobs-url-filters.ts`).
 *
 * Dane wejściowe: `GET /api/jobs?include_stage_counts=true` — każdy wiersz
 * dostaje `stage_breakdown: {<stage>: count}` jednym dodatkowym GROUP BY na
 * całą stronę wyników (`backend/app/api/jobs.py::list_jobs`), zero zapytań
 * per wiersz.
 */

import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { countHired, groupKanbanColumns } from "@/lib/pipeline-flow";

/**
 * Kolumna szablonu z liczbą, bez kart — `stage_columns` z wiersza listy
 * (`GET /api/jobs?include_stage_counts=true`). Te same pola co `KanbanColumn`
 * tablicy (`GET /api/pipeline/kanban/{id}`), z których `groupKanbanColumns`
 * rozpoznaje grupę: enum, kategoria, nazwa, pozycja, terminal.
 */
export type StageColumnSummary = Omit<KanbanColumn, "items"> & {
  items?: KanbanColumn["items"];
};

/**
 * Skrót pipeline'u z wiersza listy. `stage_columns` jest źródłem prawdy —
 * grupowane TĄ SAMĄ funkcją co szyny szczegółów (`groupKanbanColumns`), więc
 * lista i szczegóły nie mogą pokazać różnych liczb dla tej samej rekrutacji
 * (UAT B33: „Przepuszczony przez DZ" liczony raz do Nowych, raz do
 * Zweryfikowanych). Legacy `stage_breakdown` (po enumie) zostaje fallbackiem
 * dla odpowiedzi sprzed tego pola.
 */
export interface PipelineStageSummary {
  stage_columns?: readonly StageColumnSummary[] | null;
  stage_breakdown?: Record<string, number> | null;
}

export type FunnelGroupKey =
  | "new"
  | "screening"
  | "verified"
  | "with_client"
  | "contract"
  | "hired";

export interface FunnelGroup {
  key: FunnelGroupKey;
  label: string;
  count: number;
}

export const FUNNEL_GROUP_ORDER: readonly FunnelGroupKey[] = [
  "new",
  "screening",
  "verified",
  "with_client",
  "contract",
  "hired",
];

export const FUNNEL_GROUP_LABELS: Record<FunnelGroupKey, string> = {
  new: "Nowi",
  screening: "Screening",
  verified: "Zweryfikowani",
  with_client: "U klienta",
  contract: "Umowa",
  hired: "Zatrudnieni",
};

// `prep_call` to rozmowa PRZED formalnym screeningiem — liczymy ją do "nowi",
// nie do "screening" (screening = etap `screening` wprost). `rejected` i
// `withdrawn` to stany terminalne odejścia z procesu — świadomie POZA sześcioma
// grupami (mini-lejek pokazuje postęp, nie odpady); ich sumę liczy
// `funnelRejectedTotal` osobno, dla dociekliwych.
const STAGE_TO_GROUP: Record<string, FunnelGroupKey> = {
  // `posting` (kandydaci z ogłoszeń) w mini-lejku liczy się do „nowi" —
  // sześć grup to skrót, osobną kolumnę ma pełna tablica.
  posting: "new",
  new: "new",
  prep_call: "new",
  screening: "screening",
  verified: "verified",
  cv_sent: "with_client",
  // `interview` = interview WEWNĘTRZNY / techniczny (`StageCategory.internal`
  // w `models/recruitment_pipeline.py`) — kandydat nie poszedł jeszcze do
  // klienta, więc liczy się do „zweryfikowani", nie do „u klienta".
  interview: "verified",
  client_interview: "with_client",
  acceptance: "contract",
  negotiation: "contract",
  onboarding: "contract",
  hired: "hired",
};

const TERMINAL_NEGATIVE_STAGES: readonly string[] = ["rejected", "withdrawn"];

function isStageSummary(
  input: PipelineStageSummary | Record<string, number>,
): input is PipelineStageSummary {
  return (
    Array.isArray((input as PipelineStageSummary).stage_columns) ||
    typeof (input as PipelineStageSummary).stage_breakdown === "object"
  );
}

/** Kolumny szablonu z wiersza listy jako `KanbanColumn[]` (bez kart). */
function stageColumnsOf(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): KanbanColumn[] | null {
  if (!input || !isStageSummary(input) || !Array.isArray(input.stage_columns)) {
    return null;
  }
  return input.stage_columns.map((c) => ({ ...c, items: c.items ?? [] }));
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

/**
 * `stage_breakdown` surowy z API → sześć grup w stałej kolejności (zawsze
 * wszystkie sześć kluczy, licznik 0 gdy brak kandydatów na danym etapie —
 * stały kształt ułatwia renderowanie paska bez warunków na brakujące klucze).
 *
 * Nieznany klucz etapu (przyszła wartość enuma, której ta mapa jeszcze nie zna)
 * jest po cichu pomijany z sumy — CELOWO: literówka w mapowaniu ma dać zaniżony
 * pasek, którego brak da się zauważyć na oko, a nie wyjątek wywalający całą listę.
 */
export function buildStageFunnel(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): FunnelGroup[] {
  const totals: Record<FunnelGroupKey, number> = {
    new: 0,
    screening: 0,
    verified: 0,
    with_client: 0,
    contract: 0,
    hired: 0,
  };
  const columns = stageColumnsOf(input);
  if (columns) {
    // Jedna definicja grup z szynami szczegółów. „Umowa → zatrudnieni" jest
    // tam jedną grupą; mini-lejek listy rozdziela z niej zatrudnionych, żeby
    // ostatni kubełek mówił o wyniku, nie o etapie.
    const groups = groupKanbanColumns(columns);
    const hired = countHired(columns);
    for (const g of groups) {
      if (g.key === "intake") totals.new += g.count;
      // „Ogłoszenia" to też kandydaci na wejściu — bez tej linii mini-lejek
      // listy i dok „Gotowość" gubiły ich (lista „1·0·0", tablica 5 kart).
      else if (g.key === "posting") totals.new += g.count;
      else if (g.key === "screening") totals.screening += g.count;
      else if (g.key === "verification") totals.verified += g.count;
      else if (g.key === "client") totals.with_client += g.count;
      else if (g.key === "contract") totals.contract += g.count - hired;
    }
    totals.hired += hired;
    return FUNNEL_GROUP_ORDER.map((key) => ({
      key,
      label: FUNNEL_GROUP_LABELS[key],
      count: totals[key],
    }));
  }
  const stageBreakdown = stageBreakdownOf(input);
  if (stageBreakdown) {
    for (const [stage, count] of Object.entries(stageBreakdown)) {
      const group = STAGE_TO_GROUP[stage];
      if (group && typeof count === "number") {
        totals[group] += count;
      }
    }
  }
  return FUNNEL_GROUP_ORDER.map((key) => ({
    key,
    label: FUNNEL_GROUP_LABELS[key],
    count: totals[key],
  }));
}

/** Suma sześciu grup — "ile kandydatów jest gdziekolwiek w tej rekrutacji". */
export function funnelTotal(groups: readonly FunnelGroup[]): number {
  return groups.reduce((sum, g) => sum + g.count, 0);
}

/** Odrzuceni + wycofani — poza sześcioma grupami, liczeni osobno. */
export function funnelRejectedTotal(
  input: PipelineStageSummary | Record<string, number> | null | undefined,
): number {
  const columns = stageColumnsOf(input);
  if (columns) {
    return groupKanbanColumns(columns).find((g) => g.key === "closed")?.count ?? 0;
  }
  const stageBreakdown = stageBreakdownOf(input);
  if (!stageBreakdown) return 0;
  return TERMINAL_NEGATIVE_STAGES.reduce(
    (sum, stage) => sum + (stageBreakdown[stage] ?? 0),
    0,
  );
}

/** Krótki opis do `title` (tooltip) paska — pomija grupy zerowe. */
export function funnelTooltip(groups: readonly FunnelGroup[]): string {
  const nonZero = groups.filter((g) => g.count > 0);
  if (nonZero.length === 0) return "Brak kandydatów w tej rekrutacji.";
  return nonZero.map((g) => `${g.label}: ${g.count}`).join(" · ");
}
