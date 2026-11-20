// Rozliczenie miesiąca klienta jako cztery kroki: RCP → do faktury → KSeF →
// zapłata (makieta „Klienci: nowe ekrany” 19.11.2026, ekran 6, wariant A).
// Czyste funkcje — karta w Przeglądzie i pasek w „Fakturach i rozliczeniu”
// liczą kroki tak samo (`__tests__/month-steps.test.ts`).
//
// Zasada: krok mówi tylko to, co potwierdzają dane NEXUSA. Brak RCP w NEXUSIE
// to „brak w NEXUSIE”, nie „czeka”; faktura z terminem za sobą bez dowodu
// z wyciągów to „brak danych o zapłacie”, nigdy „niezapłacona” (19.11.2026:
// 2 741 faktur „po terminie”, żadna z zapisaną zapłatą — PR #3620, #3623).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type { ClientInvoicing, SalesInvoice } from "@/lib/api/client-invoicing";
import type { ClientInvoiceRow } from "@/lib/api/client-settlements";
import { formatDayMonthPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { totalsText, unknownReasonNote } from "./invoicing-format";

export type MonthStepKey = "rcp" | "invoice" | "ksef" | "payment";

export interface MonthStep {
  key: MonthStepKey;
  label: string;
  /** Krótki stan kroku: „12 z 29 przyjętych”, „brak danych o zapłacie”. */
  value: string;
  /** Jeszcze krótszy stan do karty w Przeglądzie (ok. 120 px): „46 z 48”. */
  short?: string;
  /** Drobny druk: co liczy krok albo czego brakuje. */
  note: string | null;
  tone: StatusDotTone;
  /** Krok ma jakiekolwiek dane (przyjęte RCP, faktura w KSeF, faktura do zapłaty). */
  started: boolean;
  /** Wszystko w kroku zrobione i potwierdzone danymi. */
  done: boolean;
}

/**
 * RCP z modułu rozliczeń (`/api/my-clients/{id}/settlements`): wiersze miesiąca
 * albo powód, dla którego ich nie ma. `unavailable` — moduł zamknięty dla konta
 * (404) albo brak dostępu (403); `error` — awaria.
 */
export type RcpInput =
  | { state: "loading" }
  | { state: "unavailable" }
  | { state: "error" }
  | { state: "ready"; rows: readonly Pick<ClientInvoiceRow, "kind">[] };

export const STEP_LABELS: Record<MonthStepKey, string> = {
  rcp: "RCP",
  invoice: "Do faktury",
  ksef: "W KSeF",
  payment: "Zapłata",
};

type StepBody = Omit<MonthStep, "key" | "label">;

function step(key: MonthStepKey, body: StepBody): MonthStep {
  return { key, label: STEP_LABELS[key], ...body };
}

const IDLE = { tone: "neutral", started: false, done: false } as const;

export function rcpStep(input: RcpInput): MonthStep {
  if (input.state === "loading") return step("rcp", { ...IDLE, value: "…", note: null });
  // Powód stoi w samym stanie, nie w drobnym druku: karta w Przeglądzie pokazuje
  // tylko stan, a awaria i brak dostępu nie mogą wyglądać tak samo (przegląd 20.11).
  if (input.state === "error") {
    return step("rcp", { ...IDLE, value: "nie udało się wczytać", note: null });
  }
  if (input.state === "unavailable") {
    return step("rcp", { ...IDLE, value: "bez dostępu", note: "rozliczenia RCP są poza Twoim dostępem" });
  }
  const total = input.rows.length;
  // Przyjęty plan miesiąca (`estimate`, E5.3) liczy się jak przyjęte RCP: faktura
  // do klienta idzie z planu, a różnicę koryguje następny miesiąc. Tak samo liczy
  // sekcja „Rozliczenie miesiąca i marża” (wiersze z `kind`).
  const accepted = input.rows.filter((row) => row.kind).length;
  const planned = input.rows.filter((row) => row.kind === "estimate").length;
  if (accepted === 0) {
    // NEXUS nie wie, czy RCP gdzieś czeka — mówi tylko, że go u siebie nie ma.
    return step("rcp", {
      ...IDLE,
      value: "brak w NEXUSIE",
      note: total ? `0 z ${countPl(total, "osoby", "osób", "osób")} z przyjętym RCP` : null,
    });
  }
  const plan = planned ? ` · ${planned} z planu` : "";
  const done = accepted === total;
  return step("rcp", {
    value: `${accepted} z ${total} przyjętych`,
    note: done ? `wszystkie RCP przyjęte${plan}` : `${total - accepted} bez przyjętego RCP${plan}`,
    tone: done ? "success" : "neutral",
    started: true,
    done,
  });
}

export function invoiceStep(data: Pick<ClientInvoicing, "summary">): MonthStep {
  const { summary } = data;
  const orders = countPl(summary.rows, "zamówienie", "zamówienia", "zamówień");
  const notes = [
    summary.totals_hidden ? null : orders,
    summary.unknown ? `${summary.unknown} czeka na zużycie MD` : null,
    summary.cost ? `${countPl(summary.cost, "kosztowe", "kosztowe", "kosztowych")} bez kwoty` : null,
  ].filter(Boolean);
  return step("invoice", {
    value: summary.totals_hidden ? orders : totalsText(summary.expected),
    note: notes.length ? notes.join(" · ") : null,
    tone: summary.unknown ? "warning" : "success",
    started: summary.rows > 0,
    done: summary.rows > 0 && summary.unknown === 0,
  });
}

export function ksefStep(data: Pick<ClientInvoicing, "summary">): MonthStep {
  const { summary } = data;
  const done = summary.rows > 0 && summary.invoiced === summary.rows && summary.differences === 0;
  const notes = [
    summary.differences
      ? countPl(summary.differences, "różnica do sprawdzenia", "różnice do sprawdzenia", "różnic do sprawdzenia")
      : null,
    summary.unmatched_invoices
      ? `${countPl(summary.unmatched_invoices, "faktura", "faktury", "faktur")} do przypisania`
      : null,
  ].filter(Boolean);
  return step("ksef", {
    value: `${summary.invoiced} z ${countPl(summary.rows, "zamówienia", "zamówień", "zamówień")}`,
    short: `${summary.invoiced} z ${summary.rows}`,
    note: notes.length ? notes.join(" · ") : done ? "każde zamówienie ma fakturę" : null,
    tone: summary.differences ? "warning" : done ? "success" : "neutral",
    started: summary.invoiced > 0,
    done,
  });
}

/** Stan zapłaty jednej faktury — wyłącznie z danych, które NEXUS ma. */
export type PaymentClass = "paid" | "partial" | "overdue" | "unknown" | "not_due" | "nothing";

export function paymentClass(invoice: SalesInvoice): PaymentClass {
  if (invoice.payment_status === "paid" || invoice.payment_status === "overpaid") return "paid";
  if (invoice.payment_status === "none") return "nothing";
  // Zaległość tylko z dowodem z ciągłych wyciągów (`payment_proof`, #3623).
  if (invoice.overdue_days > 0) return "overdue";
  // Wpłata części to fakt z wyciągu — jak „zapłacono część” w wierszu tabeli,
  // nawet gdy o reszcie NEXUS nie wie.
  if (invoice.payment_status === "partial") return "partial";
  if (invoice.payment_unknown) return "unknown";
  return "not_due";
}

/** Faktury miesiąca bez pominiętych przez Finanse i bez tych, przy których nie ma nic do zapłaty. */
function payable(invoices: readonly SalesInvoice[]): SalesInvoice[] {
  return invoices.filter(
    (invoice) => invoice.match_status !== "ignored" && paymentClass(invoice) !== "nothing",
  );
}

/** Wspólny powód braku danych (ten sam powód i rachunek) albo nic. */
function sharedUnknownNote(invoices: readonly SalesInvoice[]): string | null {
  const notes = new Set(invoices.map((invoice) => unknownReasonNote(invoice)));
  const [only] = [...notes];
  return notes.size === 1 && only ? only : null;
}

export interface PaymentOptions {
  /** „Po terminie” z dowodem z wyciągów; `false` — liczy się jak brak danych. */
  showOverdue?: boolean;
}

export function paymentStep(
  data: Pick<ClientInvoicing, "invoices">,
  { showOverdue = true }: PaymentOptions = {},
): MonthStep {
  const invoices = payable(data.invoices);
  if (invoices.length === 0) {
    return step("payment", { ...IDLE, value: "nie ma faktur", note: "zapłata po fakturze w KSeF" });
  }
  const byClass = (kind: PaymentClass) =>
    invoices.filter((invoice) => {
      const value = paymentClass(invoice);
      return (value === "overdue" && !showOverdue ? "unknown" : value) === kind;
    });
  const total = invoices.length;
  const paid = byClass("paid").length;
  const partial = byClass("partial").length;
  const overdue = byClass("overdue").length;
  const unknown = byClass("unknown");
  const notDue = byClass("not_due");
  const nextDue = notDue
    .map((invoice) => invoice.due_date)
    .filter((due): due is string => Boolean(due))
    .sort()[0];
  const texts = {
    overdue: overdue ? `${overdue} po terminie` : null,
    partial: partial ? `${partial} zapłacone w części` : null,
    unknown: unknown.length ? `${unknown.length} bez danych o zapłacie` : null,
    notDue: notDue.length ? `${notDue.length} przed terminem` : null,
  };
  const rest = (...skip: (keyof typeof texts)[]) =>
    (Object.keys(texts) as (keyof typeof texts)[])
      .filter((key) => !skip.includes(key))
      .map((key) => texts[key])
      .filter(Boolean)
      .join(" · ") || null;
  const tone: StatusDotTone = overdue ? "danger" : "neutral";

  if (paid === total) {
    return step("payment", {
      value: "zapłacone",
      note: countPl(total, "faktura zapłacona", "faktury zapłacone", "faktur zapłaconych"),
      tone: "success",
      started: true,
      done: true,
    });
  }
  if (paid > 0) {
    return step("payment", { value: `${paid} z ${total} zapłacone`, note: rest(), tone, started: true, done: false });
  }
  if (overdue > 0) {
    return step("payment", {
      value: `${overdue} z ${total} po terminie`,
      note: rest("overdue") ?? "z ciągłych wyciągów rachunku odbioru",
      tone,
      started: true,
      done: false,
    });
  }
  if (notDue.length === total) {
    return step("payment", {
      value: "przed terminem",
      note: nextDue ? `najbliższy termin ${formatDayMonthPl(nextDue)}` : null,
      tone,
      started: true,
      done: false,
    });
  }
  if (unknown.length === total) {
    return step("payment", {
      value: "brak danych o zapłacie",
      note: sharedUnknownNote(unknown) ?? "termin minął, a wyciągi rachunku tego nie rozstrzygają",
      tone,
      started: true,
      done: false,
    });
  }
  if (notDue.length > 0) {
    return step("payment", {
      value: `${notDue.length} z ${total} przed terminem`,
      short: `${notDue.length} przed terminem`,
      note: rest("notDue"),
      tone,
      started: true,
      done: false,
    });
  }
  return step("payment", {
    value: `${partial} z ${total} zapłacone w części`,
    short: `${partial} z ${total} w części`,
    note: rest("partial"),
    tone,
    started: true,
    done: false,
  });
}

/** Cztery kroki miesiąca; miesiąc bez zamówień i faktur — bez kroków. */
export function monthSteps(
  data: Pick<ClientInvoicing, "summary" | "invoices" | "rows">,
  rcp: RcpInput,
  options: PaymentOptions = {},
): MonthStep[] {
  if (data.rows.length === 0 && data.invoices.length === 0) return [];
  return [rcpStep(rcp), invoiceStep(data), ksefStep(data), paymentStep(data, options)];
}

/**
 * Gdzie stoi miesiąc: ostatni krok z danymi, a gdy jest skończony — następny.
 * RCP spoza NEXUSA nie zatrzymuje miesiąca na pierwszym kroku.
 */
export function frontierStep(steps: readonly MonthStep[]): MonthStep | null {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (!steps[index].started) continue;
    return steps[index].done && index + 1 < steps.length ? steps[index + 1] : steps[index];
  }
  return steps[0] ?? null;
}
