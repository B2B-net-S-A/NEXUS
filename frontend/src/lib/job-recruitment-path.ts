/**
 * „Ścieżka rekrutacji" w nagłówku rekrutacji i pole „Najbliższy krok"
 * (24.09.2026, zatwierdzone przez właściciela).
 *
 * Pięć kroków — Zlecenie → Kandydaci → CV do klienta → Rozmowy → Umowa —
 * każdy z kropką stanu i JEDNĄ linią faktu. Czysty moduł: czyta wyłącznie to,
 * co strona już pobiera (tablica, gotowość zlecenia, liczba propozycji), bez
 * własnych zapytań. Kolumny Tablicy składa ta sama reguła co render
 * (`foldBoardColumns`), więc liczba „w QC" na ścieżce i nagłówek kolumny
 * „QC CV" nie mogą się rozjechać.
 */

import {
  BOARD_COLUMN_ORDER,
  foldBoardColumns,
  type BoardColumnKey,
  type FoldableColumn,
} from "@/lib/board-stages";

// ── Podsumowanie Tablicy ─────────────────────────────────────────────────

export type BoardColumnCounts = Record<Exclude<BoardColumnKey, "closed">, number>;

export interface BoardSummary {
  counts: BoardColumnCounts;
  /** Osoby w kolumnach procesu (bez zamkniętych i bez „Zatrudniony"). */
  inProcess: number;
  /** Najbliższa zaplanowana rozmowa u klienta (ISO) albo `null`. */
  nextInterviewAt: string | null;
}

interface SummaryItem {
  id: number;
  interview_badge?: { kind?: string | null; at?: string | null } | null;
}

interface SummaryColumn extends FoldableColumn {
  items: ReadonlyArray<SummaryItem>;
}

function emptyCounts(): BoardColumnCounts {
  return {
    new: 0,
    screening: 0,
    verified: 0,
    cv_qc: 0,
    cv_sent: 0,
    client_interview: 0,
    contract: 0,
    hired: 0,
  };
}

/**
 * Liczby per kolumna Tablicy + najbliższa rozmowa u klienta.
 *
 * Własne etapy szablonu bez znanego znaczenia (`key === null`) liczą się do
 * „w procesie", ale nie do żadnego kroku ścieżki — nie zgadujemy, czym są.
 */
export function summarizeBoard(
  columns: readonly SummaryColumn[],
  options: { cproEnabled?: boolean; now?: Date } = {},
): BoardSummary {
  const fold = foldBoardColumns(columns, { cproEnabled: options.cproEnabled });
  const counts = emptyCounts();
  let inProcess = 0;
  const nowMs = (options.now ?? new Date()).getTime();
  let nextMs: number | null = null;
  let nextAt: string | null = null;

  for (const f of fold.columns) {
    if (f.key && f.key !== "closed") counts[f.key] += f.count;
    if (f.key !== "hired") inProcess += f.count;
    if (f.key !== "client_interview") continue;
    for (const item of f.items as ReadonlyArray<SummaryItem>) {
      const at = item.interview_badge?.at;
      if (!at) continue;
      const ms = Date.parse(at);
      if (!Number.isFinite(ms) || ms < nowMs) continue;
      if (nextMs == null || ms < nextMs) {
        nextMs = ms;
        nextAt = at;
      }
    }
  }
  return { counts, inProcess, nextInterviewAt: nextAt };
}

// ── Ścieżka ──────────────────────────────────────────────────────────────

export type PathStepKey = "order" | "candidates" | "cv" | "interviews" | "contract";

/** gotowe ✓ · trwa ● · brak ! · przed nami ○ */
export type PathStepState = "done" | "active" | "missing" | "todo";

export interface PathStep {
  key: PathStepKey;
  label: string;
  state: PathStepState;
  /** Jedna linia stanu pod nazwą kroku. */
  detail: string;
}

export interface RecruitmentPathInput {
  /**
   * Braki zlecenia wg bramki gotowości; `null` = nie wiadomo (rola spoza
   * bramki albo zapytanie w toku) — krok nie udaje wtedy kompletu.
   */
  orderMissing: number | null;
  /** `null` = tablica się jeszcze nie wczytała. */
  board: BoardSummary | null;
  /** Propozycje z bazy do przejrzenia; `null` = nie wiadomo. */
  proposals: number | null;
  headcount: number | null;
  now?: Date;
}

export const PATH_STEP_LABEL: Record<PathStepKey, string> = {
  order: "Zlecenie",
  candidates: "Kandydaci",
  cv: "CV do klienta",
  interviews: "Rozmowy",
  contract: "Umowa",
};

function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function dayStart(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** „dziś" / „jutro" / „pojutrze" / „DD.MM" — dzień w strefie przeglądarki. */
export function relativeDayLabel(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const diff = Math.round((dayStart(at) - dayStart(now)) / 86_400_000);
  if (diff === 0) return "dziś";
  if (diff === 1) return "jutro";
  if (diff === 2) return "pojutrze";
  const dd = String(at.getDate()).padStart(2, "0");
  const mm = String(at.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}`;
}

function orderStep(missing: number | null): PathStep {
  const base = { key: "order" as const, label: PATH_STEP_LABEL.order };
  if (missing == null) return { ...base, state: "todo", detail: "otwórz zlecenie" };
  if (missing > 0) return { ...base, state: "missing", detail: `brakuje ${missing} — uzupełnij` };
  return { ...base, state: "done", detail: "kompletne" };
}

function candidatesStep(board: BoardSummary | null, proposals: number | null): PathStep {
  const base = { key: "candidates" as const, label: PATH_STEP_LABEL.candidates };
  if (!board) return { ...base, state: "todo", detail: "wczytywanie…" };
  const parts = [`${board.inProcess} w procesie`];
  if (proposals != null && proposals > 0) {
    parts.push(`${proposals} ${plural(proposals, "propozycja", "propozycje", "propozycji")}`);
  }
  if (board.inProcess === 0 && !(proposals && proposals > 0)) {
    return { ...base, state: "missing", detail: "nikogo jeszcze — dodaj kandydatów" };
  }
  return { ...base, state: "active", detail: parts.join(" · ") };
}

function laterThan(counts: BoardColumnCounts, key: BoardColumnKey): number {
  const at = BOARD_COLUMN_ORDER.indexOf(key);
  return BOARD_COLUMN_ORDER.slice(at + 1).reduce(
    (sum, k) => sum + counts[k as keyof BoardColumnCounts],
    0,
  );
}

function cvStep(board: BoardSummary | null): PathStep {
  const base = { key: "cv" as const, label: PATH_STEP_LABEL.cv };
  if (!board) return { ...base, state: "todo", detail: "—" };
  const { counts } = board;
  const sent = counts.cv_sent;
  const detail = `${counts.cv_qc} w QC · ${sent} ${plural(sent, "wysłane", "wysłane", "wysłanych")}`;
  if (counts.cv_qc > 0 || counts.verified > 0) return { ...base, state: "active", detail };
  if (sent > 0 || laterThan(counts, "cv_sent") > 0) return { ...base, state: "done", detail };
  return { ...base, state: "todo", detail };
}

function interviewsStep(board: BoardSummary | null, now: Date): PathStep {
  const base = { key: "interviews" as const, label: PATH_STEP_LABEL.interviews };
  if (!board) return { ...base, state: "todo", detail: "—" };
  const n = board.counts.client_interview;
  const next = board.nextInterviewAt
    ? `najbliższa ${relativeDayLabel(board.nextInterviewAt, now)}`
    : "brak zaplanowanych";
  if (n > 0) {
    return {
      ...base,
      state: "active",
      detail: `${n} ${plural(n, "rozmowa", "rozmowy", "rozmów")} · ${next}`,
    };
  }
  if (laterThan(board.counts, "client_interview") > 0) {
    return { ...base, state: "done", detail: next };
  }
  return { ...base, state: "todo", detail: next };
}

function contractStep(board: BoardSummary | null, headcount: number | null): PathStep {
  const base = { key: "contract" as const, label: PATH_STEP_LABEL.contract };
  const hired = board?.counts.hired ?? null;
  const detail = `obsada ${hired ?? "—"} / ${headcount ?? "—"}`;
  if (!board) return { ...base, state: "todo", detail };
  if (headcount != null && headcount > 0 && board.counts.hired >= headcount) {
    return { ...base, state: "done", detail };
  }
  if (board.counts.contract > 0 || board.counts.hired > 0) {
    return { ...base, state: "active", detail };
  }
  return { ...base, state: "todo", detail };
}

export function buildRecruitmentPath(input: RecruitmentPathInput): PathStep[] {
  const now = input.now ?? new Date();
  return [
    orderStep(input.orderMissing),
    candidatesStep(input.board, input.proposals),
    cvStep(input.board),
    interviewsStep(input.board, now),
    contractStep(input.board, input.headcount),
  ];
}

// ── Najbliższy krok ──────────────────────────────────────────────────────

export type NearestStepAction =
  | { kind: "order" }
  | { kind: "column"; column: BoardColumnKey }
  | { kind: "add"; tab: "proposals" | "search" };

export interface NearestStep {
  /** Stały klucz reguły (testy, telemetria). */
  rule: "order" | "qc" | "verified" | "proposals" | "search";
  sentence: string;
  cta: string;
  action: NearestStepAction;
}

export interface NearestStepInput {
  orderMissing: number | null;
  board: BoardSummary | null;
  proposals: number | null;
  /** Czy patrzący może dodawać kandydatów (zapis pipeline'u). */
  canAddCandidates: boolean;
}

/**
 * Jedno zdanie „co teraz" — PIERWSZA pasująca reguła:
 *  1. zlecenie niekompletne,
 *  2. osoby w QC CV,
 *  3. osoby w „Zweryfikowany",
 *  4. propozycje z bazy do przejrzenia,
 *  5. pusto w „Nowi" i „Screening" → szukaj w bazie (AI).
 * Inaczej `null` — pole się nie pokazuje (lepiej nic niż zdanie o niczym).
 */
export function nearestStep(input: NearestStepInput): NearestStep | null {
  const { orderMissing, board, proposals, canAddCandidates } = input;
  if (orderMissing != null && orderMissing > 0) {
    return {
      rule: "order",
      sentence: `Uzupełnij zlecenie (brakuje ${orderMissing})`,
      cta: "Otwórz zlecenie",
      action: { kind: "order" },
    };
  }
  if (!board) return null;
  if (board.counts.cv_qc > 0) {
    return {
      rule: "qc",
      sentence: `Sprawdź CV w QC (${board.counts.cv_qc})`,
      cta: "Pokaż QC CV",
      action: { kind: "column", column: "cv_qc" },
    };
  }
  if (board.counts.verified > 0) {
    return {
      rule: "verified",
      sentence: `Przygotuj CV do QC (${board.counts.verified})`,
      cta: "Pokaż Zweryfikowanych",
      action: { kind: "column", column: "verified" },
    };
  }
  if (!canAddCandidates) return null;
  if (proposals != null && proposals > 0) {
    return {
      rule: "proposals",
      sentence: `Przejrzyj ${proposals} ${plural(proposals, "propozycję", "propozycje", "propozycji")} z bazy`,
      cta: "Przejrzyj",
      action: { kind: "add", tab: "proposals" },
    };
  }
  if (board.counts.new === 0 && board.counts.screening === 0) {
    return {
      rule: "search",
      sentence: "Znajdź kandydatów w bazie (AI)",
      cta: "Szukaj w bazie",
      action: { kind: "add", tab: "search" },
    };
  }
  return null;
}
