/**
 * Lista plików kandydata (zakładka „Pliki i umowy”): kolejność i podpis
 * „dodano DD.MM.RRRR · kto”. Czyste funkcje — komponent tylko renderuje.
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
