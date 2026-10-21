// „Mój czas → Rozliczenie” i kolejka Płac (etap 4): czyste funkcje bez renderu
// (`__tests__/settlement-format.test.ts`). Kwoty z `@/lib/money`, daty
// z `@/lib/date-pl`. NEXUS nie liczy podatków (R4): B2B — netto do faktury,
// zlecenie i UoP — brutto; „na rękę” liczy program płacowy.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type { EmploymentType } from "@/lib/api/hr";
import type {
  MySettlementMonth,
  MySettlements,
  SettlementRow,
  SettlementStatus,
  SettlementStep,
} from "@/lib/api/hr-settlements";
import { formatDayMonthPl } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";

/** Kolor stanu rozliczenia — ten sam w panelu osoby i w kolejce Płac. */
export const SETTLEMENT_TONE: Record<SettlementStatus | "estimate", StatusDotTone> = {
  estimate: "neutral",
  awaiting_document: "info",
  mismatch: "warning",
  ready: "success",
  approved: "info",
  paid: "success",
  cancelled: "neutral",
};

/** „17 160,00 zł netto” / „2 944,00 zł brutto”. */
export function amountWithBasis(
  amount: string | null | undefined,
  currency: string,
  basis: "net" | "gross",
): string {
  return `${formatMoney(amount, currency)} ${basis === "net" ? "netto" : "brutto"}`;
}

/** Tekst do schowka: „pozycja<TAB>kwota” i suma — do przepisania na fakturę (R2). */
export function copyItemsText(month: Pick<MySettlementMonth, "items" | "currency" | "amount" | "amount_basis">): string {
  const lines = month.items.map((item) => `${item.label}\t${formatMoney(item.amount, month.currency)}`);
  lines.push(
    `Razem ${month.amount_basis === "net" ? "netto" : "brutto"}\t${formatMoney(month.amount, month.currency)}`,
  );
  return lines.join("\n");
}

/** Etykieta kroku z datą: „Do zapłaty do 18.11”, „Opłacono 15.10”. */
export function stepLabel(step: SettlementStep): string {
  if (!step.date) return step.label;
  const day = formatDayMonthPl(step.date);
  if (step.key === "due" && step.state !== "done") return `${step.label} do ${day}`;
  if (step.key === "paid" && step.state !== "done") return `${step.label} do ${day}`;
  return step.label;
}

/** Druga linia kroku: data i kto (np. „03.11 · Marta P.”). */
export function stepDetail(step: SettlementStep): string | null {
  const parts: string[] = [];
  if (step.date && !(step.state !== "done" && (step.key === "due" || step.key === "paid"))) {
    parts.push(formatDayMonthPl(step.date));
  }
  if (step.detail) parts.push(step.detail);
  return parts.length ? parts.join(" · ") : null;
}

/** Zdanie pod pozycjami według formy — bez zgadywania podatków (R4). */
export function formNote(form: EmploymentType | null | undefined): string {
  if (form === "b2b") {
    return "VAT dolicza Twój program według Twojego statusu. NEXUS porównuje kwotę netto z fakturą z KSeF.";
  }
  if (form === "zlecenie") {
    return "Zaliczkę na podatek, składki i kwotę do wypłaty policzy program płacowy. Godziny potwierdzasz w raporcie — osobny rachunek nie jest potrzebny.";
  }
  return "Wynagrodzenie zasadnicze, urlop i listę płac liczy program kadrowo-płacowy. Tu są dane miesiąca z NEXUSA.";
}

/** Tytuł karty miesiąca według formy (M1, M2). */
export function documentTitle(month: Pick<MySettlementMonth, "employment_type" | "final">): string {
  if (month.employment_type === "b2b") return month.final ? "do faktury" : "do faktury (szacunek)";
  if (month.employment_type === "zlecenie") return "rozliczenie umowy zlecenia";
  return "dane do listy płac";
}

/** „gdy dojdą premie” (UoP) / „gdy dojdzie wynagrodzenie dodatkowe” (21.10.2026). */
function bonusesArrive(form: EmploymentType | null | undefined): string {
  const words = employmentTerms(form);
  return words.flow === "request" ? `gdy dojdą ${words.bonuses}` : `gdy dojdzie ${words.bonuses}`;
}

/** Co dalej — jedno zdanie dla osoby. */
export function nextStepText(month: MySettlementMonth): string {
  if (month.status === "estimate") {
    return month.hours_confirmed
      ? `Miesiąc liczy się do zamknięcia przez Płace — kwota może się jeszcze zmienić, ${bonusesArrive(month.employment_type)}.`
      : "Pozycje pojawią się po potwierdzeniu raportu godzin.";
  }
  const due = month.due_on ? formatDayMonthPl(month.due_on) : null;
  switch (month.status) {
    case "awaiting_document":
      return "Wystaw fakturę na kwotę netto z pozycji — trafi do NEXUSA z KSeF sama, nic nie wgrywasz.";
    case "mismatch":
      return month.correction_requested_at
        ? `Płace poprosiły o korektę ${formatDayMonthPl(month.correction_requested_at)} — faktura korygująca z KSeF podepnie się sama.`
        : "Faktura nie zgadza się z kwotą z NEXUSA — Płace to sprawdzają.";
    case "ready":
      return month.employment_type === "b2b"
        ? "Faktura zgodna — czeka na zatwierdzenie do zapłaty."
        : "Nic więcej nie musisz robić. Kwota czeka na przekazanie do listy płac.";
    case "approved":
      return due ? `Zapłata do ${due}.` : "Zatwierdzone do zapłaty.";
    case "paid":
      return `${month.employment_type === "b2b" ? "Opłacono" : "Wypłacono"} ${formatDayMonthPl(month.paid_on)}.`;
    default:
      return "";
  }
}

/**
 * Miesiąc, w którym osoba ma coś do zrobienia: B2B wystawia fakturę albo
 * korektę, o którą poprosiły Płace. Taki miesiąc idzie na górę zakładki,
 * z pozycjami do skopiowania (audyt A2, 19.10.2026).
 */
export function needsMyAction(month: Pick<MySettlementMonth, "status" | "correction_requested_at">): boolean {
  return (
    month.status === "awaiting_document" ||
    (month.status === "mismatch" && Boolean(month.correction_requested_at))
  );
}

/**
 * Styczeń: grudzień jeszcze się rozlicza (faktura, przelew), więc zakładki
 * pokazują też poprzedni rok — inaczej 1.01 osoba traci miesiąc do faktury.
 */
export function showsPreviousYear(today: string): boolean {
  return today.slice(5, 7) === "01";
}

/**
 * Bieżący rok + poprzedni: w styczniu cały poprzedni rok, potem tylko jego
 * miesiące, w których osoba ma coś do zrobienia (np. grudzień bez faktury w lutym).
 */
export function mergeSettlementYears(
  current: MySettlements,
  previous: MySettlements | undefined,
  today: string,
): MySettlements {
  if (!previous) return current;
  const all = showsPreviousYear(today);
  const extra = previous.months.filter((month) => all || needsMyAction(month));
  return extra.length ? { ...current, months: [...current.months, ...extra] } : current;
}

export interface SettlementLayout {
  /** Karty z pozycjami: miesiące do działania osoby (od najnowszego), potem najnowszy. */
  featured: MySettlementMonth[][];
  /** Reszta jako „Poprzednie miesiące” — wiersz na walutę. */
  previous: MySettlementMonth[];
}

/**
 * Układ zakładki: serwer zwraca wiersz na miesiąc × walutę (waluty alfabetycznie),
 * więc grupujemy po miesiącu — wszystkie waluty miesiąca są razem. Na górze
 * miesiące, w których osoba ma coś do zrobienia, potem najnowszy (bieżący szacunek).
 */
export function settlementLayout(months: readonly MySettlementMonth[]): SettlementLayout {
  const groups = new Map<number, MySettlementMonth[]>();
  for (const month of months) {
    const key = month.year * 12 + month.month;
    const group = groups.get(key);
    if (group) group.push(month);
    else groups.set(key, [month]);
  }
  const ordered = [...groups.entries()].sort(([a], [b]) => b - a).map(([, group]) => group);
  if (ordered.length === 0) return { featured: [], previous: [] };
  const featured = ordered.filter((group) => group.some(needsMyAction));
  if (!featured.includes(ordered[0])) featured.push(ordered[0]);
  return {
    featured,
    previous: ordered.filter((group) => !featured.includes(group)).flat(),
  };
}

/** Jedna linia poprzedniego miesiąca: „FV 9/2026 · 16 400,00 zł netto · opłacono 15.10”. */
export function previousMonthLine(month: MySettlementMonth): string {
  const parts: string[] = [];
  if (month.invoice) parts.push(month.invoice.invoice_number);
  parts.push(amountWithBasis(month.amount, month.currency, month.amount_basis));
  const bonuses = month.items.filter((item) => item.kind === "bonus");
  if (bonuses.length) {
    const sum = bonuses.reduce((total, item) => total + Number(item.amount), 0);
    parts.push(`w tym ${employmentTerms(month.employment_type).bonuses} ${formatMoney(sum, month.currency)}`);
  }
  return parts.join(" · ");
}

/** „123-456-32-18” — NIP w zapisie z kreskami (tylko wyświetlanie). */
export function formatNip(nip: string | null | undefined): string {
  if (!nip || !/^\d{10}$/.test(nip)) return nip ?? "—";
  return `${nip.slice(0, 3)}-${nip.slice(3, 6)}-${nip.slice(6, 8)}-${nip.slice(8)}`;
}

const NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7];

/** Suma kontrolna NIP-u (podpowiedź w formularzu; decyduje serwer). */
export function nipValid(raw: string): boolean {
  const digits = raw.replace(/[\s-]/g, "").replace(/^PL/i, "");
  if (!/^\d{10}$/.test(digits)) return false;
  const sum = NIP_WEIGHTS.reduce((total, weight, i) => total + weight * Number(digits[i]), 0);
  const check = sum % 11;
  return check !== 10 && check === Number(digits[9]);
}

/** Rachunek do wyświetlenia: „•• 4521 · z białej listy VAT”. */
export function accountLabel(
  last4: string | null | undefined,
  source: "white_list" | "manual" | null | undefined,
): string {
  if (!last4) return "brak rachunku";
  return `•• ${last4} · ${source === "white_list" ? "z białej listy VAT" : "wpisany ręcznie"}`;
}

/** Kolumna „Dokument” kolejki Płac (M3). */
export function documentCell(row: SettlementRow): string {
  if (row.document.kind === "invoice") {
    if (!row.document.label) return "—";
    return row.document.date
      ? `${row.document.label} · ${row.document.source === "manual_pdf" ? "PDF" : "KSeF"} ${formatDayMonthPl(row.document.date)}`
      : row.document.label;
  }
  return row.document.label ?? "—";
}

/** Stan w kolejce — z różnicą przy rozbieżności: „rozbieżność +120,00”. */
export function queueStatus(row: SettlementRow): string {
  // Faktura od innego NIP-u niż w danych do rozliczeń — nie różnica do uznania.
  if (row.status === "mismatch" && row.problems.includes("seller")) {
    return "NIP wystawcy faktury inny niż w danych do rozliczeń";
  }
  if (row.status === "mismatch" && row.discrepancy && Number(row.discrepancy) !== 0) {
    const value = Number(row.discrepancy);
    return `${row.status_label.toLowerCase()} ${value > 0 ? "+" : "−"}${formatMoney(Math.abs(value), row.currency).replace(/\s?zł$/, "")}`;
  }
  if (row.status === "mismatch" && row.problems.includes("gross")) {
    return "brutto albo VAT do sprawdzenia";
  }
  if (row.status === "mismatch" && row.problems.includes("white_list")) {
    return "rachunek spoza białej listy";
  }
  if (row.employment_type === "zlecenie" && row.hours_confirmed === false && row.status === "ready") {
    return "godziny niepotwierdzone";
  }
  if (row.status === "paid" && row.paid_on) {
    return `${row.status_label.toLowerCase()} ${formatDayMonthPl(row.paid_on)}`;
  }
  return row.status_label.toLowerCase();
}
