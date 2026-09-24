/**
 * Kolumny tabeli „Kandydaci” — każdy wybiera własne (Traffit: ikona zębatki
 * nad tabelą). Wybór żyje w przeglądarce (`useUiStore.columnPreferences`,
 * klucz `CANDIDATE_TABLE_PREFS_KEY`, lista UKRYTYCH id — semantyka v1 tego
 * pola). „Kandydat” i „Przypisz” są zawsze: bez nich wiersz nie ma sensu.
 */

export type CandidateColumnId =
  | "candidate"
  | "position"
  | "phone"
  | "email"
  | "location"
  | "rate"
  | "availability"
  | "experience"
  | "process"
  | "last_contact"
  | "added"
  | "cv"
  | "assign";

export interface CandidateColumn {
  id: CandidateColumnId;
  label: string;
  width: string;
  minWidth: number;
  /** Zawsze widoczna — bez przełącznika. */
  required?: boolean;
  /** Ukryta, dopóki ktoś jej nie włączy. */
  hiddenByDefault?: boolean;
}

export const CANDIDATE_TABLE_PREFS_KEY = "candidates-table-v2";

/** Kolejność = kolejność w tabeli. */
export const CANDIDATE_COLUMNS: readonly CandidateColumn[] = [
  { id: "candidate", label: "Kandydat", width: "minmax(168px, 1.5fr)", minWidth: 168, required: true },
  { id: "position", label: "Ostatnie stanowisko", width: "minmax(150px, 1.5fr)", minWidth: 150 },
  { id: "phone", label: "Telefon", width: "minmax(132px, 1fr)", minWidth: 132 },
  { id: "email", label: "E-mail", width: "minmax(150px, 1.2fr)", minWidth: 150, hiddenByDefault: true },
  { id: "location", label: "Lokalizacja", width: "minmax(100px, 0.8fr)", minWidth: 100, hiddenByDefault: true },
  { id: "rate", label: "Stawka B2B", width: "minmax(72px, 0.6fr)", minWidth: 72 },
  { id: "availability", label: "Dostępność", width: "minmax(88px, 0.8fr)", minWidth: 88 },
  { id: "experience", label: "Staż", width: "minmax(64px, 0.5fr)", minWidth: 64, hiddenByDefault: true },
  { id: "process", label: "W procesie", width: "minmax(112px, 1fr)", minWidth: 112 },
  { id: "last_contact", label: "Ostatni kontakt", width: "minmax(96px, 0.7fr)", minWidth: 96, hiddenByDefault: true },
  { id: "added", label: "Dodano", width: "minmax(88px, 0.6fr)", minWidth: 88, hiddenByDefault: true },
  { id: "cv", label: "CV", width: "minmax(52px, 0.4fr)", minWidth: 52 },
  { id: "assign", label: "Przypisz", width: "104px", minWidth: 104, required: true },
];

const KNOWN = new Set<string>(CANDIDATE_COLUMNS.map((c) => c.id));

/** Ukryte kolumny, gdy ktoś jeszcze nic nie wybierał. */
export const DEFAULT_HIDDEN_COLUMNS: readonly CandidateColumnId[] = CANDIDATE_COLUMNS.filter(
  (c) => c.hiddenByDefault,
).map((c) => c.id);

/** Widoczne kolumny z listy ukrytych (`null` = domyślne). Nieznane id i próby
 *  ukrycia kolumny wymaganej są ignorowane. */
export function visibleCandidateColumns(hidden: readonly string[] | null | undefined): CandidateColumn[] {
  const hide = new Set((hidden ?? DEFAULT_HIDDEN_COLUMNS).filter((id) => KNOWN.has(id)));
  return CANDIDATE_COLUMNS.filter((c) => c.required || !hide.has(c.id));
}

/** Nowa lista ukrytych po przełączeniu kolumny. */
export function toggleCandidateColumn(
  hidden: readonly string[] | null | undefined,
  id: CandidateColumnId,
): string[] {
  const current = new Set(hidden ?? DEFAULT_HIDDEN_COLUMNS);
  if (current.has(id)) current.delete(id);
  else current.add(id);
  return CANDIDATE_COLUMNS.filter((c) => current.has(c.id) && !c.required).map((c) => c.id);
}

/** Odstęp między kolumnami siatki wiersza (`gap-3`). */
export const CANDIDATE_GRID_GAP_PX = 12;
/** Poziomy padding wiersza i nagłówka (`px-4` z obu stron). */
export const CANDIDATE_GRID_PADDING_X_PX = 16;

/** `grid-template-columns` (z kolumną zaznaczenia) i minimalna szerokość wiersza.
 *  Minimalna szerokość liczy też odstępy między kolumnami i padding wiersza —
 *  bez nich kontener był o ~130 px węższy niż siatka i ostatnie kolumny
 *  („Przypisz”, CV) wypadały poza obszar przewijania. */
export function candidateGridLayout(columns: readonly CandidateColumn[]): {
  template: string;
  minWidth: number;
} {
  return {
    template: ["32px", ...columns.map((c) => c.width)].join(" "),
    minWidth:
      32 +
      columns.reduce((sum, c) => sum + c.minWidth, 0) +
      CANDIDATE_GRID_GAP_PX * columns.length +
      2 * CANDIDATE_GRID_PADDING_X_PX,
  };
}
