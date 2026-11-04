// Karta osoby w sekcji „Zakończone" zamówienia MD/kosztowego (ticket 6, 09.2026).
//
// Zwinięta karta odpowiada na cztery pytania: kto, że zakończył i kiedy, ile
// wykorzystał, czy trzeba podjąć decyzję. Reguły są czystymi funkcjami, żeby
// dało się je sprawdzić bez montowania karty zamówienia.

import { formatMd } from "@/components/client-profile/orders/MdBudgetBar";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import { formatDate, formatPLN } from "@/types/client-profile";

type EndedLine = Pick<
  OrderLineRead,
  | "is_active"
  | "start_date"
  | "end_date"
  | "cooperation_ended_on"
  | "removed_from_order"
  | "replaced_by_order_id"
  | "replaced_by_consultant_name"
  | "replaced_by_scheduled"
  | "replaced_by_start_date"
  | "history_kept_at"
  | "offboarding_case"
  | "contract_type"
  | "agreement_termination_mode"
  | "agreement_last_day"
>;

export type EndedStatus = "cooperation" | "project";

/** Jedyne dwie plakietki zakończenia na kartach zamówień. */
export const ENDED_STATUS_LABEL: Record<EndedStatus, string> = {
  cooperation: "Zakończył współpracę",
  project: "Zakończył projekt",
};

/**
 * „Zakończył współpracę" = umowa rozwiązana (wypowiedzenie albo porozumienie
 * stron); „Zakończył projekt" = koniec pracy na tym zamówieniu, umowa B2B
 * nadal obowiązuje. Umowa o pracę / zlecenie nie ma osobnego rozwiązania —
 * zakończony kontrakt znaczy tam koniec współpracy.
 */
export function endedStatus(line: EndedLine): EndedStatus {
  if (line.agreement_termination_mode) return "cooperation";
  if (
    line.contract_type != null &&
    line.contract_type !== "b2b" &&
    line.cooperation_ended_on
  ) {
    return "cooperation";
  }
  return "project";
}

const TERMINATION_MODE_LABEL: Record<
  NonNullable<OrderLineRead["agreement_termination_mode"]>,
  string
> = {
  notice: "Wypowiedzenie",
  mutual_agreement: "Porozumienie stron",
};

/** Zdanie o umowie w rozwiniętej karcie; `null` = nie wiemy nic o umowie. */
export function agreementSentence(line: EndedLine): string | null {
  if (line.agreement_termination_mode) {
    const mode = TERMINATION_MODE_LABEL[line.agreement_termination_mode];
    return line.agreement_last_day
      ? `Ostatni dzień umowy: ${formatDate(line.agreement_last_day)} · ${mode}`
      : `Umowa rozwiązana · ${mode}`;
  }
  if (line.contract_type == null) return null;
  if (line.contract_type !== "b2b") {
    return line.cooperation_ended_on
      ? `Umowa zakończona ${formatDate(line.cooperation_ended_on)}`
      : "Umowa nadal obowiązuje";
  }
  return "Umowa B2B nadal obowiązuje";
}

/** „01.05.2026 – 31.08.2026" — okres osoby na TYM zamówieniu. */
export function endedPeriod(line: EndedLine): string {
  const end = line.end_date ?? line.cooperation_ended_on ?? null;
  if (!line.start_date) return end ? `do ${formatDate(end)}` : "—";
  return `${formatDate(line.start_date)} – ${end ? formatDate(end) : "…"}`;
}

type UsageLine = Pick<OrderLineRead, "invoiced_total" | "md_used" | "rate_revenue">;

/**
 * „25,45 MD · 25 450,00 zł". Kwota tylko przy stawce z odpowiedzi — rola bez
 * finansów ma `rate_revenue = null` i widzi same MD (operacyjne). Zamówienie
 * kosztowe rozlicza faktury, więc pokazuje zafakturowaną kwotę. `null` = brak
 * danych o zużyciu tej osoby (np. wspólna pula), nie zero.
 */
export function endedUsage(
  group: Pick<OrderGroupRead, "is_cost_based">,
  line: UsageLine,
): string | null {
  if (group.is_cost_based) {
    return line.invoiced_total == null ? null : formatPLN(line.invoiced_total);
  }
  if (line.md_used == null) return null;
  const md = `${formatMd(line.md_used)} MD`;
  if (line.rate_revenue == null) return md;
  const amount = Math.round(line.md_used * line.rate_revenue * 100) / 100;
  return `${md} · ${formatPLN(amount)}`;
}

/** Sprawa offboardingu MD czeka na decyzję (a następca nie jest już zaplanowany). */
export function hasPendingPoolDecision(line: EndedLine): boolean {
  return (
    line.offboarding_case?.status === "pending" && line.replaced_by_scheduled !== true
  );
}

/**
 * Czy karta wymaga decyzji: czekająca sprawa puli MD albo osoba z zakończoną
 * współpracą, o której nikt jeszcze nie zdecydował (nie została zostawiona
 * jako historia, usunięta ani zastąpiona). Niezależne od roli — licznik
 * i kolejność sekcji mają być te same dla każdego.
 */
export function requiresDecision(line: EndedLine): boolean {
  if (line.is_active) return false;
  if (hasPendingPoolDecision(line)) return true;
  return (
    Boolean(line.cooperation_ended_on) &&
    !line.removed_from_order &&
    line.replaced_by_order_id == null &&
    !line.history_kept_at &&
    !line.offboarding_case
  );
}

/** Szary opis podjętej decyzji po prawej stronie karty; `null` = brak decyzji. */
export function decisionLabel(line: EndedLine): string | null {
  if (line.removed_from_order) return "Usunięty z zamówienia";
  if (line.replaced_by_order_id != null) {
    const who = line.replaced_by_consultant_name ?? "następca";
    return line.replaced_by_scheduled
      ? `Zastępstwo: ${who} od ${formatDate(line.replaced_by_start_date ?? null)}`
      : `Zastąpiony przez ${who}`;
  }
  if (line.history_kept_at) return "Zostawiony jako historia";
  const pool = line.offboarding_case;
  if (pool?.status === "resolved") {
    if (pool.resolution === "transfer") return "Pula MD przeniesiona";
    if (pool.resolution_payload?.automatic) return "Pula MD wykorzystana";
    if (pool.resolution === "remove") return "Pula MD zamknięta";
  }
  return null;
}

/** Karty wymagające decyzji na górze; w obrębie grup kolejność bez zmian. */
export function sortEndedLines<T extends EndedLine>(lines: readonly T[]): T[] {
  return [
    ...lines.filter((line) => requiresDecision(line)),
    ...lines.filter((line) => !requiresDecision(line)),
  ];
}
