/**
 * Lista plików kandydata (zakładka „Dokumenty”): kolejność, podpis
 * „dodano DD.MM.RRRR · kto” i grupy listy. Czyste funkcje — komponent tylko
 * renderuje.
 */

export interface CandidateFileListItem {
  id: number;
  is_primary: boolean;
  uploaded_at: string | null;
  created_at: string;
  external_source: string | null;
  uploaded_by_name?: string | null;
}

function addedAt(doc: CandidateFileListItem): number {
  const time = Date.parse(doc.uploaded_at ?? doc.created_at);
  return Number.isFinite(time) ? time : 0;
}

/** Główne CV pierwsze, potem najnowsze (`uploaded_at ?? created_at`). */
export function sortCandidateFiles<T extends CandidateFileListItem>(docs: readonly T[]): T[] {
  return [...docs].sort((a, b) => {
    if (a.is_primary !== b.is_primary) return a.is_primary ? -1 : 1;
    const byDate = addedAt(b) - addedAt(a);
    return byDate !== 0 ? byDate : b.id - a.id;
  });
}

const DATE_FORMAT = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

export function formatFileDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? DATE_FORMAT.format(new Date(time)) : null;
}

/** „dodano 29.09.2026 · Anna Nowak”, „… · z Traffita” albo sama data. */
export function fileAddedLabel(doc: CandidateFileListItem): string {
  const date = formatFileDate(doc.uploaded_at ?? doc.created_at);
  const name = doc.uploaded_by_name?.trim();
  const who = name ? name : doc.external_source === "traffit" ? "z Traffita" : null;
  return [date ? `dodano ${date}` : "dodano", who].filter(Boolean).join(" · ");
}

/**
 * CV przygotowane dla klienta (plik „…_B2B_….docx”) — od 04.10.2026 stoi
 * osobno od plików kandydata, w grupie „CV dla klientów” (decyzja D4).
 * Rozpoznajemy je wyłącznie po nazwie: „B2B” jako osobny człon nazwy. QC CV
 * i kolejka Cpro (`dz_review.pick_document_cv`) szukają szerzej (`%b2b%`), ale
 * tu chodzi tylko o grupę na liście — pomyłka nie zmienia żadnej decyzji.
 */
const CLIENT_CV_NAME = /(^|[_\s-])b2b([_\s.-]|$)/i;

export function isClientCvFilename(filename: string | null | undefined): boolean {
  return CLIENT_CV_NAME.test(filename ?? "");
}

/** Pliki kandydata i CV dla klientów — kolejność z `sortCandidateFiles`. */
export function splitClientCvFiles<T extends CandidateFileListItem & { filename?: string | null }>(
  docs: readonly T[],
): { own: T[]; client: T[] } {
  const own: T[] = [];
  const client: T[] = [];
  for (const doc of docs) (isClientCvFilename(doc.filename) ? client : own).push(doc);
  return { own, client };
}

/** Rekrutacja z `GET /api/candidates/{id}/history` — wystarcza tytuł. */
export interface RecruitmentCodeSource {
  job_title?: string | null;
}

/** Kod rekrutacji w tytule: „Java Developer (ZOB-2962)”. */
const LETTER_CODE = /\b([A-Z]{2,6})-(\d{3,6})\b/g;
/** Numer rekrutacji z Traffita w nawiasie: „Analityk (42700)”. */
const TRAFFIT_NUMBER = /\((\d{4,7})\)/g;
/** Rok w nawiasie („(2026)”) to nie numer rekrutacji — łapałby każde „CV_2026.pdf”. */
const YEAR = /^(19|20)\d{2}$/;

/**
 * Kody rekrutacji osoby wyciągnięte z tytułów (13.10.2026, E5): kody
 * „ZOB-2962” i numery Traffita z nawiasu „(42700)”. Bez powtórzeń,
 * w kolejności rekrutacji.
 */
export function recruitmentCodes(
  jobs: readonly RecruitmentCodeSource[] | null | undefined,
): string[] {
  const codes = new Set<string>();
  for (const job of jobs ?? []) {
    const title = job?.job_title ?? "";
    for (const match of title.matchAll(LETTER_CODE)) codes.add(`${match[1]}-${match[2]}`);
    for (const match of title.matchAll(TRAFFIT_NUMBER)) {
      if (!YEAR.test(match[1])) codes.add(match[1]);
    }
  }
  return [...codes];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Nazwa pliku z kodem rekrutacji: „ZOB-2962” także jako „zob_2962” albo
 * „ZOB2962”; numer Traffita jako osobna liczba („42700_Jan.docx”,
 * „CV (42700).pdf”), nie fragment dłuższej.
 */
function codeMatcher(code: string): RegExp {
  const letter = /^([A-Z]{2,6})-(\d{3,6})$/.exec(code);
  if (letter) {
    return new RegExp(`(^|[^A-Za-z0-9])${letter[1]}[-_ ]?${letter[2]}(?!\\d)`, "i");
  }
  return new RegExp(`(^|\\D)${escapeRegExp(code)}(?!\\d)`);
}

/** Załączniki do ofert i formularze klienta — po nazwie pliku. */
const ATTACHMENT_NAME = /za[łl][aą]cznik|formularz|(^|[^a-z])swz([^a-z]|$)/i;

export interface CandidateFileGroups<T> {
  /** „CV kandydata” — CV od kandydata; główne CV zawsze tutaj. */
  own: T[];
  /** „CV wysłane klientom” — pliki „…B2B…” i pliki z kodem rekrutacji osoby. */
  client: T[];
  /** „Załączniki i formularze” — załączniki, formularze, SWZ i pliki nie-CV. */
  attachments: T[];
}

/**
 * Grupy listy plików w zakładce „Dokumenty” (13.10.2026, E5). Kolejność
 * reguł: główne CV → załącznik/formularz po nazwie → CV dla klienta („B2B”
 * albo kod rekrutacji, bez względu na rodzaj, bo Traffit oznacza takie pliki
 * jako „inny”) → pozostałe pliki nie-CV → CV kandydata. Kolejność w grupie
 * bez zmian (wejście zwykle z `sortCandidateFiles`).
 */
export function groupCandidateFiles<
  T extends CandidateFileListItem & {
    filename?: string | null;
    document_kind?: string | null;
  },
>(docs: readonly T[], codes: readonly string[] = []): CandidateFileGroups<T> {
  const matchers = codes.map(codeMatcher);
  const groups: CandidateFileGroups<T> = { own: [], client: [], attachments: [] };
  for (const doc of docs) {
    const name = doc.filename ?? "";
    if (doc.is_primary) groups.own.push(doc);
    else if (ATTACHMENT_NAME.test(name)) groups.attachments.push(doc);
    else if (isClientCvFilename(name) || matchers.some((m) => m.test(name))) groups.client.push(doc);
    else if (doc.document_kind && doc.document_kind !== "cv") groups.attachments.push(doc);
    else groups.own.push(doc);
  }
  return groups;
}
