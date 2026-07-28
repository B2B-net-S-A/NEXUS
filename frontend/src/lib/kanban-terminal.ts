/**
 * Który terminal reprezentuje kolumna Kanbana.
 *
 * Osobny moduł, a nie funkcja lokalna w `KanbanBoardV2`, żeby test wiązał się
 * z TĄ SAMĄ funkcją, której używa komponent — test odtwarzający logikę
 * sprawdza własną kopię i przestaje chronić w chwili, gdy oryginał się zmieni.
 */

export type TerminalType = "hired" | "rejected" | "withdrawn";

export interface TerminalAwareColumn {
  stage: string;
  terminal_type?: TerminalType | null;
}

const LEGACY_TERMINAL_STAGES: ReadonlySet<TerminalType> = new Set([
  "hired",
  "rejected",
  "withdrawn",
]);

/**
 * `terminal_type` z definicji etapu, z fallbackiem na legacy `stage`.
 *
 * Kolumna bez mapowania na legacy enum raportuje `stage: "new"`, więc
 * rozpoznawanie terminala po samym `stage` gubiło WŁASNE etapy terminalne:
 * „odrzucony" nie otwierał modala powodu (backend odbijał 422), a
 * „zatrudniony" pomijał potwierdzenie mimo skutków ubocznych.
 *
 * Fallback obsługuje odpowiedzi sprzed dodania pola — dla nich zachowanie
 * pozostaje dokładnie takie jak wcześniej.
 */
export function terminalOf(col: TerminalAwareColumn): TerminalType | null {
  if (col.terminal_type) return col.terminal_type;
  return (LEGACY_TERMINAL_STAGES as ReadonlySet<string>).has(col.stage)
    ? (col.stage as TerminalType)
    : null;
}
