// Oś zmian zakładki „Aneksy” kontraktu (wariant A, decyzja Artura 19.11.2026).
// Dawna tabela łamała etykiety w trzy linie, w każdym wierszu powtarzała
// „Źródło: Ręcznie” i „Dokument: brak”, a trzy identyczne wpisy stały pod sobą
// bez słowa komentarza. Tu: wpisy po dniu wejścia w życie, zmiana w jednej
// linii, identyczne zapisy zwinięte. Czyste funkcje — widok w
// `ContractAmendmentsTab`.
import type { AnnexChange, AnnexState } from "@/lib/api/b2bDocuments";
import { annexChangeText } from "@/lib/b2b-documents";
import { relativeDays } from "@/lib/contract-happening";
import { personFromEmail } from "@/lib/contract-history";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { currencySymbol, rateUnitSuffix } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { warsawDateOf } from "@/lib/warsaw-date";
import {
  contractDetailLabel,
  contractDetailValue,
} from "@/components/contracts/contract-timeline-labels";

/** Nazwy typów wpisu `contract_amendments.amendment_type`. */
export const AMENDMENT_TYPE_LABELS: Readonly<Record<string, string>> = {
  extension: "Przedłużenie",
  rate_change: "Zmiana stawki",
  scope_change: "Zmiana zakresu",
  early_termination: "Wcześniejsze zakończenie",
  // Typy zapisywane po podpisie aneksu z Generatora aneksów (0362).
  start_date_change: "Zmiana daty startu",
  party_data_change: "Uzupełnienie danych firmy",
  subcontractor_consent: "Osoba skierowana",
  mandate_change: "Aneks do umowy zlecenie",
  // Aneks z własną nazwą (0723) — nazwę niesie `new_values.annex_title`.
  custom_change: "Inna zmiana",
};

/** Nazwa typu aneksu; typ, którego front jeszcze nie zna, nie zostaje pusty.
 *  Wpis z własną nazwą (`custom_change`, np. „Wycofanie wypowiedzenia”)
 *  pokazuje tę nazwę zamiast „Inna zmiana”. */
export function amendmentTypeLabel(
  type: string,
  newValues?: Record<string, unknown> | null,
): string {
  const title = newValues?.annex_title;
  if (type === "custom_change" && typeof title === "string" && title.trim()) {
    return title.trim();
  }
  return AMENDMENT_TYPE_LABELS[type] ?? "Aneks";
}

/** Wpis z historii kontraktu w kształcie, którego potrzebuje oś. */
export interface TimelineAmendment {
  id: number;
  amendment_type: string;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  effective_date: string;
  reason: string | null;
  created_at: string;
  created_by_name?: string | null;
  created_by_email?: string | null;
  /** `generator` = podpisany w Generatorze aneksów, `manual` = dodany w zakładce. */
  source?: "generator" | "manual";
  state?: AnnexState;
  withdrawn?: boolean;
  withdrawable?: boolean;
}

/** Tytuł wpisu na osi — przy stawkach mówi, czyja stawka się zmieniła. */
export function amendmentTitle(
  a: Pick<TimelineAmendment, "amendment_type" | "new_values">,
): string {
  if (a.amendment_type === "rate_change") {
    const keys = Object.keys(a.new_values ?? {});
    const client = keys.includes("rate_client");
    const candidate = keys.includes("rate_candidate");
    if (client && candidate) return "Zmiana stawek";
    if (client) return "Zmiana stawki klienta";
    if (candidate) return "Zmiana stawki kandydata";
  }
  return amendmentTypeLabel(a.amendment_type, a.new_values);
}

/** Pola techniczne wpisu, których oś nie pokazuje jako zmiany. */
const HIDDEN_CHANGE_KEYS = new Set(["annex_title", "withdrawn_amendment_id"]);

/** Waluty i jednostka kontraktu — wpis aneksu niesie same liczby. */
export interface ChangeLineMoney {
  clientCurrency?: string | null;
  candidateCurrency?: string | null;
  /** Jednostka stawki kontraktu, gdy wpis jej nie niesie. */
  rateUnit?: string | null;
}

const RATE_KEYS: Record<string, { who: string; currency: "clientCurrency" | "candidateCurrency" }> = {
  rate_client: { who: "klient", currency: "clientCurrency" },
  rate_candidate: { who: "kandydat", currency: "candidateCurrency" },
  framework_rate: { who: "stawka ramowa", currency: "clientCurrency" },
};

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** „175,00”, stawka z ułamkiem grosza „34,625” — te same miejsca co `formatMoney`. */
export function rateAmount(value: number): string {
  const digits = Math.round(Math.abs(value) * 1000) % 10 === 0 ? 2 : 3;
  return new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** „Data rozpoczęcia” → „data rozpoczęcia”; skrót („NIP”) zostaje. */
function lowerFirst(label: string): string {
  const second = label.charAt(1);
  const isLower = second !== "" && second === second.toLocaleLowerCase("pl") && second !== second.toLocaleUpperCase("pl");
  return isLower ? label.charAt(0).toLocaleLowerCase("pl") + label.slice(1) : label;
}

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/**
 * Zmiana w jednej linii: „klient 175,00 → 163,00 zł/h · kandydat 135,00 →
 * 125,00 zł/h”, „koniec projektu 30.06.2026 → 31.12.2026”. Pola bez zmiany
 * (status, który został ten sam) i pola techniczne nie wchodzą.
 */
export function amendmentChangeLine(
  a: Pick<TimelineAmendment, "old_values" | "new_values">,
  money: ChangeLineMoney = {},
): string {
  const before = a.old_values ?? {};
  const after = a.new_values ?? {};
  const unitKey =
    (typeof after.rate_unit === "string" && after.rate_unit) ||
    (typeof before.rate_unit === "string" && before.rate_unit) ||
    money.rateUnit ||
    "hourly";
  const parts: string[] = [];
  for (const [key, next] of Object.entries(after)) {
    if (HIDDEN_CHANGE_KEYS.has(key)) continue;
    const prev = before[key];
    const rate = RATE_KEYS[key];
    if (rate) {
      const n = toNumber(next);
      if (n == null) continue;
      const p = toNumber(prev);
      // Twarda spacja jak w `formatMoney`: kwota nie rozstaje się z jednostką.
      const unit = `\u00a0${currencySymbol(money[rate.currency])}${rateUnitSuffix(unitKey)}`;
      if (p == null) parts.push(`${rate.who} ${rateAmount(n)}${unit}`);
      else if (Math.abs(p - n) < 0.0005) parts.push(`${rate.who} ${rateAmount(n)}${unit} (bez zmiany)`);
      else parts.push(`${rate.who} ${rateAmount(p)} → ${rateAmount(n)}${unit}`);
      continue;
    }
    if (key === "status") {
      if (prev === next) continue;
      const status = (v: unknown) => contractDetailValue("status", v).toLocaleLowerCase("pl");
      parts.push(isBlank(prev) ? `status ${status(next)}` : `status ${status(prev)} → ${status(next)}`);
      continue;
    }
    if (key === "end_date") {
      // Zdjęta data końca = umowa bezterminowa (wycofane wypowiedzenie).
      const nextText = next == null ? "bezterminowo" : contractDetailValue(key, next);
      if (isBlank(prev) || prev === next) {
        parts.push(`koniec projektu ${nextText}`);
        continue;
      }
      const earlier = typeof prev === "string" && typeof next === "string" && next < prev;
      parts.push(
        `koniec projektu ${contractDetailValue(key, prev)} → ${nextText}${earlier ? " (wcześniej niż było)" : ""}`,
      );
      continue;
    }
    const label = lowerFirst(contractDetailLabel(key));
    if (typeof next === "boolean") {
      parts.push(next ? label : `${label}: nie`);
      continue;
    }
    const nextText = contractDetailValue(key, next);
    const prevText = contractDetailValue(key, prev);
    if (!isBlank(prev) && prevText === nextText) continue;
    parts.push(prevText !== "—" ? `${label} ${prevText} → ${nextText}` : `${label} ${nextText}`);
  }
  return parts.join(" · ");
}

/** Kto zapisał: imię i nazwisko, a gdy go nie ma — nazwa z adresu, nie adres. */
export function amendmentAuthor(
  a: Pick<TimelineAmendment, "created_by_name" | "created_by_email">,
): string | null {
  return a.created_by_name?.trim() || personFromEmail(a.created_by_email);
}

/** Dzień zapisu w kalendarzu firmy: „29.06.2026”. */
export function savedDay(createdAt: string | null | undefined): string {
  return formatIsoDatePl(warsawDateOf(createdAt));
}

const stable = (value: unknown): string =>
  value && typeof value === "object" && !Array.isArray(value)
    ? `{${Object.keys(value as Record<string, unknown>)
        .sort()
        .map((k) => `${JSON.stringify(k)}:${stable((value as Record<string, unknown>)[k])}`)
        .join(",")}}`
    : JSON.stringify(value ?? null);

/**
 * Ten sam rodzaj + dzień wejścia w życie + nowe wartości = ta sama zmiana
 * zapisana drugi raz. Wycofany wpis nie jest już „taki sam” — zostaje osobno,
 * ze swoim stanem.
 */
export function amendmentDuplicateKey(
  a: Pick<TimelineAmendment, "amendment_type" | "effective_date" | "new_values" | "withdrawn">,
): string {
  return [a.amendment_type, a.effective_date ?? "", stable(a.new_values ?? {}), a.withdrawn ? "wycofany" : ""].join("|");
}

export interface AmendmentGroup<T extends TimelineAmendment = TimelineAmendment> {
  key: string;
  /** Pierwszy zapis — pozostałe to powtórzenia. */
  main: T;
  /** Wszystkie zapisy, od najnowszego. */
  entries: T[];
  /** Uzasadnienie wpisane ręcznie przy którymkolwiek zapisie (najnowsze). */
  reason: string | null;
}

const createdAt = (a: TimelineAmendment): number => Date.parse(a.created_at) || 0;

/** Zapisy zgrupowane po `amendmentDuplicateKey`, od najnowszego dnia wejścia w życie. */
export function groupAmendments<T extends TimelineAmendment>(list: readonly T[]): AmendmentGroup<T>[] {
  const byKey = new Map<string, T[]>();
  for (const a of list) {
    const key = amendmentDuplicateKey(a);
    byKey.set(key, [...(byKey.get(key) ?? []), a]);
  }
  return [...byKey.entries()]
    .map(([key, items]) => {
      const entries = [...items].sort((x, y) => createdAt(y) - createdAt(x) || y.id - x.id);
      // Powód przy aneksie z generatora składa serwer („Aneks — … (dokument #3)”).
      const reason =
        entries
          .filter((e) => e.source !== "generator")
          .map((e) => e.reason?.trim() ?? "")
          .find(Boolean) ?? null;
      return { key, main: entries[entries.length - 1], entries, reason };
    })
    .sort(
      (x, y) =>
        y.main.effective_date.localeCompare(x.main.effective_date) ||
        createdAt(y.main) - createdAt(x.main) ||
        y.main.id - x.main.id,
    );
}

/** „zapisano 3 razy (05.07, 29.06, 29.06) — możliwy duplikat”. */
export function duplicateNote(entries: readonly Pick<TimelineAmendment, "created_at">[]): string {
  const days = entries.map((e) => formatDayMonthPl(warsawDateOf(e.created_at)));
  return `zapisano ${entries.length} razy (${days.join(", ")}) — możliwy duplikat`;
}

/** Aneks z Generatora aneksów bez wpisu w historii kontraktu. */
export interface TimelineDocument {
  effective_date: string | null;
  state: AnnexState;
  change?: AnnexChange | null;
}

export interface TimelineNode<
  A extends TimelineAmendment = TimelineAmendment,
  D extends TimelineDocument = TimelineDocument,
> {
  /** Dzień wejścia w życie; `null` — aneks z generatora jeszcze bez daty. */
  date: string | null;
  future: boolean;
  /** Ostatni dzień (≤ dziś) ze zmianą, która nie została wycofana. */
  current: boolean;
  /** Aneksy z generatora czekające na podpis — na górze węzła. */
  waiting: D[];
  groups: AmendmentGroup<A>[];
  /** Pozostałe aneksy z generatora (anulowane, podpisane bez zmiany w kontrakcie). */
  documents: D[];
}

/** Węzły osi od najnowszego dnia; aneks bez daty na samej górze. */
export function buildTimeline<A extends TimelineAmendment, D extends TimelineDocument>(
  groups: readonly AmendmentGroup<A>[],
  documents: readonly D[],
  today: string,
): TimelineNode<A, D>[] {
  const nodes = new Map<string, TimelineNode<A, D>>();
  const node = (date: string | null): TimelineNode<A, D> => {
    const existing = nodes.get(date ?? "");
    if (existing) return existing;
    const created: TimelineNode<A, D> = {
      date,
      future: date != null && date > today,
      current: false,
      waiting: [],
      groups: [],
      documents: [],
    };
    nodes.set(date ?? "", created);
    return created;
  };
  for (const g of groups) node(g.main.effective_date).groups.push(g);
  for (const d of documents) {
    const target = node(d.effective_date);
    (d.state === "waiting" ? target.waiting : target.documents).push(d);
  }
  const sorted = [...nodes.values()].sort((x, y) =>
    (y.date ?? "9999-12-31").localeCompare(x.date ?? "9999-12-31"),
  );
  const current = sorted.find(
    (n) => n.date != null && n.date <= today && n.groups.some((g) => !g.main.withdrawn),
  );
  return sorted.map((n) => (n === current ? { ...n, current: true } : n));
}

/** „2 zmiany · 1 aneks czeka na podpis · 2 powtórzone wpisy”. */
export function timelineSummary(groupCount: number, waitingCount: number, repeatCount: number): string {
  return [
    groupCount > 0 ? countPl(groupCount, "zmiana", "zmiany", "zmian") : "",
    waitingCount > 0 ? `${countPl(waitingCount, "aneks czeka", "aneksy czekają", "aneksów czeka")} na podpis` : "",
    repeatCount > 0 ? countPl(repeatCount, "powtórzony wpis", "powtórzone wpisy", "powtórzonych wpisów") : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function dayDiff(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

/** „za 11 dni”, „jutro”, „dziś” — dzień wejścia w życie względem dziś. */
export function untilDay(date: string, today: string): string {
  return relativeDays(dayDiff(today, date));
}

const DOCUMENT_CHANGE_WHO: Partial<Record<AnnexChange["kind"], string>> = {
  // Aneks stawki z generatora zmienia stawkę Partnera, czyli kosztową.
  rate: "kandydat",
  start_date: "data startu",
  party: "Partner",
  delegate: "osoba skierowana",
};

/** Zmiana aneksu z generatora w jednej linii: „kandydat 140,00 → 150,00 zł/h”. */
export function annexDocumentChangeLine(change: AnnexChange | null | undefined): string | null {
  const text = annexChangeText(change);
  if (!text || !change) return null;
  const who = DOCUMENT_CHANGE_WHO[change.kind];
  const value = text.before ? `${text.before} → ${text.after}` : text.after;
  return who ? `${who} ${value}` : value;
}
