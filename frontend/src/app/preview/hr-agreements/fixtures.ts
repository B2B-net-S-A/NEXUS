/**
 * Dane fikcyjne harnessu „Umowy z ludźmi” (etap 5, E5) — z makiety „Umowa
 * zlecenia” rekomendacji „NEXUS a eBI24” (17.10.2026). Osoby, stawki i daty
 * są zmyślone; daty liczą się od bieżącego miesiąca przeglądarki, żeby
 * harness wyglądał tak samo w każdym miesiącu.
 */
import type { Person } from "@/lib/api/hr";
import type {
  Agreement,
  AgreementSettings,
  AgreementTemplate,
  AgreementTemplates,
  PersonAgreements,
} from "@/lib/api/hr-agreements";

/** Osoba z makiety: zlecenie, recepcja (ta sama co w harnessie „Dokumenty”). */
export const CELINA = { id: 120, name: "Celina Testowa", email: "celina.testowa@example.com" };
export const OLA = { id: 121, name: "Ola Nowak", email: "ola.nowak@example.com" };
export const MARTA = { id: 105, name: "Marta Fikcyjna" };

/** Pierwszy dzień miesiąca przesuniętego o `delta` od bieżącego (RRRR-MM-DD). */
export function monthStart(delta: number, now: Date = new Date()): string {
  const date = new Date(now.getFullYear(), now.getMonth() + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-01`;
}

function shiftDays(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(year, month - 1, day + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

const NO_ACTIONS = {
  edit: false,
  send: false,
  withdraw: false,
  cancel: false,
  mark_signed: false,
  apply: false,
};

function agreement(id: number, values: Partial<Agreement>): Agreement {
  return {
    id,
    user_id: CELINA.id,
    person_name: CELINA.name,
    kind: "agreement",
    employment_type: "zlecenie",
    form_label: "Umowa zlecenia",
    title: "Umowa zlecenia",
    status: "signed",
    status_label: "podpisana",
    template: { template_id: 31, version_id: 313, name: "Zlecenie — recepcja", kind: "zlecenie", version: 3 },
    base_agreement_id: null,
    hourly_rate: "32.00",
    currency: "PLN",
    rate_basis: "brutto",
    rate_from: monthStart(0),
    start_date: monthStart(0),
    end_date: null,
    agreement_date: monthStart(0),
    hours_confirmation: true,
    payout_day: 10,
    coordinator_user_id: MARTA.id,
    coordinator_name: MARTA.name,
    signing_channel: "autenti",
    signing_channel_label: "Autenti",
    sent_at: null,
    signed_on: null,
    signed_at: null,
    manual_reason: null,
    rejected_at: null,
    cancelled_at: null,
    cancel_reason: null,
    last_error: null,
    applied_at: null,
    apply_error: null,
    document_id: null,
    symfonia_pending: false,
    created_at: null,
    actions: NO_ACTIONS,
    ...values,
  };
}

function titled(kind: "agreement" | "annex", start: string): string {
  const [year, month, day] = start.split("-");
  return kind === "annex" ? `Aneks: stawka od ${day}.${month}.${year}` : `Umowa zlecenia od ${day}.${month}.${year}`;
}

/** Kadry oglądają Celinę: umowa i aneks podpisane, kolejny aneks czeka w Autenti. */
export function celinaAgreements(writer = true): PersonAgreements {
  const first = monthStart(-7);
  const raise = monthStart(-1);
  const next = monthStart(1);
  const can = (values: Partial<Agreement["actions"]>) => ({ ...NO_ACTIONS, ...(writer ? values : {}) });
  return {
    person: { user_id: CELINA.id, name: CELINA.name, employment_type: "zlecenie", employment_status: "active" },
    defaults: {
      employment_type: "zlecenie",
      payout_day: 10,
      coordinator_user_id: MARTA.id,
      coordinator_name: MARTA.name,
      hours_confirmation: true,
      currency: "PLN",
      hourly_rate: "32.00",
      base_agreement_id: 41,
      agreement_date: monthStart(0),
    },
    minimum_rates: { "2025": "30.50", "2026": "31.40", "2027": "31.40" },
    autenti_configured: true,
    can_write: writer,
    applies_rate: true,
    agreements: [
      agreement(43, {
        kind: "annex",
        title: titled("annex", next),
        status: "sent",
        status_label: "wysłana do podpisu",
        template: { template_id: 33, version_id: 331, name: "Aneks — stawka", kind: "annex", version: 1 },
        base_agreement_id: 41,
        hourly_rate: "33.50",
        rate_from: next,
        start_date: next,
        agreement_date: shiftDays(next, -10),
        sent_at: `${shiftDays(next, -9)}T10:20:00+01:00`,
        actions: can({ withdraw: true, cancel: true }),
      }),
      agreement(42, {
        kind: "annex",
        title: titled("annex", raise),
        status: "signed",
        status_label: "podpisana",
        template: { template_id: 33, version_id: 331, name: "Aneks — stawka", kind: "annex", version: 1 },
        base_agreement_id: 41,
        hourly_rate: "32.00",
        rate_from: raise,
        start_date: raise,
        signing_channel: "manual",
        signing_channel_label: "ręcznie, ze skanem",
        signed_on: shiftDays(raise, -6),
        signed_at: `${shiftDays(raise, -6)}T12:00:00+02:00`,
        manual_reason: "Podpis na papierze w biurze.",
        applied_at: `${shiftDays(raise, -6)}T12:00:00+02:00`,
        document_id: 7002,
      }),
      agreement(41, {
        title: titled("agreement", first),
        hourly_rate: "31.40",
        rate_from: first,
        start_date: first,
        agreement_date: shiftDays(first, -2),
        sent_at: `${shiftDays(first, -3)}T09:00:00+01:00`,
        signed_on: shiftDays(first, -1),
        signed_at: `${shiftDays(first, -1)}T15:40:00+01:00`,
        applied_at: `${shiftDays(first, -1)}T15:40:00+01:00`,
        document_id: 7001,
      }),
    ],
  };
}

/** Ola na B2B: szkic po nieudanej wysyłce i umowa podpisana, która nie przeszła do kartoteki. */
export function olaAgreements(): PersonAgreements {
  const start = monthStart(1);
  const signed = monthStart(0);
  return {
    ...celinaAgreements(),
    person: { user_id: OLA.id, name: OLA.name, employment_type: "b2b", employment_status: "active" },
    defaults: { ...celinaAgreements().defaults, employment_type: "b2b", hourly_rate: "95.00", base_agreement_id: null },
    agreements: [
      agreement(52, {
        user_id: OLA.id,
        person_name: OLA.name,
        kind: "annex",
        employment_type: "b2b",
        title: titled("annex", start),
        status: "draft",
        status_label: "szkic",
        template: { template_id: 33, version_id: 331, name: "Aneks — stawka", kind: "annex", version: 1 },
        hourly_rate: "100.00",
        rate_basis: "netto",
        rate_from: start,
        start_date: start,
        payout_day: null,
        signing_channel: null,
        signing_channel_label: null,
        last_error: "Autenti nie przyjęło umowy — spróbuj ponownie za chwilę albo oznacz ją jako podpisaną ręcznie, ze skanem. (Autenti: HTTP 503)",
        actions: { ...NO_ACTIONS, edit: true, send: true, mark_signed: true, cancel: true },
      }),
      agreement(51, {
        user_id: OLA.id,
        person_name: OLA.name,
        employment_type: "b2b",
        form_label: "Umowa B2B",
        title: `Umowa B2B od ${signed.split("-").reverse().join(".")}`,
        template: { template_id: 32, version_id: 322, name: "B2B biura", kind: "b2b", version: 2 },
        hourly_rate: "95.00",
        rate_basis: "netto",
        rate_from: signed,
        start_date: signed,
        payout_day: null,
        signed_on: shiftDays(signed, -2),
        signed_at: `${shiftDays(signed, -2)}T11:00:00+02:00`,
        apply_error: `Miesiąc płac ${signed.slice(5, 7)}.${signed.slice(0, 4)} jest zamknięty — stawkę zmienią Płace po ponownym otwarciu.`,
        actions: { ...NO_ACTIONS, apply: true },
      }),
    ],
  };
}

function template(id: number, values: Partial<AgreementTemplate>): AgreementTemplate {
  return {
    id,
    kind: "zlecenie",
    kind_label: "Umowa zlecenia",
    name: "Zlecenie — recepcja",
    description: null,
    is_active: true,
    versions: [],
    ...values,
  };
}

function version(id: number, number: number, created: string, agreements: number, file: string) {
  return {
    id,
    version: number,
    file_name: file,
    file_size: 48_213,
    fields: ["person_name", "rate", "start_date", "hours_confirmation", "coordinator_name"],
    created_at: `${created}T10:00:00+02:00`,
    agreements,
  };
}

export const TEMPLATES: AgreementTemplates = {
  items: [
    template(31, {
      description: "wzór kancelarii",
      versions: [
        version(313, 3, monthStart(-1), 2, "zlecenie-recepcja-v3.docx"),
        version(312, 2, monthStart(-5), 4, "zlecenie-recepcja-v2.docx"),
        version(311, 1, monthStart(-9), 1, "zlecenie-recepcja.docx"),
      ],
    }),
    template(32, {
      kind: "b2b",
      kind_label: "Umowa B2B",
      name: "B2B biura",
      versions: [version(322, 2, monthStart(-2), 3, "b2b-biuro-v2.docx"), version(321, 1, monthStart(-8), 5, "b2b-biuro.docx")],
    }),
    template(33, {
      kind: "annex",
      kind_label: "Aneks",
      name: "Aneks — stawka",
      versions: [version(331, 1, monthStart(-3), 2, "aneks-stawka.docx")],
    }),
    template(34, {
      kind: "uop",
      kind_label: "Umowa o pracę",
      name: "UoP — stary wzór",
      is_active: false,
      versions: [version(341, 1, monthStart(-12), 1, "uop-2025.docx")],
    }),
  ],
  fields: [
    { field: "person_name", label: "imię i nazwisko osoby" },
    { field: "employment_form", label: "forma współpracy (np. „umowa zlecenia”)" },
    { field: "rate", label: "stawka za godzinę (np. 32,00)" },
    { field: "rate_words", label: "stawka słownie, tylko w złotych" },
    { field: "currency", label: "waluta stawki (PLN, EUR, USD)" },
    { field: "rate_basis", label: "„netto” na B2B, „brutto” na zleceniu i umowie o pracę" },
    { field: "start_date", label: "od kiedy (dd.mm.rrrr)" },
    { field: "end_date", label: "do kiedy (dd.mm.rrrr) — puste przy umowie bez daty końca" },
    { field: "indefinite", label: "umowa bez daty końca — do warunku" },
    { field: "hours_confirmation", label: "potwierdzanie godzin (art. 8b) — do warunku" },
    { field: "payout_day", label: "dzień wypłaty w następnym miesiącu (np. 10)" },
    { field: "coordinator_name", label: "koordynator, który potwierdza godziny" },
    { field: "agreement_date", label: "data zawarcia (dd.mm.rrrr)" },
    { field: "base_agreement_date", label: "w aneksie: data zmienianej umowy" },
  ],
  required: {
    b2b: ["person_name", "rate", "start_date"],
    zlecenie: ["person_name", "rate", "start_date"],
    uop: ["person_name", "rate", "start_date"],
    annex: ["person_name", "rate", "start_date"],
  },
  kinds: { b2b: "Umowa B2B", zlecenie: "Umowa zlecenia", uop: "Umowa o pracę", annex: "Aneks" },
  max_bytes: 2 * 1024 * 1024,
};

export const ACTIVE_TEMPLATES: AgreementTemplates = {
  ...TEMPLATES,
  items: TEMPLATES.items.filter((item) => item.is_active),
};

export const SETTINGS: AgreementSettings = { enabled: true, autenti_configured: true };

/** Katalog ludzi do wyboru koordynatora. */
export const PEOPLE: { items: Person[]; total: number } = {
  items: [CELINA, OLA, { id: MARTA.id, name: MARTA.name, email: "marta.fikcyjna@example.com" }].map(
    (row) => ({
      user_id: row.id,
      name: row.name,
      email: row.email,
      job_title: null,
      department: null,
      phone: null,
      default_location: "onsite",
      employment_status: "active",
      manager_user_id: null,
      manager_name: null,
      scope: "card",
    }),
  ),
  total: 3,
};
