/** Polskie etykiety osi czasu kontraktu (zakładka „Timeline" w `/contracts/[id]`).
 *
 *  Backend (`GET /api/contracts/{id}/activities`) wysyła surowe slugi
 *  `Activity.action` („synced_with_orders", „terminated", „updated") i JSON
 *  `details` z kluczami technicznymi (`source_order_id`, identyfikator
 *  jednorazowej korekty danych w `source`). Do UAT 09.2026 (B23) zakładka
 *  renderowała slug jak leci i `<pre>` z JSON-em — użytkownik musiał czytać
 *  strukturę techniczną, żeby zrozumieć, co się zmieniło.
 *
 *  Wzorzec: `components/v2/pages/candidate-timeline-labels.ts`. Nieznany slug
 *  NIGDY nie wraca dosłownie; nieznany klucz szczegółów dostaje czytelną formę
 *  (bez podkreśleń), a surowy JSON zostaje pod rozwijanymi „Danymi
 *  technicznymi" w widoku.
 */

import { CONTRACT_FIELD_LABELS, CONTRACT_TERMINATION_REASONS } from "@/lib/api";
import { formatDateTimePl, formatIsoDatePl } from "@/lib/date-pl";

const ACTION_LABELS: Record<string, string> = {
  created: "Utworzono kontrakt",
  updated: "Zaktualizowano dane kontraktu",
  status_updated: "Zmieniono status kontraktu",
  terminated: "Zakończono współpracę",
  end_date_cleared: "Wyczyszczono datę zakończenia (umowa bezterminowa)",
  synced_with_orders: "Zsynchronizowano z zamówieniami klienta",
  bulk_marked_ended: "Zakończono współpracę (operacja zbiorcza)",
  contracts_merged: "Scalono zduplikowane kontrakty",
  draft_initialized: "Przygotowano szkic do podpisu",
  draft_finalized: "Zamknięto szkic i przekazano do podpisu",
  signature_initiated: "Rozpoczęto proces podpisu",
  signature_sent: "Wysłano do podpisu",
  signature_send_failed: "Nie udało się wysłać do podpisu",
  signature_remind_sent: "Wysłano przypomnienie o podpisie",
  signature_signed: "Podpisano",
  signature_completed: "Zakończono proces podpisu",
  signature_withdrawn: "Wycofano z podpisu",
  signature_expired: "Wygasł termin podpisu",
  equipment_added: "Dodano sprzęt",
  equipment_updated: "Zaktualizowano sprzęt",
  equipment_removed: "Usunięto sprzęt",
  document_uploaded: "Dodano dokument",
  document_deleted: "Usunięto dokument",
  b2b_generated: "Wygenerowano umowę B2B",
  auto_drafted_from_order_mail: "Założono szkic z zamówienia z maila",
  deleted: "Usunięto kontrakt",
  force_deleted_signed: "Usunięto podpisany kontrakt (wymuszone)",
};

const SLUG_RE = /^[a-z0-9_]+$/;

/** Etykieta `Activity.action` z osi czasu kontraktu. */
export function contractActivityLabel(action: string | null | undefined): string {
  if (!action) return "Zdarzenie";
  const known = ACTION_LABELS[action];
  if (known) return known;
  return SLUG_RE.test(action) ? "Zdarzenie systemowe" : action;
}

const DETAIL_LABELS: Record<string, string> = {
  ...CONTRACT_FIELD_LABELS,
  status: "Status",
  from_status: "Status przed",
  to_status: "Status po",
  previous_status: "Status przed",
  previous_end_date: "Poprzednia data zakończenia",
  client_order_start_date: "Początek zamówienia u klienta",
  client_order_end_date: "Koniec zamówienia u klienta",
  previous_client_order_end_date: "Poprzedni koniec zamówienia u klienta",
  source: "Źródło zmiany",
  source_order_id: "Zamówienie źródłowe",
  synced_orders: "Zsynchronizowane zamówienia",
  order_cost_synced: "Zamówienia z przepisaną stawką kosztową",
  revenue_steps_changed: "Zmienione kroki stawki przychodowej",
  order_period_changed: "Zmieniono okres zamówienia",
  period_changed: "Zmieniono okres zamówienia",
  rate_client_currency_changed: "Zmieniono walutę stawki przychodowej",
  auto_activated: "Aktywowano automatycznie",
  order_drafts_inherited_rates: "Szkice zamówień odziedziczyły stawki",
  candidate_rate_schedule_steps: "Liczba kroków stawki kandydata",
  framework_rate_schedule_steps: "Liczba kroków stawki ramowej",
  termination_reason: "Powód zakończenia",
  terminated_at: "Data zakończenia współpracy",
  termination_lessons: "Kto i dlaczego",
  early: "Przed planowanym końcem",
  business_day: "Dzień roboczy",
  contract_id: "Kontrakt",
  survivor_contract_id: "Kontrakt zachowany",
  deleted_contract_ids: "Kontrakty usunięte",
  deleted_status: "Status usuniętego kontraktu",
  filled_fields: "Uzupełnione pola",
  reparented: "Przepięte powiązania",
  mail_orders_activated: "Aktywowane zamówienia z maila",
  margin: "Marża",
  framework_rate: "Stawka z umowy ramowej",
  billing_hours_per_month: "Godziny / miesiąc",
  target_rate_min: "Widełki docelowe (min)",
  target_rate_max: "Widełki docelowe (max)",
  currency: "Waluta",
  rate_client_currency: "Waluta stawki przychodowej",
  rate_candidate_currency: "Waluta stawki kosztowej",
  order_consumption: "Zużycie zamówienia",
  order_consumption_unit: "Jednostka zużycia",
  handover_notes: "Notatki wewnętrzne",
  client_pm_name: "PM po stronie klienta",
  client_pm_email: "Email PM",
  line_manager: "Line Manager",
  office_location: "Lokalizacja biura",
  project_name: "Projekt",
  team_name: "Zespół",
  notes: "Notatki",
  fields: "Zmienione pola",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Szkic",
  ready_for_signature: "Do podpisu",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
  void: "Anulowany",
};

const RATE_UNIT_LABELS: Record<string, string> = {
  hourly: "godzinowa",
  daily: "dzienna (MD)",
  monthly: "miesięczna",
};

const CONTRACT_TYPE_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  uzlecenie: "Umowa zlecenie",
};

const WORK_MODE_LABELS: Record<string, string> = {
  remote: "Zdalnie",
  hybrid: "Hybrydowo",
  onsite: "Stacjonarnie",
};

const SOURCE_LABELS: Record<string, string> = {
  daily_cost_sync: "dobowa synchronizacja stawek kosztowych zamówień",
  daily_period_backfill: "dobowe uzupełnienie okresu zamówienia",
  b2b_signed_agreement: "podpisana umowa B2B",
};

const ENUM_KEYS: Record<string, Record<string, string>> = {
  status: STATUS_LABELS,
  from_status: STATUS_LABELS,
  to_status: STATUS_LABELS,
  previous_status: STATUS_LABELS,
  deleted_status: STATUS_LABELS,
  rate_unit: RATE_UNIT_LABELS,
  contract_type: CONTRACT_TYPE_LABELS,
  work_mode: WORK_MODE_LABELS,
};

const ID_LIST_KEYS = new Set([
  "synced_orders",
  "order_cost_synced",
  "revenue_steps_changed",
  "deleted_contract_ids",
  "order_drafts_inherited_rates",
  "mail_orders_activated",
]);

const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
// Identyfikator jednorazowej korekty danych („0307_b2b_indefinite_end_date").
const REPAIR_MARKER_RE = /^\d{4}_[a-z0-9_]+$/;

function sourceLabel(value: string): string {
  const known = SOURCE_LABELS[value];
  if (known) return known;
  if (REPAIR_MARKER_RE.test(value)) {
    return `jednorazowa korekta danych (${value.slice(0, 4)})`;
  }
  return SLUG_RE.test(value) ? "operacja systemowa" : value;
}

/** Klucz szczegółów → etykieta PL; nieznany klucz bez podkreśleń. */
export function contractDetailLabel(key: string): string {
  return DETAIL_LABELS[key] ?? key.replace(/_/g, " ");
}

/** Wartość szczegółu → tekst po polsku. */
export function contractDetailValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "tak" : "nie";
  if (typeof value === "number") {
    if (key === "source_order_id" || key === "contract_id" || key === "survivor_contract_id") {
      return `#${value}`;
    }
    return value.toLocaleString("pl-PL");
  }
  if (typeof value === "string") {
    if (key === "source") return sourceLabel(value);
    if (key === "termination_reason") {
      return (
        CONTRACT_TERMINATION_REASONS.find((r) => r.value === value)?.label ?? value
      );
    }
    const enumLabels = ENUM_KEYS[key];
    if (enumLabels && enumLabels[value]) return enumLabels[value];
    if (DATE_ONLY_RE.test(value)) return formatIsoDatePl(value);
    if (DATE_TIME_RE.test(value)) return formatDateTimePl(value);
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    if (ID_LIST_KEYS.has(key) && value.every((v) => typeof v === "number")) {
      return value.map((v) => `#${v}`).join(", ");
    }
    return value
      .map((v) =>
        typeof v === "object" && v !== null
          ? JSON.stringify(v)
          : contractDetailValue(key, v),
      )
      .join(", ");
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    // `rate_unit: {from, to}` z synchronizacji jednostki kontrakt ↔ zamówienie.
    if ("from" in obj && "to" in obj) {
      const from = contractDetailValue(key, obj.from);
      const to = contractDetailValue(key, obj.to);
      return from === "—" ? to : `${from} → ${to}`;
    }
    return JSON.stringify(obj);
  }
  return String(value);
}

export interface ContractDetailRow {
  key: string;
  label: string;
  value: string;
}

/** Szczegóły zdarzenia jako lista „etykieta → wartość" (kolejność z payloadu). */
export function contractActivityDetailRows(
  details: Record<string, unknown> | null | undefined,
): ContractDetailRow[] {
  if (!details) return [];
  return Object.entries(details).map(([key, value]) => ({
    key,
    label: contractDetailLabel(key),
    value: contractDetailValue(key, value),
  }));
}
