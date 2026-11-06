/**
 * „Ostatnie odrzucenie” na liście kandydatów (06.11.2026, makiety:
 * https://claude.ai/artifact/HfjaZy1PzPFEaLNMayNNfx, wariant C).
 *
 * Kolumna, pigułka „Powód odrzucenia” i pasek „Ostatnie odrzucenie w tym
 * wyniku” czytają jedną definicję z backendu
 * (`app/services/candidate_last_rejection.py`): najnowsze odrzucenie albo
 * rezygnacja, które jest nadal stanem swojej pary. Osoba może mieć po nim nowszy
 * proces — wtedy kolumna dopisuje „potem: w toku” (decyzja Artura).
 *
 * Klucze filtra przychodzą z API: `r:<etykieta>` (powód ze słownika),
 * `t:<kategoria Traffita>` (import bez powodu), `none` (nic).
 */

import type { CandidateFilters, RejectionWho, RejectionWithinMonths } from "@/lib/url-filters";

export interface LastRejection {
  key: string;
  label: string;
  who: RejectionWho;
  ended_by?: string | null;
  note?: string | null;
  at?: string | null;
  job_id: number;
  job_title?: string | null;
  client_name?: string | null;
  moved_by_name?: string | null;
}

export interface RejectionFacetItem {
  key: string;
  label: string;
  count: number;
}

export interface RejectionFacets {
  total: number;
  without_rejection: number;
  items: RejectionFacetItem[];
  who: Array<{ key: RejectionWho; count: number }>;
}

export const REJECTION_WHO_LABELS: Record<RejectionWho, string> = {
  client: "Klient",
  us: "My",
  candidate: "Kandydat",
};

export const REJECTION_MONTHS_OPTIONS: ReadonlyArray<{
  value: RejectionWithinMonths;
  label: string;
}> = [
  { value: 0, label: "Kiedykolwiek" },
  { value: 3, label: "3 mies." },
  { value: 12, label: "12 mies." },
];

export const TRAFFIT_KEY_PREFIX = "t:";

/** Etykieta klucza bez odpowiedzi API (np. z adresu, zanim przyjdzie pasek). */
export function rejectionKeyLabel(key: string): string {
  if (key.startsWith("r:")) return key.slice(2);
  if (key.startsWith(TRAFFIT_KEY_PREFIX)) return `Traffit · ${key.slice(2)}`;
  if (key === "none") return "Bez powodu";
  return key;
}

type RejectionFilterFields = Pick<
  CandidateFilters,
  "rejectionKeys" | "rejectionBy" | "rejectionWithinMonths" | "rejectionExclude"
>;

export const NO_REJECTION_FILTER: RejectionFilterFields = {
  rejectionKeys: [],
  rejectionBy: [],
  rejectionWithinMonths: 0,
  rejectionExclude: false,
};

/** Ile ustawień siedzi w pigułce (licznik przycisku). */
export function rejectionFilterCount(f: RejectionFilterFields): number {
  return f.rejectionKeys.length + f.rejectionBy.length + (f.rejectionWithinMonths ? 1 : 0);
}

function rejectionWhat(f: RejectionFilterFields): string {
  const parts = [
    ...f.rejectionKeys.map(rejectionKeyLabel),
    ...f.rejectionBy.map((w) => REJECTION_WHO_LABELS[w]),
  ];
  const what = parts.length ? parts.join(", ") : "dowolne";
  const when = f.rejectionWithinMonths ? ` · ${f.rejectionWithinMonths} mies.` : "";
  return `${what}${when}`;
}

/** Podsumowanie na pigułce („Brak doświadczenia · 3 mies.”, „ukryj: …”). */
export function rejectionPillSummary(f: RejectionFilterFields): string | null {
  if (rejectionFilterCount(f) === 0) return null;
  return `${f.rejectionExclude ? "ukryj: " : ""}${rejectionWhat(f)}`;
}

/**
 * Tekst chipa nad listą: „Odrzucenie: Brak doświadczenia, Klient · 3 mies.”
 * albo „bez: …” przy „Ukryj”. `null` = filtr nieustawiony.
 */
export function rejectionFilterSummary(f: RejectionFilterFields): string | null {
  if (rejectionFilterCount(f) === 0) return null;
  return `${f.rejectionExclude ? "Ukryte odrzucenie" : "Odrzucenie"}: ${rejectionWhat(f)}`;
}

/**
 * Klik w chip paska: pierwszy „pokaż tylko”, drugi „ukryj”, trzeci zdejmuje.
 * Pasek działa na jednym kluczu naraz w trybie, który już jest ustawiony —
 * wybór kilku powodów i „kto zakończył” zostaje w pigułce.
 */
export function cycleFacetKey(
  f: RejectionFilterFields,
  key: string,
): Partial<CandidateFilters> {
  const has = f.rejectionKeys.includes(key);
  if (!has) {
    return { rejectionKeys: [...f.rejectionKeys, key], rejectionExclude: f.rejectionExclude };
  }
  if (!f.rejectionExclude && f.rejectionKeys.length === 1) {
    return { rejectionExclude: true };
  }
  const rest = f.rejectionKeys.filter((k) => k !== key);
  return {
    rejectionKeys: rest,
    rejectionExclude: rest.length || f.rejectionBy.length ? f.rejectionExclude : false,
  };
}

export function formatRejectionDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return null;
  return new Date(ts).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Warsaw",
  });
}

interface LiveRecruitment {
  stage: string;
  moved_at?: string | null;
}

const ENDED_STAGES = new Set(["rejected", "withdrawn", "hired"]);

/** Czy po odrzuceniu osoba weszła w proces, który dziś trwa. */
export function hasLaterLiveProcess(
  rejection: Pick<LastRejection, "at" | "job_id">,
  recruitments: ReadonlyArray<LiveRecruitment & { job_id: number }> | null | undefined,
): boolean {
  const at = rejection.at ? Date.parse(rejection.at) : NaN;
  return (recruitments ?? []).some((r) => {
    if (r.job_id === rejection.job_id || ENDED_STAGES.has(r.stage)) return false;
    const moved = r.moved_at ? Date.parse(r.moved_at) : NaN;
    return !Number.isFinite(at) || !Number.isFinite(moved) || moved > at;
  });
}

export interface LastRejectionCellView {
  primary: string;
  /** Powód to wolny opis (Traffit), nie pozycja słownika — kursywa. */
  primaryIsNote: boolean;
  who: RejectionWho | "traffit";
  whoLabel: string;
  secondary: string;
  title: string;
}

/**
 * Dwie linie komórki. „Inne” bez opisu nic nie mówi, więc pokazuje opis;
 * import Traffita bez powodu pokazuje opis w cudzysłowie, a kategorię
 * („Traffit · Po CV”) w drugiej linii.
 */
export function lastRejectionCell(row: LastRejection): LastRejectionCellView {
  const traffit = row.key.startsWith(TRAFFIT_KEY_PREFIX);
  const note = row.note?.trim() || "";
  let primary = row.label;
  let primaryIsNote = false;
  if (traffit || row.key === "none") {
    if (note) {
      primary = `„${note}”`;
      primaryIsNote = true;
    } else if (row.key === "none") {
      primary = "bez powodu";
    }
  } else if (row.label === "Inne" && note) {
    primary = `Inne · „${note}”`;
  }
  const whoLabel = traffit
    ? `Traffit · ${row.key.slice(TRAFFIT_KEY_PREFIX.length)}`
    : row.ended_by === "delivery_lead"
      ? "DL"
      : REJECTION_WHO_LABELS[row.who];
  const date = formatRejectionDate(row.at);
  const secondary = [row.client_name, date].filter(Boolean).join(" · ");
  const title = [
    `${row.label} — ${REJECTION_WHO_LABELS[row.who].toLowerCase()} zakończył`,
    row.job_title ? `Rekrutacja: ${row.job_title}` : null,
    row.client_name ? `Klient: ${row.client_name}` : null,
    row.moved_by_name ? `Przesunął: ${row.moved_by_name}` : null,
    date ? `Data: ${date}` : null,
    note ? `Opis: ${note}` : null,
  ]
    .filter(Boolean)
    .join("\n");
  return {
    primary,
    primaryIsNote,
    who: traffit ? "traffit" : row.who,
    whoLabel,
    secondary,
    title,
  };
}
