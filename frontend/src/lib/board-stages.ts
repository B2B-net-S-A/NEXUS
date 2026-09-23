/**
 * Tablica rekrutacji: 6 kolumn — Nowi · Zweryfikowany · CV wysłane · Rozmowa
 * u klienta · Umowa · Zatrudniony (decyzja Artura 23.09.2026, makiety
 * https://claude.ai/artifact/JQ8qdz16J6wG24WKTSgv6i). Do 22.09 było 9 kolumn;
 * „Do przejrzenia”, „Screening” i „Akceptacja” są teraz odznakami.
 *
 * Szablony etapów w bazie ZOSTAJĄ — nocny import z Traffita zapisuje ruch na
 * dokładny stan swojego procesu (15 i 18 stanów), a usunięcie etapu wrzuciłoby
 * te osoby do „Poza szablonem". Ten moduł tylko TŁUMACZY etap szablonu na
 * kolumnę Tablicy, a to, co nie jest krokiem procesu, na odznakę na karcie:
 *
 *   Ogłoszenia, Screening   → „Nowi" + „Z ogłoszenia"/„Screening"
 *   Przepuszczony przez DZ → „Zweryfikowany" + „DZ ✓"
 *   Wysłać do Cpro          → „Zweryfikowany" + „Gotowy do Cpro" (Nordea)
 *   Preparation Meeting     → „Rozmowa u klienta" + „Prep"
 *   Akceptacja              → „Umowa" + „Akceptacja"
 *   Umowa wysłana/podpisana → „Umowa" + „wysłana"/„podpisana"
 *   Onboarding              → „Zatrudniony" + „Onboarding"
 *   Odrzucony, Wycofany     → pasek pod tablicą
 *
 * Statystyki liczą dalej każdy etap osobno — tablica tylko składa kolumny.
 * Reguła ma lustro w backendzie (`services/board_stage_badges.py`: kto może
 * ustawić odznakę, `board_column_for` — kolumna dla blokady 12 h i
 * statystyk). Oba czytają `__fixtures__/board-stage-cases.json`.
 */

export type BoardColumnKey =
  | "new"
  | "verified"
  | "cv_sent"
  | "client_interview"
  | "contract"
  | "hired"
  | "closed";

export type StageBadgeKey =
  | "posting"
  | "screening"
  | "acceptance"
  | "dz"
  | "cpro"
  | "prep"
  | "after_interview"
  | "contract_sent"
  | "contract_signed"
  | "onboarding";

export const BOARD_COLUMN_ORDER: readonly BoardColumnKey[] = [
  "new",
  "verified",
  "cv_sent",
  "client_interview",
  "contract",
  "hired",
];

export const BOARD_COLUMN_LABEL: Record<BoardColumnKey, string> = {
  new: "Nowi",
  verified: "Zweryfikowany",
  cv_sent: "CV wysłane",
  client_interview: "Rozmowa u klienta",
  contract: "Umowa",
  hired: "Zatrudniony",
  closed: "Zamknięci",
};

/** U Nordei wysłanie CV do klienta TO JEST wysłanie do Cpro (decyzja Artura
 *  22.09.2026) — ta sama kolumna, inna nazwa. */
export const CPRO_SENT_COLUMN_LABEL = "Wysłane do Cpro";

export interface FoldBoardOptions {
  /** Rekrutacja Nordei (`job.cpro_enabled`): „CV wysłane" → „Wysłane do Cpro". */
  cproEnabled?: boolean;
}

function boardColumnLabel(key: BoardColumnKey, options: FoldBoardOptions): string {
  if (key === "cv_sent" && options.cproEnabled) return CPRO_SENT_COLUMN_LABEL;
  return BOARD_COLUMN_LABEL[key];
}

export const STAGE_BADGE_LABEL: Record<StageBadgeKey, string> = {
  posting: "Z ogłoszenia",
  screening: "Screening",
  acceptance: "Akceptacja",
  dz: "DZ ✓",
  cpro: "Gotowy do Cpro",
  prep: "Prep",
  after_interview: "Po rozmowie",
  contract_sent: "wysłana",
  contract_signed: "podpisana",
  onboarding: "Onboarding",
};

export const STAGE_BADGE_TITLE: Record<StageBadgeKey, string> = {
  posting: "Osoba z ogłoszenia — jeszcze nikt z nią nie rozmawiał",
  screening: "Etap „Screening” (z Traffita) — rozmowa w toku",
  acceptance: "Klient zaakceptował — umowa jeszcze nie wysłana",
  dz: "Zweryfikowany przez DZ (Delivery Lead / Dominik)",
  cpro: "Gotowy do wysłania w systemie Cpro Nordei",
  prep: "Przygotowanie do rozmowy u klienta",
  after_interview: "Rozmowa u klienta się odbyła — czekamy na decyzję",
  contract_sent: "Umowa wysłana",
  contract_signed: "Umowa podpisana",
  onboarding: "Onboarding przed startem pracy",
};

export interface StageLike {
  stage?: string | null;
  label?: string | null;
  name?: string | null;
  category?: string | null;
  terminal_type?: string | null;
}

export interface StagePlacement {
  column: BoardColumnKey;
  badge: StageBadgeKey | null;
}

/** Nazwa etapu → klucz dopasowania: małe litery, bez polskich znaków. */
export function normalizeStageName(name: string | null | undefined): string {
  return (name ?? "")
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .trim();
}

/** Etap „Przepuszczony przez DZ" — lustro `is_dz_stage` w backendzie. */
export function isDzStageName(name: string | null | undefined): boolean {
  const n = normalizeStageName(name);
  return /\bdz\b/.test(n) || n.includes("przepuszcz");
}

/** Etap „Wysłać do Cpro" (Nordea) — lustro `is_cpro_stage` w backendzie. */
export function isCproStageName(name: string | null | undefined): boolean {
  return /\bcpro\b/.test(normalizeStageName(name));
}

const BY_ENUM: Record<string, BoardColumnKey> = {
  posting: "new",
  new: "new",
  prep_call: "new",
  screening: "new",
  verified: "verified",
  interview: "verified",
  cv_sent: "cv_sent",
  client_interview: "client_interview",
  acceptance: "contract",
  negotiation: "contract",
  onboarding: "hired",
  hired: "hired",
  rejected: "closed",
  withdrawn: "closed",
};

/** Etap szablonu → kolumna Tablicy i odznaka (bez odznaki = `null`). */
export function placeStage(col: StageLike): StagePlacement {
  const raw = col.label ?? col.name ?? "";
  const n = normalizeStageName(raw);
  if (isDzStageName(raw)) return { column: "verified", badge: "dz" };
  if (isCproStageName(raw)) return { column: "verified", badge: "cpro" };
  if (n.includes("umowa podpis")) return { column: "contract", badge: "contract_signed" };
  if (n.includes("umowa wysl")) return { column: "contract", badge: "contract_sent" };
  if (n.includes("po interview") || n.includes("po rozmowie")) {
    return { column: "client_interview", badge: "after_interview" };
  }
  if (
    n.includes("prep") ||
    n.includes("pre-interview") ||
    n.includes("przygotowany do spotkania")
  ) {
    return { column: "client_interview", badge: "prep" };
  }
  if (n.includes("onboarding")) return { column: "hired", badge: "onboarding" };
  if (n.includes("rezerw")) return { column: "closed", badge: null };
  if (col.stage === "hired" || col.terminal_type === "hired") {
    return { column: "hired", badge: null };
  }
  if (col.category === "terminal") return { column: "closed", badge: null };
  // Odznaki z KODU etapu (nie z nazwy): kolumny, które zniknęły 23.09.2026.
  if (col.stage === "posting") return { column: "new", badge: "posting" };
  if (col.stage === "screening" || col.stage === "prep_call") {
    return { column: "new", badge: "screening" };
  }
  if (col.stage === "acceptance") return { column: "contract", badge: "acceptance" };
  return { column: BY_ENUM[col.stage ?? ""] ?? "new", badge: null };
}

export interface FoldableColumn extends StageLike {
  items: ReadonlyArray<{ id: number }>;
  count: number;
}

export interface BoardColumnFold<C extends FoldableColumn> {
  /** Kolumna Tablicy albo `null` = własny etap szablonu bez znanego znaczenia. */
  key: BoardColumnKey | null;
  /** Nagłówek kolumny. */
  label: string;
  /** Kolumna szablonu, do której trafia karta upuszczona na tę kolumnę. */
  host: C;
  /** Wszystkie kolumny szablonu wpadające do tej kolumny Tablicy. */
  members: C[];
  /** Karty w kolejności kolumn szablonu (host pierwszy). */
  items: C["items"][number][];
  count: number;
}

const CANONICAL_ENUM: Partial<Record<BoardColumnKey, string>> = {
  verified: "verified",
  cv_sent: "cv_sent",
  client_interview: "client_interview",
  hired: "hired",
};

/** „Zaakceptowany (#41)" → „zaakceptowany" — importer dokleja sufiks przy duplikatach. */
function baseName(col: StageLike): string {
  return normalizeStageName((col.label ?? col.name ?? "").replace(/\s*\(#\d+\)\s*$/, ""));
}

/**
 * Składa kolumny szablonu w kolumny Tablicy. JEDEN etap = JEDNA kolumna —
 * łączą się WYŁĄCZNIE:
 *  - etapy-odznaki rozpoznane po nazwie (DZ, Cpro, Prep, Umowa, Onboarding)
 *    z etapem swojej kolumny (np. „Przepuszczony przez DZ" → „Zweryfikowany"),
 *  - duplikaty nazw z importu („Zaakceptowany (#41)" → „Zaakceptowany").
 * Własny etap szablonu bez znanego znaczenia (kod zastępczy `new` poza
 * pierwszym) zostaje osobną kolumną z własną nazwą — inaczej szablon
 * z samych własnych etapów złożyłby się w jedną kolumnę „Nowi".
 * Zamknięci (odrzuceni, wycofani, rezerwa) wracają osobno — Tablica pokazuje
 * ich paskiem.
 */
export function foldBoardColumns<C extends FoldableColumn>(
  columns: readonly C[],
  options: FoldBoardOptions = {},
): { columns: BoardColumnFold<C>[]; closed: C[]; badgeByItemId: Map<number, StageBadgeKey> } {
  const closed: C[] = [];
  const badgeByItemId = new Map<number, StageBadgeKey>();
  const folds: BoardColumnFold<C>[] = [];
  const hostByKey = new Map<BoardColumnKey, BoardColumnFold<C>>();
  const foldByBaseName = new Map<string, BoardColumnFold<C>>();
  const pendingBadged: Array<{ col: C; key: BoardColumnKey }> = [];
  let seenNew = false;

  for (const col of columns) {
    const { column, badge } = placeStage(col);
    if (badge) for (const item of col.items) badgeByItemId.set(item.id, badge);
    if (column === "closed") {
      closed.push(col);
      continue;
    }
    if (badge) {
      pendingBadged.push({ col, key: column });
      continue;
    }
    const duplicate = foldByBaseName.get(baseName(col));
    if (duplicate) {
      duplicate.members.push(col);
      continue;
    }
    // Nazwę i rolę kolumny Tablicy dostaje wyłącznie etap o KANONICZNYM
    // kodzie („verified" → „Zweryfikowany"). Kod `new` jest zastępczy dla
    // własnych etapów — znaczenie „Nowi" ma tylko pierwszy taki etap; inne
    // kody (np. `interview` = rozmowa wewnętrzna) zostają własną kolumną
    // z własną nazwą.
    const canonical =
      CANONICAL_ENUM[column] === col.stage ||
      (column === "hired" && col.terminal_type === "hired") ||
      (column === "new" && col.stage === "new" && !seenNew);
    if (column === "new" && col.stage === "new") seenNew = true;
    const key = canonical ? column : null;
    const fold: BoardColumnFold<C> = {
      key,
      label: key && !hostByKey.has(key) ? boardColumnLabel(key, options) : (col.label ?? col.name ?? ""),
      host: col,
      members: [col],
      items: [],
      count: 0,
    };
    folds.push(fold);
    foldByBaseName.set(baseName(col), fold);
    if (key && !hostByKey.has(key)) hostByKey.set(key, fold);
  }

  // Etap-odznaka dołącza do kolumny swojego znaczenia; gdy szablon jej nie
  // ma, zostaje własną kolumną (nie znika).
  for (const { col, key } of pendingBadged) {
    const host = hostByKey.get(key);
    if (host) {
      host.members.push(col);
      continue;
    }
    const fold: BoardColumnFold<C> = {
      key,
      label: boardColumnLabel(key, options),
      host: col,
      members: [col],
      items: [],
      count: 0,
    };
    hostByKey.set(key, fold);
    // Wstaw w kolejności szablonu (przed pierwszą kolumną, która stoi dalej).
    const order = columns.indexOf(col);
    const at = folds.findIndex((f) => columns.indexOf(f.host) > order);
    if (at < 0) folds.push(fold);
    else folds.splice(at, 0, fold);
  }

  for (const fold of folds) {
    fold.members.sort((a, b) => columns.indexOf(a) - columns.indexOf(b));
    // Gospodarz na początek: to on jest celem upuszczenia.
    fold.members = [fold.host, ...fold.members.filter((m) => m !== fold.host)];
    fold.items = fold.members.flatMap((c) => [...c.items]);
    fold.count = fold.members.reduce((sum, c) => sum + c.count, 0);
  }
  return { columns: folds, closed, badgeByItemId };
}

/**
 * Odznaki, które da się ustawić z panelu osoby: etap-odznaka z tej samej
 * kolumny Tablicy (ruch na ten etap). `cpro` wyłącznie u Nordei, `dz`
 * wyłącznie dla admina, Delivery Leada i Head of Recruitment — tę samą
 * regułę sprawdza serwer przy ruchu.
 */
export const SETTABLE_BADGES: readonly StageBadgeKey[] = ["dz", "cpro", "contract_signed"];

/**
 * Odznaki widoczne na karcie dla etapu-odznaki. „Wysłać do Cpro" stoi w procesie
 * PO „Przepuszczony przez DZ" — osoba gotowa do Cpro jest też zweryfikowana
 * przez DZ, więc karta pokazuje obie odznaki (inaczej ustawienie Cpro
 * „zabierało" DZ).
 */
export function impliedBadges(badge: StageBadgeKey | null | undefined): StageBadgeKey[] {
  if (!badge) return [];
  return badge === "cpro" ? ["dz", "cpro"] : [badge];
}
