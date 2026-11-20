/**
 * Reguły bocznego panelu kontraktu w rejestrze (wariant A, 20.11.2026): jedno
 * ostrzeżenie na górze zamiast kilku o tym samym, z akcją do zrobienia. Czyste
 * funkcje — panel tylko je renderuje, testy sprawdzają je bez DOM-u.
 *
 * Sprawy z paska „Co się dzieje” strony kontraktu (`buildContractHappening`)
 * idą bez zmian; panel dokłada to, co widać tylko z listy: szkic do
 * uzupełnienia, zakończony kontrakt z przywróceniem i brak aktywnego zamówienia.
 */
import { formatIsoDatePl } from "@/lib/date-pl";
import {
  buildContractHappening,
  relativeDays,
  URGENT_DAYS,
  type HappeningActionId,
  type HappeningCare,
  type HappeningContract,
  type HappeningItem,
} from "@/lib/contract-happening";
import type { ContractEndDateState } from "@/lib/contract-end-date";

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

const LIVE_STATUSES = new Set(["active", "ending"]);

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

/** Akcje ostrzeżenia: te z paska strony i dwie, które ma tylko panel. */
export type PanelActionId = HappeningActionId | "complete_draft" | "recover";

export interface PanelWarning {
  id: HappeningItem["id"] | "draft" | "ended" | "no_order" | "contract_end";
  /** Kilka zamówień po końcu to kilka spraw tego samego rodzaju. */
  key?: string;
  tone: "danger" | "warning" | "info";
  lead: string;
  detail: string | null;
  actions: PanelActionId[];
}

const ACTIVATION_FIELD_LABEL: Record<string, string> = {
  start_date: "data rozpoczęcia",
  rate_candidate: "stawka kosztowa",
  rate_client: "stawka przychodowa",
};

function dayDiff(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

export type PanelContract = ContractPanelFacts &
  Partial<
    Pick<
      HappeningContract,
      "termination_lessons" | "agreement_termination_mode" | "prolongation_status" | "order_after_end"
    >
  > & {
    contract_type: string;
  };

/**
 * Sprawy panelu w kolejności pilności. Pierwsza stoi w ramce z akcją, reszta
 * jednym zdaniem pod nią („Także: …”).
 */
export function contractPanelWarnings(
  c: PanelContract,
  care: HappeningCare | null,
  today: string,
  options: { canViewFinance: boolean },
): PanelWarning[] {
  if (c.status === "draft") {
    // Lustro `ACTIVATION_REQUIRED_FIELDS` (backend) — stawki tylko, gdy je widać:
    // zredagowane `null` nie jest brakiem.
    const missing = [
      !c.start_date && "start_date",
      options.canViewFinance && c.rate_candidate == null && "rate_candidate",
      options.canViewFinance && c.rate_client == null && "rate_client",
    ].filter(Boolean) as string[];
    return [
      {
        id: "draft",
        tone: "warning",
        lead: missing.length
          ? `Szkic — brakuje: ${missing.map((f) => ACTIVATION_FIELD_LABEL[f]).join(", ")}`
          : "Szkic — uzupełnij i aktywuj, żeby kontrakt zaczął obowiązywać",
        detail: null,
        actions: ["complete_draft"],
      },
    ];
  }

  const happening = buildContractHappening(
    {
      status: c.status,
      contract_type: c.contract_type,
      end_date: c.end_date ?? null,
      terminated_at: c.terminated_at ?? null,
      termination_reason: c.termination_reason ?? null,
      termination_lessons: c.termination_lessons ?? null,
      agreement_termination_mode: c.agreement_termination_mode ?? null,
      client_order_end_date: c.client_order_end_date ?? null,
      prolongation_status: c.prolongation_status ?? null,
      rate_client: c.rate_client ?? null,
      can_reverse_termination: c.can_reverse_termination ?? false,
      order_after_end: c.order_after_end ?? [],
    },
    care,
    today,
    { canSeeRates: options.canViewFinance },
  );
  const items: PanelWarning[] = happening.map((item) => ({
    id: item.id,
    key: item.key,
    tone: item.tone,
    lead: item.lead,
    detail: item.detail,
    actions: [...item.actions],
  }));

  if (c.status === "ended") {
    const end = c.end_date ?? c.terminated_at ?? null;
    const endItem = items.find((item) => item.id === "end");
    if (endItem) {
      endItem.actions = [...endItem.actions.filter((a) => a !== "reverse_termination"), "recover"];
    } else {
      items.unshift({
        id: "ended",
        tone: "info",
        lead: end ? `Kontrakt zakończony ${formatIsoDatePl(end.slice(0, 10))}` : "Kontrakt zakończony",
        detail: null,
        actions: ["recover"],
      });
    }
    return items;
  }

  // Koniec umowy z datą (np. umowa zlecenie w 30 dni), bez zapisanego
  // zakończenia współpracy — pasek go nie liczy, a panel mówił o nim zawsze.
  const end = c.end_date?.slice(0, 10);
  if (c.status === "ending" && end && !items.some((item) => item.id === "end") && dayDiff(today, end) >= 0) {
    const days = dayDiff(today, end);
    items.unshift({
      id: "contract_end",
      tone: days <= URGENT_DAYS ? "danger" : "warning",
      lead: `Umowa kończy się ${formatIsoDatePl(end)} — ${relativeDays(days)}`,
      detail: null,
      actions: ["terminate"],
    });
  }

  if (lacksActiveOrder(c, today) && !items.some((item) => item.id === "order_end")) {
    const ended = orderEnded(c, today);
    const at = items.findIndex((item) => item.id !== "end" && item.id !== "contract_end");
    items.splice(at === -1 ? items.length : at, 0, {
      id: "no_order",
      tone: "danger",
      lead: "Brak aktywnego zamówienia",
      detail: ended
        ? `Ostatnie zamówienie skończyło się ${formatIsoDatePl((c.client_order_end_date ?? "").slice(0, 10))}.`
        : "Kontrakt nie ma uzupełnionego zamówienia u klienta.",
      actions: ["add_order"],
    });
  }
  return items;
}
