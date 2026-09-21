/**
 * Czyste buildery tabeli osób („rekrutacja = jedna tabela", wersja 3).
 *
 * Tablica kanbana odpowiadała na pytanie „kto stoi na którym etapie". Tabela
 * odpowiada na inne: „z kim mam dziś coś zrobić" — dlatego każdy wiersz niesie
 * policzoną RAZ następną akcję (`nextActionFor`, z grupą etapu znaną z całego
 * szablonu), a sortowanie, filtry i grupy czytają wyłącznie to, co już jest
 * w wierszu. Zero sieci i zero Reacta: moduł woła się przy każdym renderze
 * tabeli z kilkuset wierszami.
 */

import {
  colId,
  columnLabel,
  type KanbanColumn,
  type KanbanItem,
} from "@/components/v2/pages/kanban-shared";
import {
  countInProcess,
  formatExpectedRate,
  groupKanbanColumns,
  itemFullName,
  type PipelineGroupKey,
} from "@/lib/pipeline-flow";
import {
  STUCK_DAYS,
  hasNoNextAction,
  nextActionFor,
  type NextAction,
} from "@/lib/pipeline-next-action";
import { isInterviewStage, type FlowColumn } from "@/lib/job-flow-stages";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { formatDate } from "@/lib/utils";

import type {
  PersonRow,
  PersonRowGroup,
  ProcessPersonRow,
  RecruitmentSegment,
} from "./types";

// ── Stałe ─────────────────────────────────────────────────────────────

/**
 * Sentinel kolumny „poza szablonem" — ta sama wartość co w `KanbanBoardV2`
 * (tam nieeksportowana). CELOWO nie jest etapem pipeline'u: gdyby kubełek
 * udawał `new`, pomyłkowy ruch „na" niego kończyłby się cichym HTTP 200.
 */
export const OFF_TEMPLATE_STAGE = "__off_template__";

/** Powyżej tylu wierszy tabela sama grupuje po „kto ma ruch". */
export const AUTO_GROUP_THRESHOLD = 60;

/** Powyżej tylu dni bez ruchu osoba trafia do grupy „Bez ruchu ponad 14 dni". */
export const STALE_DAYS = 14;

/**
 * Etapy z punktem (re)screeningu Championa — lustro `SCREENING_BADGE_STAGES`
 * z `KanbanBoardV2` (tam nieeksportowane). Odznaka „Uzupełnij screening"
 * pojawia się tylko na nich i tylko przy jawnym `screening_done === false`.
 */
const SCREENING_BADGE_STAGES: ReadonlySet<string> = new Set([
  "verified",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
]);

const AVAILABILITY_LABEL: Record<string, string> = {
  actively_looking: "Aktywnie szuka",
  open_to_offers: "Otwarty na oferty",
  not_looking: "Nie szuka",
};

// ── Wejście ───────────────────────────────────────────────────────────

/** Kubełek „poza szablonem" z `KanbanView.off_template`. */
export interface OffTemplateBucket {
  name?: string | null;
  count: number;
  items: KanbanItem[];
}

export interface BuildProcessRowsOptions {
  /** Dopasowanie 0–100 po `candidate_id`. Brak wpisu = `null`, nigdy zero. */
  scores?: ReadonlyMap<number, number> | null;
  /** SLA klienta w dniach roboczych (karta klienta). */
  slaDays?: number | null;
  /**
   * Aktualny budżet PLN/h rekrutacji. Serwer stempluje `budget_exceeded`
   * z chwili RUCHU; tablica kanbana porównuje z budżetem BIEŻĄCYM — tabela
   * łączy oba, żeby odznaka nie różniła się między widokami.
   */
  budgetHourly?: number | null;
  offTemplate?: OffTemplateBucket | null;
  /** „Dziś" do etykiety dostępności — wstrzykiwane w testach. */
  today?: Date;
}

/** Czy wiersz pochodzi z kubełka „poza szablonem". */
export function isOffTemplateRow(row: ProcessPersonRow): boolean {
  return row.column.stage === OFF_TEMPLATE_STAGE;
}

function offTemplateColumn(bucket: OffTemplateBucket): KanbanColumn {
  return {
    stage: OFF_TEMPLATE_STAGE,
    count: bucket.count,
    items: bucket.items,
    stage_def_id: null,
    name: bucket.name ?? "Poza szablonem",
  };
}

/**
 * Etykieta dostępności: data wygrywa ze statusem (jest konkretniejsza),
 * data miniona znaczy „od razu". `unknown` i brak pól = `null` („—").
 */
export function availabilityLabelFor(
  item: Pick<KanbanItem, "availability_status" | "availability_date">,
  today: Date = new Date(),
): string | null {
  if (item.availability_date) {
    const date = new Date(item.availability_date);
    if (!Number.isNaN(date.getTime())) {
      const startOfToday = new Date(today);
      startOfToday.setHours(0, 0, 0, 0);
      return date.getTime() <= startOfToday.getTime()
        ? "od razu"
        : `od ${formatDate(item.availability_date)}`;
    }
  }
  const status = item.availability_status ?? null;
  return status ? (AVAILABILITY_LABEL[status] ?? null) : null;
}

function normalizedScore(
  scores: ReadonlyMap<number, number> | null | undefined,
  candidateId: number,
): number | null {
  const raw = scores?.get(candidateId);
  if (typeof raw !== "number" || !Number.isFinite(raw)) return null;
  return Math.max(0, Math.min(100, Math.round(raw)));
}

function warningsFor(item: KanbanItem, budgetHourly: number | null | undefined): string[] {
  // Starsza odpowiedź nie niesie `warnings` — weto HM znamy wtedy z pola karty.
  const codes = [...(item.warnings ?? (item.hm_veto ? ["hm_veto"] : []))];
  if (item.hm_veto && !codes.includes("hm_veto")) codes.unshift("hm_veto");
  const overBudget =
    item.budget_exceeded === true || isOverHourlyBudget(item, budgetHourly);
  if (overBudget && !codes.includes("budget_exceeded")) codes.push("budget_exceeded");
  return codes;
}

/**
 * Wiersze osób w procesie — jedno przejście po tablicy.
 *
 * Grupę etapu liczymy nad CAŁĄ listą kolumn (`groupKanbanColumns`), bo własny
 * etap wewnętrzny stojący po screeningu bez pozycji w szablonie wyglądałby jak
 * etap wejściowy i dostał „Umów screening" zamiast „Wyślij CV do klienta".
 */
export function buildProcessRows(
  columns: KanbanColumn[],
  options: BuildProcessRowsOptions = {},
): ProcessPersonRow[] {
  const { scores, slaDays, budgetHourly, offTemplate, today } = options;
  const groupByColId = new Map<string, PipelineGroupKey>();
  for (const group of groupKanbanColumns(columns)) {
    for (const col of group.columns) groupByColId.set(colId(col), group.key);
  }

  const rows: ProcessPersonRow[] = [];
  const seen = new Set<number>();
  const push = (
    item: KanbanItem,
    column: KanbanColumn,
    group: PipelineGroupKey,
    nextAction: NextAction,
  ) => {
    // Jedna osoba = jeden wiersz. Tablica nie powinna nieść duplikatów, ale
    // zdublowany klucz wywraca zaznaczanie i aktywny wiersz, więc bronimy się.
    if (seen.has(item.candidate_id)) return;
    seen.add(item.candidate_id);
    rows.push({
      kind: "process",
      // Klucz po KANDYDACIE, nie po wierszu etapu: `item.id` zmienia się przy
      // każdym ruchu, a zaznaczenie i otwarty panel mają ruch przeżyć.
      key: `c:${item.candidate_id}`,
      candidateId: item.candidate_id,
      fullName: itemFullName(item),
      rateLabel: formatExpectedRate(item),
      availabilityLabel: availabilityLabelFor(item, today),
      fitScore: normalizedScore(scores, item.candidate_id),
      warnings: warningsFor(item, budgetHourly),
      item,
      column,
      group,
      stageLabel: columnLabel(column),
      nextAction,
      daysInStage: item.days_in_stage ?? null,
      recruiterId: item.recruiter_id ?? null,
      recruiterName:
        item.recruiter_name?.trim() || item.added_to_job_by_name?.trim() || null,
    });
  };

  for (const column of columns) {
    const group = groupByColId.get(colId(column)) ?? "intake";
    for (const item of column.items) {
      push(item, column, group, nextActionFor(item, column, { slaDays, group }));
    }
  }

  if (offTemplate && offTemplate.items.length > 0) {
    const column = offTemplateColumn(offTemplate);
    for (const item of offTemplate.items) {
      // Etap tej osoby nie istnieje w szablonie — jedyny sensowny następny
      // krok to przenieść ją na etap, który istnieje. `nextActionFor` nie zna
      // tego przypadku (kolumna-sentinel wyglądałaby jak etap wejściowy).
      push(item, column, "intake", {
        label: "Przenieś na etap z szablonu",
        tone: "due",
        kind: "none",
        owner: "recruiter",
      });
    }
  }
  return rows;
}

// ── Odznaki wiersza ───────────────────────────────────────────────────

export type RowBadgeTone = "warning" | "danger" | "info";

export interface RowBadge {
  key: "over-budget" | "screening" | "scorecard" | "hm-veto";
  label: string;
  tone: RowBadgeTone;
  title: string;
}

export interface RowBadgeContext {
  /** Definicje etapów ze scorecardem (z szablonu rekrutacji). */
  stagesWithScorecard?: ReadonlySet<number> | null;
}

/**
 * Odznaki w kolumnie „Następny krok" — te same warunki co karta kanbana.
 * `=== false`, nie `!`: odpowiedź bez pola nie pokazuje odznaki, której nie
 * umie uzasadnić. Etap terminalny nie ma odznak — nikt tej osoby nie rusza.
 */
export function rowBadges(row: ProcessPersonRow, ctx: RowBadgeContext = {}): RowBadge[] {
  if (row.group === "closed") return [];
  const out: RowBadge[] = [];
  const { item, column } = row;
  if (item.hm_veto) {
    out.push({
      key: "hm-veto",
      label: "weto HM",
      tone: "danger",
      title: `Hiring manager odrzucił już tę osobę — ${item.hm_veto.rejection_reason_name}. Ruch jest możliwy po potwierdzeniu.`,
    });
  }
  if (row.warnings.includes("budget_exceeded")) {
    out.push({
      key: "over-budget",
      label: "ponad budżet",
      tone: "warning",
      title: "Stawka ponad budżet rekrutacji — informacja, nie blokada.",
    });
  }
  if (SCREENING_BADGE_STAGES.has(item.stage) && item.screening_done === false) {
    out.push({
      key: "screening",
      label: "Uzupełnij screening",
      tone: "info",
      title: "Arkusz screeningu na tym etapie nie jest jeszcze zapisany.",
    });
  }
  if (
    column.stage_def_id != null &&
    ctx.stagesWithScorecard?.has(column.stage_def_id) === true &&
    item.scorecard_done === false
  ) {
    out.push({
      key: "scorecard",
      label: "Scorecard",
      tone: "info",
      title: "Scorecard tego etapu — do uzupełnienia.",
    });
  }
  return out;
}

// ── Filtry ────────────────────────────────────────────────────────────

export type QuickChipKey =
  | "mine"
  | "review"
  | "overdue"
  | "waiting-client"
  | "stuck"
  | "no-action"
  | "warnings";

export const QUICK_CHIP_ORDER: readonly QuickChipKey[] = [
  "mine",
  "review",
  "overdue",
  "waiting-client",
  "stuck",
  "no-action",
  "warnings",
];

export const QUICK_CHIP_LABEL: Record<QuickChipKey, string> = {
  mine: "Wymaga mojego ruchu",
  // Stos wejściowy (Ogłoszenia, Nowi) — przegląd, nie sprawa do załatwienia.
  review: "Do przejrzenia",
  overdue: "Po terminie",
  "waiting-client": "Czeka na klienta",
  stuck: `Utknęli > ${STUCK_DAYS} d`,
  "no-action": "Bez następnej akcji",
  warnings: "Ostrzeżenia",
};

/**
 * Predykaty chipów. „Utknęli" pomija etapy terminalne — odrzucony czy
 * zatrudniony „stoi" bezterminowo i nie jest sprawą do załatwienia (ta sama
 * reguła co `countStalled` i filtr lewej kolumny kanbana).
 */
const CHIP_PREDICATE: Record<QuickChipKey, (row: ProcessPersonRow) => boolean> = {
  mine: (row) => row.nextAction.owner === "recruiter",
  review: (row) => row.nextAction.owner === "review",
  overdue: (row) => row.nextAction.tone === "due",
  "waiting-client": (row) => row.nextAction.owner === "client",
  stuck: (row) =>
    row.column.category !== "terminal" && (row.daysInStage ?? 0) > STUCK_DAYS,
  "no-action": (row) => hasNoNextAction(row.nextAction),
  warnings: (row) => row.group !== "closed" && row.warnings.length > 0,
};

export function matchesChip(row: ProcessPersonRow, chip: QuickChipKey): boolean {
  return CHIP_PREDICATE[chip](row);
}

/** Liczniki chipów — nad wierszami JUŻ zawężonymi segmentem. */
export function chipCounts(rows: ProcessPersonRow[]): Record<QuickChipKey, number> {
  const counts = Object.fromEntries(
    QUICK_CHIP_ORDER.map((key) => [key, 0]),
  ) as Record<QuickChipKey, number>;
  for (const row of rows) {
    for (const key of QUICK_CHIP_ORDER) {
      if (CHIP_PREDICATE[key](row)) counts[key] += 1;
    }
  }
  return counts;
}

/** Czy wiersz należy do segmentu paska etapów. */
export function matchesSegment(row: ProcessPersonRow, segment: RecruitmentSegment): boolean {
  if (segment === "in-process") {
    // „W procesie" = kolumny nie-terminalne (jak `countInProcess`) plus
    // kubełek poza szablonem — to nadal realni kandydaci w procesie.
    return row.column.category !== "terminal";
  }
  if (segment === "off-template") return isOffTemplateRow(row);
  if (isOffTemplateRow(row)) return false;
  if (segment === "closed") return row.group === "closed";
  if (segment.startsWith("group:")) return row.group === segment.slice("group:".length);
  if (segment.startsWith("stage:")) {
    const id = Number(segment.slice("stage:".length));
    return row.column.stage_def_id === id;
  }
  // „Propozycje" i „Shortlista" nie są wierszami procesu.
  return false;
}

const DIACRITICS = /[̀-ͯ]/g;

/** `ł` trzeba zamienić ręcznie — NFKD go nie rozkłada. */
export function foldText(value: string): string {
  return value
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFKD")
    .replace(DIACRITICS, "")
    .trim();
}

export interface RowFilters {
  segment: RecruitmentSegment;
  chips?: ReadonlySet<QuickChipKey> | readonly QuickChipKey[];
  /** `null` = wszyscy rekruterzy. */
  recruiterId?: number | null;
  text?: string;
}

/**
 * Filtr tabeli: segment ORAZ wszystkie włączone chipy ORAZ rekruter ORAZ tekst.
 * Tekst to AND po słowach (bez polskich znaków) po nazwisku, etapie
 * i następnym kroku — „kowalski screening" zawęża, nie poszerza.
 */
export function filterRows(rows: ProcessPersonRow[], filters: RowFilters): ProcessPersonRow[] {
  const chips = Array.from(filters.chips ?? []);
  const tokens = foldText(filters.text ?? "").split(/\s+/).filter(Boolean);
  const recruiterId = filters.recruiterId ?? null;
  return rows.filter((row) => {
    if (!matchesSegment(row, filters.segment)) return false;
    if (recruiterId != null && row.recruiterId !== recruiterId) return false;
    for (const chip of chips) {
      if (!CHIP_PREDICATE[chip](row)) return false;
    }
    if (tokens.length > 0) {
      const haystack = foldText(
        `${row.fullName} ${row.stageLabel} ${row.nextAction.label} ${row.recruiterName ?? ""}`,
      );
      for (const token of tokens) {
        if (!haystack.includes(token)) return false;
      }
    }
    return true;
  });
}

export interface RecruiterOption {
  id: number;
  name: string;
}

/** Rekruterzy obecni w wierszach — do selecta; alfabetycznie po polsku. */
export function recruiterOptions(rows: ProcessPersonRow[]): RecruiterOption[] {
  const byId = new Map<number, string>();
  for (const row of rows) {
    if (row.recruiterId == null || byId.has(row.recruiterId)) continue;
    byId.set(row.recruiterId, row.recruiterName ?? `Użytkownik #${row.recruiterId}`);
  }
  return Array.from(byId, ([id, name]) => ({ id, name })).sort((a, b) =>
    a.name.localeCompare(b.name, "pl"),
  );
}

// ── Sortowanie ────────────────────────────────────────────────────────

export type PersonSortKey = "action" | "days" | "fit" | "name";

export interface PersonSort {
  key: PersonSortKey;
  dir: "asc" | "desc";
}

/** Domyślnie: najpierw to, co wymaga MOJEGO ruchu. */
export const DEFAULT_PERSON_SORT: PersonSort = { key: "action", dir: "asc" };

export const PERSON_SORT_LABEL: Record<PersonSortKey, string> = {
  action: "Wymaga ruchu",
  days: "W etapie najdłużej",
  fit: "Dopasowanie",
  name: "Nazwisko",
};

/**
 * Kierunek, w którym dany klucz ma sens „na start": najdłużej w etapie
 * i najlepsze dopasowanie na górze, nazwiska od A.
 */
export const PERSON_SORT_PRESET: Record<PersonSortKey, PersonSort> = {
  action: DEFAULT_PERSON_SORT,
  days: { key: "days", dir: "desc" },
  fit: { key: "fit", dir: "desc" },
  name: { key: "name", dir: "asc" },
};

const TONE_RANK: Record<NextAction["tone"], number> = { gate: 0, due: 1, normal: 2 };

function lastNameKey(row: PersonRow): string {
  const last =
    row.kind === "process" ? (row.item.lastname ?? "").trim() : "";
  return foldText(last || row.fullName.split(/\s+/).slice(-1)[0] || row.fullName);
}

function byName(a: PersonRow, b: PersonRow): number {
  return (
    lastNameKey(a).localeCompare(lastNameKey(b), "pl") ||
    a.fullName.localeCompare(b.fullName, "pl")
  );
}

function actionRank(row: PersonRow): number {
  if (row.kind !== "process") return 3;
  // Ruch po mojej stronie: bramka (weto HM) > po terminie > zwykły.
  if (row.nextAction.owner === "recruiter") return TONE_RANK[row.nextAction.tone];
  return 3;
}

function days(row: PersonRow): number {
  return row.kind === "process" ? (row.daysInStage ?? -1) : -1;
}

/**
 * Sortowanie — nowa tablica, wejście nietknięte.
 *
 * `fit`: brak wyniku ląduje NA KOŃCU w obu kierunkach — „nie policzono" nie
 * jest ani najlepszym, ani najgorszym dopasowaniem.
 */
export function sortRows<Row extends PersonRow>(
  rows: readonly Row[],
  sort: PersonSort = DEFAULT_PERSON_SORT,
): Row[] {
  const sign = sort.dir === "desc" ? -1 : 1;
  const compare = (a: Row, b: Row): number => {
    switch (sort.key) {
      case "action":
        return (
          sign * (actionRank(a) - actionRank(b)) || days(b) - days(a) || byName(a, b)
        );
      case "days":
        return sign * (days(a) - days(b)) || byName(a, b);
      case "fit": {
        if (a.fitScore == null || b.fitScore == null) {
          if (a.fitScore == null && b.fitScore == null) return byName(a, b);
          return a.fitScore == null ? 1 : -1;
        }
        return sign * (a.fitScore - b.fitScore) || byName(a, b);
      }
      case "name":
        return sign * byName(a, b);
      default:
        return 0;
    }
  };
  return [...rows].sort(compare);
}

// ── Grupy „kto ma ruch" ───────────────────────────────────────────────

export type OwnerGroupKey =
  | "mine"
  | "review"
  | "client"
  | "candidate"
  | "delivery"
  | "stale"
  | "closed";

export const OWNER_GROUP_LABEL: Record<OwnerGroupKey, string> = {
  mine: "Wymaga mojego ruchu",
  review: "Do przejrzenia",
  client: "Czeka na klienta",
  candidate: "Czeka na kandydata",
  delivery: "Delivery",
  stale: `Bez ruchu ponad ${STALE_DAYS} dni`,
  closed: "Zamknięci",
};

const OWNER_GROUP_ORDER: readonly OwnerGroupKey[] = [
  "mine",
  "client",
  "candidate",
  "delivery",
  "review",
  "stale",
  "closed",
];

/** Grupy zwinięte na starcie — osoby bez ruchu od dwóch tygodni to przegląd, nie praca na dziś. */
export const DEFAULT_COLLAPSED_GROUPS: readonly OwnerGroupKey[] = ["review", "stale"];

export function ownerGroupOf(row: ProcessPersonRow): OwnerGroupKey {
  if (row.nextAction.owner === "none") return "closed";
  if (row.nextAction.owner === "delivery") return "delivery";
  // Stos wejściowy jest przeglądem niezależnie od wieku — inaczej zgłoszenia
  // sprzed miesięcy mieszałyby się w „Bez ruchu" z osobami, z którymi ktoś
  // już pracował.
  if (row.nextAction.owner === "review") return "review";
  // „Bez ruchu" wygrywa z właścicielem: po `NUDGE_DAYS` ruch i tak wraca do
  // rekrutera, więc bez tej gałęzi grupa byłaby zawsze pusta, a „Wymaga mojego
  // ruchu" puchłaby od osób, których nikt nie dotknął od tygodni.
  if ((row.daysInStage ?? 0) > STALE_DAYS) return "stale";
  if (row.nextAction.owner === "client") return "client";
  if (row.nextAction.owner === "candidate") return "candidate";
  return "mine";
}

/**
 * Grupy w stałej kolejności, tylko niepuste. Kolejność wierszy w grupie =
 * kolejność wejścia (czyli sortowanie wybrane przez użytkownika).
 */
export function groupRowsByOwner(rows: ProcessPersonRow[]): PersonRowGroup[] {
  const buckets = new Map<OwnerGroupKey, string[]>();
  for (const row of rows) {
    const key = ownerGroupOf(row);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(row.key);
    else buckets.set(key, [row.key]);
  }
  return OWNER_GROUP_ORDER.filter((key) => buckets.has(key)).map((key) => ({
    key,
    label: OWNER_GROUP_LABEL[key],
    rowKeys: buckets.get(key) as string[],
  }));
}

/** Czy tabela ma grupować: wybór użytkownika wygrywa, inaczej próg. */
export function shouldGroupRows(rowCount: number, userChoice: boolean | null): boolean {
  return userChoice ?? rowCount > AUTO_GROUP_THRESHOLD;
}

// ── Liczniki paska etapów ─────────────────────────────────────────────

export interface SegmentCounts {
  inProcess: number;
  groups: Partial<Record<PipelineGroupKey, number>>;
  /** Po `stage_def_id`. */
  stages: Record<number, number>;
  offTemplate: number;
  closed: number;
}

function sizeOf(col: KanbanColumn): number {
  return col.count ?? col.items?.length ?? 0;
}

/**
 * Liczniki segmentów. „W procesie" dolicza kubełek poza szablonem, bo tabela
 * pod tym segmentem te osoby POKAZUJE — licznik obiecujący mniej wierszy, niż
 * widać, czyta się jak błąd.
 */
export function segmentCounts(
  columns: KanbanColumn[],
  offTemplate?: OffTemplateBucket | null,
): SegmentCounts {
  const groups: Partial<Record<PipelineGroupKey, number>> = {};
  const stages: Record<number, number> = {};
  for (const group of groupKanbanColumns(columns)) {
    groups[group.key] = group.columns.reduce((sum, col) => sum + sizeOf(col), 0);
    for (const col of group.columns) {
      if (col.stage_def_id != null) stages[col.stage_def_id] = sizeOf(col);
    }
  }
  const offTemplateCount = offTemplate ? (offTemplate.count ?? offTemplate.items.length) : 0;
  const inProcess = countInProcess(columns) + offTemplateCount;
  return {
    inProcess,
    groups,
    stages,
    offTemplate: offTemplateCount,
    closed: groups.closed ?? 0,
  };
}

/** Sekcja panelu otwierana domyślnie dla etapu, na którym stoi osoba. */
export function defaultPanelSectionFor(
  group: PipelineGroupKey,
  column?: FlowColumn,
): "cv" | "screening" | "interviews" | "contract" | "notes" {
  // Grupa „u klienta" obejmuje też „CV Wysłane" i własne etapy przed rozmową
  // (np. „Preparation Meeting"). Warsztat rozmów obsługuje wyłącznie etapy
  // rozmów — dla reszty panel otwierał pustą sekcję „Rozmowy" (produkcja,
  // 21.09.2026). Tam właściwa jest sekcja CV (co i kiedy poszło do klienta).
  if (group === "client" && column && !isInterviewStage(column)) return "cv";
  switch (group) {
    case "screening":
      return "screening";
    case "verification":
      return "cv";
    case "client":
      return "interviews";
    case "contract":
      return "contract";
    default:
      return "notes";
  }
}
