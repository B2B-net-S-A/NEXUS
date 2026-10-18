// Umowy z ludźmi — słowa i reguły okna „Nowa umowa albo aneks” (makieta
// „Umowa zlecenia”, 17.10.2026). Serwer sprawdza to samo i więcej; tu tylko
// to, co Kadry powinny zobaczyć, zanim klikną „Zapisz”.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type { EmploymentType } from "@/lib/api/hr";
import type {
  Agreement,
  AgreementInput,
  AgreementKind,
  AgreementStatus,
  AgreementTemplate,
} from "@/lib/api/hr-agreements";
import type { Currency } from "@/lib/api/hr-payroll";
import { formatIsoDatePl } from "@/lib/date-pl";

export const STATUS_TONE: Record<AgreementStatus, StatusDotTone> = {
  draft: "neutral",
  sent: "info",
  signed: "success",
  rejected: "danger",
  cancelled: "neutral",
};

export const FORM_WORDS: Record<EmploymentType, string> = {
  b2b: "B2B",
  zlecenie: "zlecenie",
  uop: "umowa o pracę",
};

/** „1234.5” → „1 234,50”. */
export function formatAmount(value: string | number): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return String(value);
  const [whole, fraction] = amount.toFixed(2).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ")},${fraction}`;
}

export function currencyWord(currency: Currency): string {
  return currency === "PLN" ? "zł" : currency;
}

/** „32,00 zł brutto za godzinę”. */
export function rateLabel(agreement: Pick<Agreement, "hourly_rate" | "currency" | "rate_basis">): string {
  return `${formatAmount(agreement.hourly_rate)} ${currencyWord(agreement.currency)} ${agreement.rate_basis} za godzinę`;
}

/** Druga linia stanu: data i kanał podpisu albo powód. */
export function statusNote(agreement: Agreement): string | null {
  switch (agreement.status) {
    case "sent":
      return agreement.sent_at ? `Autenti · ${formatIsoDatePl(agreement.sent_at)}` : "Autenti";
    case "signed": {
      const when = formatIsoDatePl(agreement.signed_on);
      return agreement.signing_channel === "manual" ? `${when} · ręcznie, ze skanem` : `${when} · Autenti`;
    }
    case "rejected":
      return formatIsoDatePl(agreement.rejected_at);
    case "cancelled":
      return agreement.cancel_reason;
    default:
      return agreement.last_error;
  }
}

/** Co jeszcze wymaga uwagi przy umowie (pokazujemy pod wierszem). */
export function attention(agreement: Agreement): string | null {
  if (agreement.status === "signed" && !agreement.applied_at && agreement.apply_error) {
    return `Podpisana, ale nie przeszła do kartoteki: ${agreement.apply_error}`;
  }
  if (agreement.status === "sent" && agreement.last_error) return agreement.last_error;
  return null;
}

export function periodLabel(agreement: Pick<Agreement, "start_date" | "end_date">): string {
  const start = formatIsoDatePl(agreement.start_date);
  return agreement.end_date ? `${start} – ${formatIsoDatePl(agreement.end_date)}` : `od ${start} · bez daty końca`;
}

// ── Okno szkicu ───────────────────────────────────────────────────────────────

export interface DraftForm {
  templateId: string;
  baseAgreementId: string;
  rate: string;
  currency: Currency;
  startDate: string;
  endDate: string;
  indefinite: boolean;
  agreementDate: string;
  hoursConfirmation: boolean;
  payoutDay: string;
  coordinatorId: string;
}

export interface TemplateChoice {
  templateId: number;
  label: string;
  kind: AgreementKind;
  employmentType: EmploymentType | null;
}

/** Wzory w użyciu z najnowszą wersją: „Umowa zlecenia · recepcja · wersja 3”. */
export function templateChoices(templates: AgreementTemplate[]): TemplateChoice[] {
  return templates
    .filter((template) => template.is_active && template.versions.length > 0)
    .map((template) => ({
      templateId: template.id,
      label: `${template.kind_label} · ${template.name} · wersja ${template.versions[0].version}`,
      kind: template.kind === "annex" ? "annex" : "agreement",
      employmentType: template.kind === "annex" ? null : template.kind,
    }));
}

/** Stawka w historii stawek obowiązuje od 1. dnia miesiąca. */
export function rateFrom(kind: AgreementKind, startDate: string): string {
  return kind === "annex" ? startDate : `${startDate.slice(0, 8)}01`;
}

export function parseRate(value: string): number | null {
  const cleaned = value.replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return Number(cleaned);
}

export interface DraftContext {
  kind: AgreementKind;
  employmentType: EmploymentType;
  minimumRates: Record<string, string>;
}

/** Pierwszy problem formularza albo `null` (te same reguły co serwer). */
export function draftProblem(form: DraftForm, context: DraftContext): string | null {
  if (!form.templateId) return "Wybierz wzór umowy.";
  const rate = parseRate(form.rate);
  if (rate === null || rate <= 0) return "Stawka musi być liczbą większą od 0, np. 32,00.";
  if (!form.startDate) return "Podaj, od kiedy obowiązuje umowa.";
  if (!form.indefinite && form.endDate && form.endDate < form.startDate) {
    return "Data końca nie może być przed datą początku.";
  }
  if (!form.indefinite && !form.endDate) return "Podaj datę końca albo zaznacz „bez daty końca”.";
  if (context.kind === "annex" && !form.startDate.endsWith("-01")) {
    return "Aneks zmienia stawkę od 1. dnia miesiąca — tak liczy historia stawek.";
  }
  if (context.kind === "agreement" && context.employmentType === "zlecenie") {
    if (!form.hoursConfirmation) {
      return "Na umowie zlecenia potwierdzanie godzin jest obowiązkowe (art. 8b).";
    }
  }
  const minimum = mandateMinimum(context, form);
  if (minimum !== null && rate < minimum) {
    return `Minimalna stawka na zleceniu w ${form.startDate.slice(0, 4)} to ${formatAmount(minimum)} zł/h brutto.`;
  }
  if (context.employmentType !== "b2b" && form.payoutDay) {
    const day = Number(form.payoutDay);
    if (!Number.isInteger(day) || day < 1 || day > 31) return "Dzień wypłaty to liczba od 1 do 31.";
  }
  return null;
}

/** Minimum roku umowy, gdy dotyczy (zlecenie w złotych), inaczej `null`. */
export function mandateMinimum(
  context: Pick<DraftContext, "employmentType" | "minimumRates">,
  form: Pick<DraftForm, "currency" | "startDate">,
): number | null {
  if (context.employmentType !== "zlecenie" || form.currency !== "PLN" || !form.startDate) return null;
  const raw = context.minimumRates[form.startDate.slice(0, 4)];
  return raw === undefined ? null : Number(raw);
}

export function draftInput(form: DraftForm, context: Pick<DraftContext, "kind" | "employmentType">): AgreementInput {
  const parsed = parseRate(form.rate);
  return {
    template_id: Number(form.templateId),
    base_agreement_id:
      context.kind === "annex" && form.baseAgreementId ? Number(form.baseAgreementId) : null,
    hourly_rate: parsed === null ? form.rate : parsed.toFixed(2),
    currency: form.currency,
    start_date: form.startDate,
    end_date: form.indefinite ? null : form.endDate || null,
    agreement_date: form.agreementDate,
    hours_confirmation: form.hoursConfirmation,
    payout_day: context.employmentType === "b2b" || !form.payoutDay ? null : Number(form.payoutDay),
    coordinator_user_id: form.coordinatorId ? Number(form.coordinatorId) : null,
  };
}

/** „Po podpisaniu NEXUS sam…” — lista z makiety, dopasowana do rodzaju i formy. */
export function afterSigning(context: Pick<DraftContext, "kind" | "employmentType">, startDate: string): string[] {
  const from = startDate ? formatIsoDatePl(rateFrom(context.kind, startDate)) : "daty początku";
  const steps = [`zapisze stawkę od ${from} w historii stawek`];
  if (context.kind === "agreement") {
    steps.push(`ustawi formę „${FORM_WORDS[context.employmentType]}” i potwierdzanie godzin w kartotece`);
  }
  steps.push(context.kind === "annex" ? "doda aneks do dokumentów osoby" : "doda umowę do dokumentów osoby");
  if (context.employmentType !== "b2b") steps.push("przekaże dane do Symfonii przy najbliższym eksporcie");
  return steps;
}
