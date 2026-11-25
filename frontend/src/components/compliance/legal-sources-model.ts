// Karta „Źródła asystenta prawnego” (Przepisy → „Źródła i boty”, część H):
// czyste funkcje z odpowiedzi `GET /api/legal/sources` → wiersze karty.
// Reguły: docs/claude/asystent-prawny/przejrzyj-wzor-po-zmianie-przepisu.md.

import type { LegalActStatus, LegalDocumentsStatus, LegalSources, LegalTemplateReviewStatus } from "@/lib/api/legalSources";

import { formatDay, type Tone } from "./compliance-model";

export interface LegalSourceRow {
  name: string;
  from: string;
  state: string;
  tone: Tone;
}

export interface LegalSourceGroup {
  title: string;
  rows: LegalSourceRow[];
  /** Zamiast wierszy, gdy grupa nie ma jeszcze danych (pusty korpus). */
  empty?: string;
}

export const EMPTY_CORPUS =
  "Korpus prawa jest jeszcze pusty — pierwsze odświeżenie pobiera teksty ustaw. Do tego czasu asystent nie porówna cytatu z przepisem.";

/** Licencje: LEX i Gofin nigdy nie idą do modelu (decyzja Artura 25.11.2026). */
export const LINK_ONLY_ROWS: readonly LegalSourceRow[] = [
  { name: "LEX, Gofin", from: "komentarze chronione licencją i regulaminem", state: "tylko link — nie do modelu", tone: "danger" },
  {
    name: "NSA i WSA, interpretacje KIS, SN po 2016 r.",
    from: "CBOSA, EUREKA, sn.pl — bez API albo z bramką",
    state: "tylko link, z sygnaturą",
    tone: "neutral",
  },
];

/** Polska odmiana liczebnika: 1 umowa, 2 umowy, 5 umów, 22 umowy, 12 umów. */
export function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const tens = n % 100;
  const units = n % 10;
  if (units >= 2 && units <= 4 && (tens < 12 || tens > 14)) return few;
  return many;
}

function count(n: number, one: string, few: string, many: string): string {
  return `${n} ${plural(n, one, few, many)}`;
}

/** „25.11.2026” ze znacznika czasu w kalendarzu firmy. */
export function localDay(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "numeric",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function latest(values: (string | null | undefined)[]): string | null {
  const present = values.filter((v): v is string => Boolean(v)).sort();
  return present.length ? present[present.length - 1] : null;
}

function names(acts: LegalActStatus[], limit = 4): string {
  const shown = acts.slice(0, limit).map((a) => a.short_name);
  const rest = acts.length - shown.length;
  return rest > 0 ? `${shown.join(", ")} i ${rest} ${plural(rest, "inny", "inne", "innych")}` : shown.join(", ");
}

const SOURCE_ROW: Record<LegalActStatus["source"], { from: string }> = {
  eli: { from: "ELI Sejmu · tekst jednolity z wersjami" },
  eurlex: { from: "EUR-Lex · wersja skonsolidowana" },
};

function actGroupRow(acts: LegalActStatus[], source: LegalActStatus["source"]): LegalSourceRow | null {
  const list = acts.filter((a) => a.source === source && a.in_registry);
  if (!list.length) return null;
  const ready = list.filter((a) => a.current).length;
  const failed = list.filter((a) => a.fetch_status === "failed").length;
  const checked = latest(list.map((a) => a.checked_at));
  let state: string;
  let tone: Tone;
  if (failed) {
    state = `${failed} z ${list.length} do ponowienia`;
    tone = "warning";
  } else if (ready < list.length) {
    state = `${ready} z ${list.length} pobranych`;
    tone = "warning";
  } else {
    state = checked ? `sprawdzone ${localDay(checked)}` : "pobrane";
    tone = "success";
  }
  return { name: names(list), from: SOURCE_ROW[source].from, state, tone };
}

export function corpusRows(data: Pick<LegalSources, "acts">, documents: LegalDocumentsStatus): LegalSourceRow[] {
  const rows: LegalSourceRow[] = [];
  for (const source of ["eli", "eurlex"] as const) {
    const row = actGroupRow(data.acts, source);
    if (row) rows.push(row);
  }
  const amended = data.acts.filter((a) => (a.current?.amendments_after.length ?? 0) > 0);
  if (amended.length) {
    rows.push({
      name: "Zmiany po tekście jednolitym",
      from: names(amended),
      state: "tekst jednolity ich nie obejmuje",
      tone: "warning",
    });
  }
  const cases = documents.case_law.count;
  rows.push({
    name: "Orzeczenia SN i sądów powszechnych",
    from: "SAOS · SN do 2016 r., sądy powszechne na bieżąco",
    state: cases ? count(cases, "orzeczenie", "orzeczenia", "orzeczeń") : "jeszcze nie zasilone",
    tone: cases ? "success" : "neutral",
  });
  return rows;
}

export function documentRows(documents: LegalDocumentsStatus): LegalSourceRow[] {
  const { contracts, amendments } = documents.framework_contracts;
  const { repo, client_clauses: clauses, custom_approved: custom } = documents.templates;
  return [
    {
      name: "Umowy ramowe klientów",
      from: "indeks Jarvisa · odczytany tekst umów i aneksów",
      state:
        contracts || amendments
          ? `${count(contracts, "umowa", "umowy", "umów")}, ${count(amendments, "aneks", "aneksy", "aneksów")}`
          : "brak odczytanych",
      tone: contracts || amendments ? "success" : "neutral",
    },
    {
      name: "Wzory i klauzule klientów",
      from: "Generator umów · szablony umów, aneksów i pism",
      state: `${count(repo, "wzór", "wzory", "wzorów")}, ${count(clauses, "klient", "klientów", "klientów")}`,
      tone: repo ? "success" : "neutral",
    },
    {
      name: "Wzory własne",
      from: "Generator → Dokumenty · zatwierdza administrator",
      state: custom ? count(custom, "zatwierdzony", "zatwierdzone", "zatwierdzonych") : "brak zatwierdzonych",
      tone: custom ? "success" : "neutral",
    },
  ];
}

export function legalSourceGroups(data: LegalSources): LegalSourceGroup[] {
  const corpusEmpty = data.acts_ready === 0;
  const rows = corpusRows(data, data.documents);
  return [
    {
      title: "Przepisy i orzeczenia (bez praw autorskich, art. 4 pr. aut.)",
      // Pusty korpus: zostaje tylko wiersz orzeczeń, bo ma osobne zasilenie.
      rows: corpusEmpty ? rows.filter((r) => r.name.startsWith("Orzeczenia")) : rows,
      empty: corpusEmpty ? EMPTY_CORPUS : undefined,
    },
    { title: "Nasze dokumenty", rows: documentRows(data.documents) },
    { title: "Tylko jako link", rows: [...LINK_ONLY_ROWS] },
  ];
}

export function reviewLine(review: LegalTemplateReviewStatus): string {
  const last = review.last_created_at ? localDay(review.last_created_at) : "brak";
  const open = review.open ? ` · otwarte: ${review.open}` : "";
  return `Zmiana artykułu cytowanego we wzorze zakłada w Przepisach zadanie „Przejrzyj wzór” · ostatnio: ${last}${open}`;
}

/** Wiersz aktu w rozwinięciu: „KC — stan na 1.01.2026 · 3 wersje”. */
export function actLine(act: LegalActStatus): { name: string; detail: string; tone: Tone } {
  if (act.current) {
    const versions = count(act.versions, "wersja", "wersje", "wersji");
    const failed = act.fetch_status === "failed" ? " · ostatnie sprawdzenie nieudane" : "";
    return {
      name: act.short_name,
      detail: `stan na ${formatDay(act.current.valid_from)} · ${versions}${failed}`,
      tone: act.fetch_status === "failed" ? "warning" : "success",
    };
  }
  return {
    name: act.short_name,
    detail: act.fetch_status === "failed" ? "nie udało się pobrać" : "czeka na pierwsze pobranie",
    tone: act.fetch_status === "failed" ? "warning" : "neutral",
  };
}
