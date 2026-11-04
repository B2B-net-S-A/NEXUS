/**
 * Reguły bocznego panelu kontraktu w rejestrze (wersja B, 29.09.2026):
 * która akcja jest główna i jakie ostrzeżenia stoją nad sekcjami. Czyste
 * funkcje — panel tylko je renderuje, testy sprawdzają je bez DOM-u.
 */
import { formatIsoDatePl } from "@/lib/date-pl";
import { b2bExtensionLocked, type ContractEndDateState } from "@/lib/contract-end-date";

export interface ContractPanelFacts extends ContractEndDateState {
  status: string;
  start_date?: string | null;
  end_date?: string | null;
  client_order_start_date?: string | null;
  client_order_end_date?: string | null;
  rate_candidate?: number | null;
  rate_client?: number | null;
  can_reverse_termination?: boolean;
  can_return_after_break?: boolean;
}

export type ContractPanelPrimary =
  | "recover"
  | "complete_draft"
  | "add_order"
  | "open";

const LIVE_STATUSES = new Set(["active", "ending"]);

function addDaysIso(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Zamówienie u klienta skończyło się (koniec przed dziś). */
export function orderEnded(c: ContractPanelFacts, today: string): boolean {
  const end = c.client_order_end_date?.slice(0, 10);
  return Boolean(end && end < today);
}

/**
 * Brak aktywnego zamówienia przy trwającej współpracy: okres zamówienia
 * (z najnowszego uzupełnionego zamówienia — synchronizacja 09.2026) minął
 * albo kontrakt nie ma żadnego uzupełnionego zamówienia.
 */
export function lacksActiveOrder(c: ContractPanelFacts, today: string): boolean {
  if (!LIVE_STATUSES.has(c.status)) return false;
  if (!c.client_order_start_date && !c.client_order_end_date) return true;
  return orderEnded(c, today);
}

/**
 * Najnowsze zamówienie kończy się w ciągu 30 dni — skoro jest najnowsze, nie
 * ma po nim kolejnego.
 */
export function orderEndsWithoutSuccessor(c: ContractPanelFacts, today: string): boolean {
  if (!LIVE_STATUSES.has(c.status)) return false;
  const end = c.client_order_end_date?.slice(0, 10);
  if (!end || end < today) return false;
  return end <= addDaysIso(today, 30);
}

export function contractPanelPrimary(
  c: ContractPanelFacts,
  access: { canRecoverTermination: boolean; canEditContract: boolean },
  today: string,
): ContractPanelPrimary {
  if (c.status === "ended") {
    return access.canRecoverTermination &&
      (c.can_reverse_termination || c.can_return_after_break)
      ? "recover"
      : "open";
  }
  if (c.status === "draft") return access.canEditContract ? "complete_draft" : "open";
  if (lacksActiveOrder(c, today) || orderEndsWithoutSuccessor(c, today)) return "add_order";
  return "open";
}

/**
 * Aneks „Przedłużenie” — NIGDY dla bezterminowej umowy B2B (nie ma czego
 * przedłużać; przedłuża się zamówienie klienta).
 */
export function canOfferExtension(c: ContractPanelFacts): boolean {
  if (c.status === "ended" || c.status === "void") return false;
  return !b2bExtensionLocked(c);
}

export interface ContractPanelAlert {
  tone: "warning" | "danger" | "info";
  text: string;
}

const ACTIVATION_FIELD_LABEL: Record<string, string> = {
  start_date: "data rozpoczęcia",
  rate_candidate: "stawka kosztowa",
  rate_client: "stawka przychodowa",
};

export function contractPanelAlerts(
  c: ContractPanelFacts,
  today: string,
  canViewFinance: boolean,
): ContractPanelAlert[] {
  const alerts: ContractPanelAlert[] = [];
  if (c.status === "ended") {
    const end = c.end_date ?? c.terminated_at ?? null;
    alerts.push({
      tone: "info",
      text: end
        ? `Kontrakt zakończony ${formatIsoDatePl(end.slice(0, 10))}.`
        : "Kontrakt zakończony.",
    });
    return alerts;
  }
  if (c.status === "draft") {
    // Lustro `ACTIVATION_REQUIRED_FIELDS` (backend) — stawki tylko, gdy je widać:
    // zredagowane `null` nie jest brakiem.
    const missing = [
      !c.start_date && "start_date",
      canViewFinance && c.rate_candidate == null && "rate_candidate",
      canViewFinance && c.rate_client == null && "rate_client",
    ].filter(Boolean) as string[];
    alerts.push({
      tone: "warning",
      text: missing.length
        ? `Draft — brakuje: ${missing.map((f) => ACTIVATION_FIELD_LABEL[f]).join(", ")}.`
        : "Draft — uzupełnij i aktywuj, żeby kontrakt zaczął obowiązywać.",
    });
    return alerts;
  }
  if (c.status === "ending" && c.end_date) {
    alerts.push({
      tone: "warning",
      text: `Zaplanowane zakończenie współpracy: ${formatIsoDatePl(c.end_date.slice(0, 10))}.`,
    });
  }
  if (lacksActiveOrder(c, today)) {
    alerts.push({
      tone: "danger",
      text: orderEnded(c, today)
        ? `Brak aktywnego zamówienia — ostatnie skończyło się ${formatIsoDatePl(
            (c.client_order_end_date ?? "").slice(0, 10),
          )}.`
        : "Brak aktywnego zamówienia u klienta.",
    });
  } else if (orderEndsWithoutSuccessor(c, today)) {
    alerts.push({
      tone: "warning",
      text: `Zamówienie kończy się ${formatIsoDatePl(
        (c.client_order_end_date ?? "").slice(0, 10),
      )} i nie ma kolejnego.`,
    });
  }
  return alerts;
}
