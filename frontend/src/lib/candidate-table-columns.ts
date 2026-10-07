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
  | "fit"
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
  /**
   * Na szerokim ekranie widoczna od razu mimo `hiddenByDefault`. Na laptopie
   * (1280 px z przypiętym menu) tabela domyślna mieści się na styk — dodatkowa
   * kolumna wypychałaby „Przypisz” poza ekran.
   */
  wideDefault?: boolean;
  /**
   * Tylko w „Szukaj ręcznie” z rekrutacji (lista w trybie osadzonym) —
   * dopasowanie liczy się względem TEJ rekrutacji, na liście nie ma do czego.
   */
  jobOnly?: boolean;
}

export const CANDIDATE_TABLE_PREFS_KEY = "candidates-table-v2";
/** Osobny wybór kolumn dla „Szukaj ręcznie” z rekrutacji — panel nie nadpisuje listy. */
export const CANDIDATE_JOB_SEARCH_PREFS_KEY = "candidates-table-job-search";

/** Kolejność = kolejność w tabeli. */
export const CANDIDATE_COLUMNS: readonly CandidateColumn[] = [
  { id: "candidate", label: "Kandydat", width: "minmax(168px, 1.5fr)", minWidth: 168, required: true },
  { id: "position", label: "Ostatnie stanowisko", width: "minmax(150px, 1.5fr)", minWidth: 150 },
  { id: "phone", label: "Telefon", width: "minmax(132px, 1fr)", minWidth: 132 },
  { id: "email", label: "E-mail", width: "minmax(150px, 1.2fr)", minWidth: 150, hiddenByDefault: true },
  { id: "location", label: "Lokalizacja", width: "minmax(100px, 0.8fr)", minWidth: 100, hiddenByDefault: true },
  { id: "rate", label: "Stawka B2B", width: "minmax(72px, 0.6fr)", minWidth: 72 },
  // Druga linia „z notatki · DD.MM.RRRR” (07.10.2026) mieści się w tej samej
  // szerokości — ucina się, pełny opis w dymku; nie poszerzaj kolumny (laptop).
  { id: "availability", label: "Dostępność", width: "minmax(88px, 0.8fr)", minWidth: 88 },
  { id: "experience", label: "Staż", width: "minmax(64px, 0.5fr)", minWidth: 64, hiddenByDefault: true },
  { id: "process", label: "W procesie", width: "minmax(112px, 1fr)", minWidth: 112 },
  // „Ostatnia rozmowa” (03.10.2026): data i autor najnowszej notatki z rozmowy,
  // a bez niej liczba prób kontaktu. Id zostaje — niosą je zapisane wybory kolumn.
  { id: "last_contact", label: "Ostatnia rozmowa", width: "minmax(118px, 0.9fr)", minWidth: 118, hiddenByDefault: true, wideDefault: true },
  { id: "added", label: "Dodano", width: "minmax(88px, 0.6fr)", minWidth: 88, hiddenByDefault: true },
  { id: "cv", label: "CV", width: "minmax(52px, 0.4fr)", minWidth: 52 },
  { id: "fit", label: "Dop.", width: "72px", minWidth: 72, jobOnly: true },
  { id: "assign", label: "Przypisz", width: "104px", minWidth: 104, required: true },
];

const KNOWN = new Set<string>(CANDIDATE_COLUMNS.map((c) => c.id));

/** Ukryte kolumny, gdy ktoś jeszcze nic nie wybierał. */
export const DEFAULT_HIDDEN_COLUMNS: readonly CandidateColumnId[] = CANDIDATE_COLUMNS.filter(
  (c) => c.hiddenByDefault,
).map((c) => c.id);

/** Widoczne kolumny z listy ukrytych (`null` = domyślne). Nieznane id i próby
 *  ukrycia kolumny wymaganej są ignorowane. */
/**
 * Domyślnie ukryte w „Szukaj ręcznie”: okno ma ~1100 px, a z kolumną „Dop.”
 * pełny zestaw nie mieści się i „Dodaj” wypadało poza prawą krawędź.
 * Telefon da się włączyć w „Kolumny”.
 */
export const DEFAULT_HIDDEN_JOB_COLUMNS: readonly CandidateColumnId[] = [
  ...DEFAULT_HIDDEN_COLUMNS,
  "phone",
];

/** Od tej szerokości okna lista pokazuje domyślnie także kolumny `wideDefault`. */
export const CANDIDATE_WIDE_DEFAULT_QUERY = "(min-width: 1536px)";

const WIDE_DEFAULT = new Set<string>(
  CANDIDATE_COLUMNS.filter((c) => c.wideDefault).map((c) => c.id),
);

/**
 * Kolumna `wideDefault` w zapisanej liście ukrytych ma trzy stany:
 * - samo id na liście = brak decyzji osoby. Lista ukrytych powstaje
 *   z domyślnych przy pierwszym przełączeniu DOWOLNEJ kolumny, więc id trafia
 *   na nią samo — kolumna idzie wtedy za szerokością okna (inaczej wybór
 *   zapisany na dużym monitorze przyklejałby ją do laptopa);
 * - id + znacznik `:hidden` = osoba ją wyłączyła — ukryta na każdym ekranie;
 * - brak id = osoba ją włączyła — widoczna na każdym ekranie (tak też czyta
 *   się wybór zapisany przed tą zmianą).
 */
const hiddenMark = (id: string) => `${id}:hidden`;

export interface CandidateColumnOptions {
  forJob?: boolean;
  /** Szeroki ekran (`CANDIDATE_WIDE_DEFAULT_QUERY`) — tylko lista, nie „Szukaj ręcznie”. */
  wide?: boolean;
}

function defaultHidden(options: CandidateColumnOptions): readonly string[] {
  return options.forJob ? DEFAULT_HIDDEN_JOB_COLUMNS : DEFAULT_HIDDEN_COLUMNS;
}

function wideDefaultVisible(
  id: string,
  saved: ReadonlySet<string>,
  options: CandidateColumnOptions,
): boolean {
  if (saved.has(hiddenMark(id))) return false;
  if (!saved.has(id)) return true;
  return Boolean(options.wide) && !options.forJob;
}

export function visibleCandidateColumns(
  hidden: readonly string[] | null | undefined,
  options: CandidateColumnOptions = {},
): CandidateColumn[] {
  const saved = new Set(hidden ?? defaultHidden(options));
  return selectableCandidateColumns(options).filter((c) => {
    if (c.required) return true;
    if (WIDE_DEFAULT.has(c.id)) return wideDefaultVisible(c.id, saved, options);
    return !saved.has(c.id);
  });
}

/** Kolumny dostępne w danym widoku (lista vs „Szukaj ręcznie” z rekrutacji). */
export function selectableCandidateColumns(
  options: { forJob?: boolean } = {},
): CandidateColumn[] {
  return CANDIDATE_COLUMNS.filter((c) => !c.jobOnly || options.forJob);
}

/** Nowa lista ukrytych po przełączeniu kolumny. */
export function toggleCandidateColumn(
  hidden: readonly string[] | null | undefined,
  id: CandidateColumnId,
  options: CandidateColumnOptions = {},
): string[] {
  const current = new Set(hidden ?? defaultHidden(options));
  if (WIDE_DEFAULT.has(id)) {
    if (wideDefaultVisible(id, current, options)) {
      current.add(id);
      current.add(hiddenMark(id));
    } else {
      current.delete(id);
      current.delete(hiddenMark(id));
    }
  } else if (current.has(id)) current.delete(id);
  else current.add(id);
  return [
    ...CANDIDATE_COLUMNS.filter((c) => current.has(c.id) && !c.required).map((c) => c.id),
    ...[...WIDE_DEFAULT].map(hiddenMark).filter((mark) => current.has(mark)),
  ];
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
