// „Co dalej” w wierszu listy kontraktów (przebudowa 20.11.2026, wariant A).
//
// Te same progi i zdania co pas „Co się dzieje” na stronie kontraktu
// (`buildContractHappening`: zamówienie w 60 dni, czerwone do 14, decyzja
// o przedłużeniu, nierozwiązana umowa B2B, brak stawki klienta tylko z wglądem
// w kwoty), policzone z danych, które lista już ma — bez zapytania na wiersz.
// Dokłada dwie rzeczy, które mówi lista, a nie pas: start w przyszłości (U5)
// i brak aktywnego zamówienia (ta sama reguła co ostrzeżenie panelu).
// Do tego marża miesięczna wiersza i grupy klientów dla „Grupuj: klient”.
import { CONTRACT_TERMINATION_REASONS } from "@/lib/api";
import {
  buildContractHappening,
  fmtDatePl,
  relativeDays,
  type HappeningTone,
} from "@/lib/contract-happening";
import { lacksActiveOrder, orderEnded } from "@/lib/contract-panel";
import { HOURS_PER_MONTH, MD_PER_MONTH } from "@/lib/work-time";

/** Fakty wiersza listy (`ContractResponse` albo członek zgrupowanego wiersza). */
export interface ListRowFacts {
  status?: string | null;
  contract_type?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  terminated_at?: string | null;
  termination_reason?: string | null;
  termination_lessons?: string | null;
  agreement_termination_mode?: string | null;
  client_order_start_date?: string | null;
  client_order_end_date?: string | null;
  prolongation_status?: string | null;
  rate_client?: number | null;
  margin?: number | null;
  rate_unit?: string | null;
  billing_hours_per_month?: number | null;
  currency?: string | null;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
}

export type NextTone = HappeningTone | "muted";

export interface NextStep {
  id: "end" | "order_end" | "rate" | "no_order" | "start";
  tone: NextTone;
  /** Zdanie w wierszu — to samo co na pasku strony kontraktu. */
  text: string;
  /** Krótki dopisek pod spodem (powód, decyzja o przedłużeniu). */
  detail: string | null;
  /** Pełny opis do podpowiedzi. */
  hint: string | null;
}

const LIVE = new Set(["active", "ending"]);

function dayDiff(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

export function terminationReasonLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return CONTRACT_TERMINATION_REASONS.find((r) => r.value === value)?.label ?? value;
}

/** Umowa B2B bez zapisanego rozwiązania (wypowiedzenia albo porozumienia). */
export function agreementOpen(f: ListRowFacts): boolean {
  return f.contract_type === "b2b" && !f.agreement_termination_mode;
}

/**
 * „Co dalej” dla jednego wiersza: najpilniejsze pierwsze. Pusta lista = nic
 * nie czeka (wiersz pokazuje kreskę).
 */
export function listNextSteps(
  f: ListRowFacts,
  today: string,
  options: { canSeeRates: boolean },
): NextStep[] {
  const status = f.status ?? "";
  const happening = buildContractHappening(
    {
      status,
      contract_type: f.contract_type ?? "",
      end_date: f.end_date ?? null,
      terminated_at: f.terminated_at ?? null,
      termination_reason: f.termination_reason ?? null,
      termination_lessons: f.termination_lessons ?? null,
      agreement_termination_mode: f.agreement_termination_mode ?? null,
      client_order_end_date: f.client_order_end_date ?? null,
      prolongation_status: f.prolongation_status ?? null,
      rate_client: f.rate_client ?? null,
      can_reverse_termination: false,
    },
    null,
    today,
    options,
  );

  const first: NextStep[] = [];
  const rest: NextStep[] = [];
  for (const item of happening) {
    if (item.id === "end") {
      // W wierszu krótko: powód i stan umowy; pełne zdania w podpowiedzi.
      // Zakończona współpraca ma stan umowy już w zdaniu głównym.
      const reason = terminationReasonLabel(f.termination_reason);
      const short = [reason, status !== "ended" && agreementOpen(f) ? "umowa B2B nierozwiązana" : null]
        .filter(Boolean)
        .join(" · ");
      first.push({ id: "end", tone: item.tone, text: item.lead, detail: short || null, hint: item.detail });
    } else if (item.id === "order_end") {
      first.push({ id: "order_end", tone: item.tone, text: item.lead, detail: item.detail, hint: item.detail });
    } else if (item.id === "rate") {
      rest.push({ id: "rate", tone: "muted", text: item.lead, detail: null, hint: item.detail });
    }
  }

  const live = LIVE.has(status);
  if (live && first.length === 0 && lacksActiveOrder(factsForPanel(f), today)) {
    const ended = orderEnded(factsForPanel(f), today);
    first.push({
      id: "no_order",
      tone: "danger",
      text: "Brak aktywnego zamówienia",
      detail: ended && f.client_order_end_date ? `Ostatnie skończyło się ${fmtDatePl(f.client_order_end_date)}.` : null,
      hint: "Dodaj zamówienie u klienta albo zakończ współpracę.",
    });
  }

  const start = f.start_date?.slice(0, 10);
  if (live && start && start > today) {
    rest.unshift({
      id: "start",
      tone: "info",
      text: `Startuje ${fmtDatePl(start)} — ${relativeDays(dayDiff(today, start))}`,
      detail: null,
      hint: null,
    });
  }
  return [...first, ...rest];
}

function factsForPanel(f: ListRowFacts) {
  return {
    status: f.status ?? "",
    client_order_start_date: f.client_order_start_date ?? null,
    client_order_end_date: f.client_order_end_date ?? null,
  };
}

/** Waluta stawki klienta (w niej liczy się marża). */
function clientCurrency(f: ListRowFacts): string {
  return (f.rate_client_currency ?? f.currency ?? "PLN").toUpperCase();
}

/**
 * Marża w miesiącu — lustro `Contract.monthly_margin` (backend): stawka
 * godzinowa × godziny rozliczeniowe (domyślnie 168), dzienna × 21 MD,
 * miesięczna bez zmian. Różne waluty stron = brak (różnica nie jest kwotą).
 */
export function monthlyMargin(f: ListRowFacts): number | null {
  if (f.margin == null) return null;
  const candidateCurrency = (f.rate_candidate_currency ?? f.currency ?? "PLN").toUpperCase();
  if (clientCurrency(f) !== candidateCurrency) return null;
  switch (f.rate_unit) {
    case "monthly":
      return f.margin;
    case "daily":
      return f.margin * MD_PER_MONTH;
    case "hourly":
      return f.margin * (f.billing_hours_per_month || HOURS_PER_MONTH);
    default:
      return f.margin;
  }
}

/** Suma marż w złotych; umowy bez stawki albo w innej walucie liczone osobno. */
export function sumMonthlyMarginPln(rows: readonly ListRowFacts[]): { total: number; unpriced: number } {
  let total = 0;
  let unpriced = 0;
  for (const row of rows) {
    const value = monthlyMargin(row);
    if (value == null || clientCurrency(row) !== "PLN") unpriced += 1;
    else total += value;
  }
  return { total, unpriced };
}

/** Współpraca zakończona z datą w przyszłości albo status „Kończący się”. */
export function isLeaving(f: ListRowFacts, today: string): boolean {
  if (f.status === "ending") return true;
  const end = f.end_date?.slice(0, 10);
  return Boolean(LIVE.has(f.status ?? "") && f.terminated_at && end && end >= today);
}

export function startsLater(f: ListRowFacts, today: string): boolean {
  const start = f.start_date?.slice(0, 10);
  return Boolean(LIVE.has(f.status ?? "") && start && start > today);
}

export interface ClientGroupRow extends ListRowFacts {
  id: number;
  client_id?: number | null;
  client_name?: string | null;
  candidate_id?: number | null;
}

export interface ClientGroup<T extends ClientGroupRow> {
  /** Klucz grupy: id klienta (wiersz bez klienta — `null`). */
  clientId: number | null;
  name: string;
  rows: T[];
  people: number;
  margin: { total: number; unpriced: number };
  leaving: number;
  starting: number;
}

/**
 * „Grupuj: klient”: wiersze pod klientem, grupy od największej (tak jak
 * czyta się portfel), w grupie kolejność wierszy z listy (sortowanie serwera).
 */
export function groupRowsByClient<T extends ClientGroupRow>(rows: readonly T[], today: string): ClientGroup<T>[] {
  const map = new Map<string, T[]>();
  for (const row of rows) {
    const key = row.client_id == null ? "none" : String(row.client_id);
    const list = map.get(key);
    if (list) list.push(row);
    else map.set(key, [row]);
  }
  const groups: ClientGroup<T>[] = [];
  for (const groupRows of map.values()) {
    const head = groupRows[0];
    const people = new Set(groupRows.map((row) => (row.candidate_id != null ? `c${row.candidate_id}` : `k${row.id}`)));
    groups.push({
      clientId: head.client_id ?? null,
      name: head.client_name || (head.client_id != null ? `Klient #${head.client_id}` : "Bez klienta"),
      rows: groupRows,
      people: people.size,
      margin: sumMonthlyMarginPln(groupRows),
      leaving: groupRows.filter((row) => isLeaving(row, today)).length,
      starting: groupRows.filter((row) => startsLater(row, today)).length,
    });
  }
  return groups.sort((a, b) => b.rows.length - a.rows.length || a.name.localeCompare(b.name, "pl"));
}

/** Polska liczba mnoga: 1 / 2–4 (bez 12–14) / reszta. */
export function pluralPl(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (n === 1) return one;
  return m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14) ? few : many;
}

export function peopleLabel(n: number): string {
  return `${n} ${pluralPl(n, "osoba", "osoby", "osób")}`;
}

const PLN_WHOLE = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 });

/** „12 345 zł” — kwoty miesięczne bez groszy. */
export function formatPlnWhole(value: number): string {
  return `${PLN_WHOLE.format(Math.round(value))} zł`;
}
