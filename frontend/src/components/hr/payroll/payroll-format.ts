// Formatowanie Płac: sumy kwot, statusy premii i timesheetów. Kwoty, daty
// i miesiące z `@/lib/money` i `@/lib/date-pl` (jeden format w całej aplikacji).
// Czyste funkcje — testowane bez renderu (`__tests__/payroll-format.test.ts`).

import type { InlineStat } from "@/components/ds/InlineStats";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { STATUS_TONE } from "@/components/hr/time/time-format";
import type {
  BonusCategory,
  BonusRow,
  BonusStatus,
  Currency,
  PayrollMonthDetail,
  PayrollPerson,
  RateRow,
  TimesheetStatus,
} from "@/lib/api/hr-payroll";
import { TIMESHEET_STATUS_LABELS } from "@/lib/api/hr-time";
import { formatDayMonthPl } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";
import { warsawToday } from "@/lib/warsaw-date";

export const CURRENCIES: Currency[] = ["PLN", "EUR", "USD"];

export const CATEGORY_LABELS: Record<BonusCategory, string> = {
  sales: "Sprzedaż",
  delivery_lead: "Delivery Lead",
  recruiter: "Rekruter",
  custom: "Inna",
  league: "Liga",
};

/** Kategorie do ręcznej premii (Liga powstaje z wyników rywalizacji). */
export const MANUAL_CATEGORIES: BonusCategory[] = [
  "custom",
  "sales",
  "delivery_lead",
  "recruiter",
];

export const EMPLOYMENT_LABELS: Record<string, string> = {
  uop: "UoP",
  b2b: "B2B",
  zlecenie: "Zlecenie",
};

/** Sumy per waluta w jednej linii: „12 345,00 zł · 100,00 EUR”. */
export function formatTotals(totals: Record<string, string> | undefined): string {
  const entries = Object.entries(totals ?? {}).filter(([, value]) => Number(value) !== 0);
  if (entries.length === 0) return "—";
  return entries.map(([currency, value]) => formatMoney(value, currency)).join(" · ");
}

/** „168” / „7,5” — godziny bez zbędnych zer. */
export function formatHours(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
}

/** Segment adresu `/people/payroll/2026-09`. */
export function ymSegment(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function parseYm(segment: string | undefined | null): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(segment ?? "");
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (year < 2020 || year > 2100 || month < 1 || month > 12) return null;
  return { year, month };
}

/** Bieżący miesiąc (Warszawa) jako „RRRR-MM” — wartość pola `type="month"`. */
export function warsawMonth(now: Date = new Date()): string {
  return warsawToday(now).slice(0, 7);
}

export const BONUS_STATUS_LABELS: Record<BonusStatus, string> = {
  proposed: "propozycja",
  assigned: "przyznana",
  cancelled: "anulowana",
};

export const BONUS_STATUS_TONE: Record<BonusStatus, StatusDotTone> = {
  proposed: "info",
  assigned: "success",
  cancelled: "neutral",
};

/**
 * Status timesheetu osoby w Płacach — słownik i kolory te same co w „Moim
 * miesiącu” i „Moim zespole”; osoba bez obowiązku timesheetu: „bez obowiązku”.
 */
export function timesheetLabel(status: TimesheetStatus | null, required: boolean): string {
  if (status) return TIMESHEET_STATUS_LABELS[status].toLowerCase();
  return required ? TIMESHEET_STATUS_LABELS.missing.toLowerCase() : "bez obowiązku";
}

export function timesheetTone(status: TimesheetStatus | null, required: boolean): StatusDotTone {
  if (status) return STATUS_TONE[status];
  return required ? STATUS_TONE.missing : "neutral";
}

/** Status premii dla osoby: „liczy się do 30.09”, „czeka na zatwierdzenie”… */
export function bonusStateLabel(bonus: Pick<BonusRow, "status" | "eligible" | "eligible_on">): string {
  if (bonus.status === "proposed") {
    if (bonus.eligible === false && bonus.eligible_on) {
      return `liczy się do ${formatDayMonthPl(bonus.eligible_on)}`;
    }
    return "czeka na zatwierdzenie";
  }
  return BONUS_STATUS_LABELS[bonus.status];
}

/**
 * Powód anulowania premii dla osoby. Automat anuluje z kodem (premia nie
 * znika bez śladu — etap 2, D2), ręczne anulowanie to „manual”.
 */
export function cancelReasonLabel(
  reason: string | null | undefined,
  requiredDays = 21,
): string | null {
  switch (reason) {
    case "contract_ended":
      return `kontrakt zakończony przed ${requiredDays}. dniem roboczym`;
    case "contract_void":
      return "kontrakt unieważniony";
    case "contract_deleted":
      return "kontrakt usunięty";
    case "rule_no_longer_applies":
      return "zmieniły się warunki premii";
    case "manual":
      return "anulowana przez Płace albo koordynatora";
    default:
      return null;
  }
}

/** Procent paska „X z 21 dni roboczych” (0–100). */
export function progressPercent(elapsed: number | null | undefined, required: number | undefined): number {
  if (!required || required <= 0 || elapsed == null) return 0;
  return Math.max(0, Math.min(100, Math.round((elapsed / required) * 100)));
}

/** „Placement” albo opis premii — pierwsza linia komórki. */
export function bonusTitle(bonus: Pick<BonusRow, "description" | "category_label">): string {
  return bonus.description?.trim() || bonus.category_label;
}

/** Kwota z pola formularza („1 234,5”) → tekst dziesiętny dla API albo `null`. */
export function parseAmount(raw: string): string | null {
  const cleaned = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return cleaned;
}

/**
 * Komunikat po zapisie stawki. Serwer zapisuje, ale ostrzega (rok bez
 * minimalnej stawki zlecenia albo stawka w innej walucie niż złoty, D7) —
 * ostrzeżenie doklejone, typ „info” (wzorzec `leaveToast`).
 */
export function rateToast(row?: Pick<RateRow, "warning"> | null): [string, "success" | "info"] {
  const warning = row?.warning?.trim();
  return warning ? [`Stawka zapisana. ${warning}`, "info"] : ["Stawka zapisana", "success"];
}

/** Liczby nad tabelą (czysta funkcja — test bez renderu). */
export function monthStats(detail: PayrollMonthDetail): InlineStat[] {
  const stats: InlineStat[] = [
    { id: "people", label: "osób", value: detail.stats.people },
    {
      id: "approved",
      label: "timesheetów zaakceptowanych",
      value: detail.stats.timesheets_approved,
    },
    { id: "submitted", label: "czeka na akceptację", value: detail.stats.timesheets_submitted },
    { id: "missing", label: "nie wysłanych", value: detail.stats.timesheets_missing },
    { id: "proposals", label: "premie do decyzji", value: detail.stats.proposals },
  ];
  if (detail.totals) {
    stats.push({
      id: "totals",
      label: "razem do wypłaty",
      value: formatTotals(detail.totals),
      title: "Liczone są tylko zaakceptowane godziny i przyznane premie.",
    });
  }
  return stats;
}

/**
 * Przyciski wiersza „Premie do decyzji”. Propozycję ręczną przełożonego
 * zatwierdzają tylko Płace, nigdy jej autor (decyzja Artura 19.10.2026) —
 * serwer mówi to w `can_approve`; autor może swoją propozycję wycofać.
 */
export function bonusDecision(
  row: BonusRow,
  meId: number | undefined,
): { approve: boolean; rejectLabel: "Odrzuć" | "Wycofaj" } {
  const ownManual = row.source === "manual" && meId !== undefined && row.proposed_by === meId;
  return { approve: row.can_approve !== false, rejectLabel: ownManual ? "Wycofaj" : "Odrzuć" };
}

/**
 * Przyciski wiersza „Premie przyznane”. Przełożony poprawia kwotę tylko we
 * własnej propozycji — przyznaną zmieniają Płace (serwer odpowiada 403, audyt
 * 21.10.2026). Anulować może każdą premię, którą sam przyznał, także po
 * zatwierdzeniu przez Płace (decyzja Artura 22.10.2026, serwer na to pozwala).
 */
export function assignedBonusActions(
  row: Pick<BonusRow, "recipient_user_id" | "proposed_by" | "status">,
  ctx: { open: boolean; payroll: boolean; meId: number | undefined },
): { edit: boolean; cancel: boolean } {
  const allowed = ctx.open && ctx.meId !== row.recipient_user_id;
  const own = ctx.meId !== undefined && row.proposed_by === ctx.meId;
  return {
    edit: allowed && (ctx.payroll || (own && row.status === "proposed")),
    cancel: allowed && (ctx.payroll || own),
  };
}

/** Komunikat po dodaniu premii ręcznej: od przełożonego czeka na Płace. */
export function bonusCreatedToast(created: Pick<BonusRow, "status">): string {
  return created.status === "proposed" ? "Premia czeka na zatwierdzenie Płac" : "Premia przyznana";
}

/** Premie podzielone na sekcje ekranu. */
export function splitBonuses(bonuses: BonusRow[]): {
  toDecide: BonusRow[];
  assigned: BonusRow[];
  cancelled: number;
} {
  return {
    toDecide: bonuses.filter((b) => b.status === "proposed"),
    assigned: bonuses.filter((b) => b.status === "assigned"),
    cancelled: bonuses.filter((b) => b.status === "cancelled").length,
  };
}

// ── Zamknięcie miesiąca: stepper, podział wypłaty, decyzje (makieta 19.10.2026) ──

export type CloseStepKey = "hours" | "bonuses" | "check" | "close";
/** `warn` — krok niedomknięty, ale nie blokuje (godziny bez akceptacji to ostrzeżenie). */
export type CloseStepState = "done" | "current" | "todo" | "warn";

export interface CloseStep {
  key: CloseStepKey;
  label: string;
  detail: string;
  state: CloseStepState;
  /** Pasek kroku „Godziny” (0–100). */
  progress?: number;
}

export interface CloseSteps {
  steps: CloseStep[];
  /** „Zamknij miesiąc” aktywne: serwer pozwala, premie z decyzją, ostrzeżenia potwierdzone. */
  ready: boolean;
  /** Ostrzeżenia czekają na potwierdzenie (krok „Kontrola”). */
  needsAcknowledge: boolean;
}

/** Proponowane premie, o których można już zdecydować (po terminie). */
export function decidableBonuses(bonuses: readonly BonusRow[]): BonusRow[] {
  return bonuses.filter((b) => b.status === "proposed" && b.eligible !== false);
}

function sumByCurrency(rows: readonly Pick<BonusRow, "amount" | "currency">[]): Record<string, string> {
  const sums: Record<string, number> = {};
  for (const row of rows) sums[row.currency] = (sums[row.currency] ?? 0) + Number(row.amount);
  return Object.fromEntries(Object.entries(sums).map(([currency, value]) => [currency, value.toFixed(2)]));
}

/** Pierwsza część komunikatu ostrzeżenia („2 os. bez zatwierdzonego timesheetu”). */
function warningShort(message: string): string {
  return message.split(" — ")[0] ?? message;
}

/**
 * Kroki zamknięcia: Godziny → Premie → Kontrola → Zamknij. Twardo blokuje
 * tylko to, co blokuje serwer: każda propozycja premii z miesiąca (także ta,
 * która jeszcze „liczy się”) i niepotwierdzone ostrzeżenia. Godziny bez
 * akceptacji są ostrzeżeniem — krok świeci się na żółto, a potwierdza się je
 * w „Kontroli”.
 */
export function closeSteps(
  detail: Pick<PayrollMonthDetail, "status" | "can_close" | "people" | "bonuses" | "stats" | "warnings" | "closed_at">,
  acknowledged: boolean,
): CloseSteps {
  const closed = detail.status === "closed";
  const required = detail.people.filter((p) => p.timesheet_required);
  const approved = required.filter((p) => p.timesheet_status === "approved").length;
  const hoursDone = closed || approved === required.length;
  const decidable = decidableBonuses(detail.bonuses);
  const pending = closed ? 0 : detail.stats.proposals;
  const bonusesDone = pending === 0;
  const counting = Math.max(0, pending - decidable.length);
  const warnings = closed ? [] : (detail.warnings ?? []);
  const checkDone = warnings.length === 0 || acknowledged;
  const ready = !closed && detail.can_close && bonusesDone && checkDone;

  const bonusDetail = bonusesDone
    ? "wszystkie z decyzją"
    : [
        decidable.length > 0 ? `${decidable.length} do decyzji · ${formatTotals(sumByCurrency(decidable))}` : null,
        counting > 0 ? `${counting} jeszcze liczy się` : null,
      ]
        .filter(Boolean)
        .join(" · ");
  const checkDetail =
    warnings.length === 0
      ? "bez ostrzeżeń"
      : acknowledged
        ? "ostrzeżenia potwierdzone"
        : warnings.length === 1
          ? warningShort(warnings[0].message)
          : `${warnings.length} ostrzeżenia do potwierdzenia`;
  const closeDetail = closed
    ? `zamknięty${detail.closed_at ? ` ${formatDayMonthPl(detail.closed_at.slice(0, 10))}` : ""}`
    : !detail.can_close
      ? "od ostatniego dnia miesiąca"
      : ready
        ? "gotowe do zamknięcia"
        : "po krokach 1–3";

  return {
    ready,
    needsAcknowledge: warnings.length > 0 && !acknowledged,
    steps: [
      {
        key: "hours",
        label: "Godziny",
        detail:
          required.length === 0 ? "nikt nie składa raportu" : `${approved} z ${required.length} zaakceptowane`,
        state: hoursDone ? "done" : "warn",
        progress: required.length === 0 ? 100 : Math.round((approved / required.length) * 100),
      },
      { key: "bonuses", label: "Premie", detail: bonusDetail, state: bonusesDone ? "done" : "current" },
      {
        key: "check",
        label: "Kontrola",
        detail: checkDetail,
        state: checkDone ? "done" : bonusesDone ? "current" : "todo",
      },
      {
        key: "close",
        label: "Zamknij miesiąc",
        detail: closeDetail,
        state: closed ? "done" : ready ? "current" : "todo",
      },
    ],
  };
}

export interface PayoutCurrency {
  currency: string;
  total: number;
  hours: number;
  bonuses: number;
}

export interface PayoutForm {
  form: string;
  label: string;
  people: number;
  totals: Record<string, number>;
}

const FORM_ORDER = ["b2b", "uop", "zlecenie"];

/**
 * „Razem do wypłaty” z linii osób (Płace): suma per waluta z podziałem na
 * godziny i premie oraz per forma współpracy. Liczy tylko to, co serwer
 * policzył do płac (zaakceptowane godziny, przyznane premie).
 */
export function payoutBreakdown(people: readonly PayrollPerson[]): {
  currencies: PayoutCurrency[];
  forms: PayoutForm[];
} {
  const currencies = new Map<string, PayoutCurrency>();
  const forms = new Map<string, PayoutForm>();
  for (const person of people) {
    const lines = (person.lines ?? []).filter((line) => Number(line.total) !== 0);
    if (lines.length === 0) continue;
    const formKey = person.employment_type ?? "";
    const form = forms.get(formKey) ?? {
      form: formKey,
      label: EMPLOYMENT_LABELS[formKey] ?? "Bez formy",
      people: 0,
      totals: {},
    };
    form.people += 1;
    for (const line of lines) {
      const sum = currencies.get(line.currency) ?? { currency: line.currency, total: 0, hours: 0, bonuses: 0 };
      sum.total += Number(line.total);
      sum.hours += Number(line.hours_amount ?? 0);
      sum.bonuses += Number(line.bonus_total);
      currencies.set(line.currency, sum);
      form.totals[line.currency] = (form.totals[line.currency] ?? 0) + Number(line.total);
    }
    forms.set(formKey, form);
  }
  const rank = (form: string) => {
    const index = FORM_ORDER.indexOf(form);
    return index < 0 ? FORM_ORDER.length : index;
  };
  return {
    currencies: [...currencies.values()].sort((a, b) =>
      a.currency === "PLN" ? -1 : b.currency === "PLN" ? 1 : a.currency.localeCompare(b.currency),
    ),
    forms: [...forms.values()].sort((a, b) => rank(a.form) - rank(b.form)),
  };
}

/** Wiersz „Premii do decyzji”, który Płace mogą zaznaczyć do „Zatwierdź zaznaczone”. */
export function batchSelectable(row: BonusRow, meId: number | undefined): boolean {
  return (
    row.status === "proposed" &&
    row.can_approve !== false &&
    row.recipient_user_id !== meId
  );
}

/** Pasek pod listą: „Zaznaczono 5 · 11 529,20 zł”. */
export function selectionSummary(
  rows: readonly BonusRow[],
  selected: ReadonlySet<number>,
): { count: number; label: string } {
  const chosen = rows.filter((row) => selected.has(row.id));
  return { count: chosen.length, label: formatTotals(sumByCurrency(chosen)) };
}

/** Osoba „do wyjaśnienia”: raport bez akceptacji (gdy go składa) albo godziny bez stawki. */
export function needsAttention(person: Pick<PayrollPerson, "timesheet_required" | "timesheet_status" | "rate_missing">): boolean {
  return (person.timesheet_required && person.timesheet_status !== "approved") || Boolean(person.rate_missing);
}

/**
 * „Przypomnij” w wierszu osoby: szkic albo brak raportu → osobie; raport
 * czeka na akceptację → akceptującemu (tylko Płace — przełożony sam akceptuje).
 */
export function reminderAction(
  person: Pick<PayrollPerson, "timesheet_required" | "timesheet_status" | "employment_type">,
  scope: "payroll" | "team",
): string | null {
  if (!person.timesheet_required) return null;
  const status = person.timesheet_status;
  if (status === null || status === "draft") return "Przypomnij";
  if (status === "submitted" && scope === "payroll") {
    return `Ponagl ${employmentTerms(person.employment_type).coordinator_genitive}`;
  }
  return null;
}
