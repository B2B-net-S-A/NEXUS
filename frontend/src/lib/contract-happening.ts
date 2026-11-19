// „Co się dzieje” na stronie kontraktu (przebudowa 19.11.2026, wariant A).
//
// Jedno miejsce pod nagłówkiem zbiera to, co dotąd leżało w trzech: dwa
// ostrzeżenia w panelu listy, czerwona karta zakończenia na dole „Szczegółów”
// (ok. 1000 px niżej przy 1280 × 720) i powody „Uwaga” w 7. zakładce „Opieka”.
// Funkcja jest czysta: akcje to identyfikatory, a strona decyduje, czy osoba
// ma do nich uprawnienie i co dokładnie otwierają.
import { CONTRACT_TERMINATION_REASONS } from "@/lib/api";

export type HappeningTone = "danger" | "warning" | "info";

export type HappeningActionId =
  | "record_agreement"
  | "reverse_termination"
  | "add_order"
  | "terminate"
  | "log_conversation"
  | "fill_rate";

export interface HappeningItem {
  id: "end" | "order_end" | "care" | "rate";
  tone: HappeningTone;
  lead: string;
  detail: string | null;
  actions: HappeningActionId[];
}

export interface HappeningContract {
  status: string;
  contract_type: string;
  end_date: string | null;
  terminated_at: string | null;
  termination_reason: string | null;
  termination_lessons: string | null;
  agreement_termination_mode: string | null;
  client_order_end_date: string | null;
  prolongation_status: string | null;
  rate_client: number | null;
  can_reverse_termination?: boolean | null;
}

export interface HappeningCare {
  level: "ok" | "watch" | "risk";
  reasons: string[];
  ownerName: string | null;
}

/** Zamówienie bliżej niż tyle dni trafia na górę strony. */
export const ORDER_END_HORIZON_DAYS = 60;
/** Do tylu dni do końca pas jest czerwony. */
export const URGENT_DAYS = 14;

const PROLONGATION_SENTENCE: Record<string, string> = {
  yes: "klient przedłuża",
  no: "klient nie przedłuża",
  negotiate: "przedłużenie w negocjacjach",
  unknown: "brak decyzji o przedłużeniu",
};

function dayDiff(fromIso: string, toIso: string): number {
  const a = Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`);
  return Math.round((b - a) / 86_400_000);
}

export function fmtDatePl(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** „za 11 dni”, „za 1 dzień”, „dziś”, „jutro”. */
export function relativeDays(days: number): string {
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  if (days < 0) return days === -1 ? "wczoraj" : `${-days} dni temu`;
  return `za ${days} dni`;
}

function reasonLabel(value: string | null): string | null {
  if (!value) return null;
  return CONTRACT_TERMINATION_REASONS.find((r) => r.value === value)?.label ?? value;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function buildContractHappening(
  c: HappeningContract,
  care: HappeningCare | null,
  today: string,
): HappeningItem[] {
  const items: HappeningItem[] = [];
  const agreementOpen = c.contract_type === "b2b" && !c.agreement_termination_mode;
  const live = c.status === "active" || c.status === "ending";

  // Zakończenie zaplanowane (data w przyszłości albo dziś) albo już zakończona
  // współpraca z nierozwiązaną umową B2B.
  const plannedEnd = c.terminated_at && c.end_date && live ? c.end_date : null;
  if (plannedEnd && dayDiff(today, plannedEnd) >= 0) {
    const days = dayDiff(today, plannedEnd);
    const reason = reasonLabel(c.termination_reason);
    const detail = [
      reason
        ? `Powód: ${reason.toLowerCase()}${c.termination_lessons ? ` („${c.termination_lessons.trim()}”)` : ""}.`
        : null,
      agreementOpen
        ? "Umowa B2B nie jest rozwiązana — zostaw ją tylko, jeśli osoba wraca na inny projekt."
        : null,
    ]
      .filter(Boolean)
      .join(" ");
    items.push({
      id: "end",
      tone: days <= URGENT_DAYS ? "danger" : "warning",
      lead: `Współpraca kończy się ${fmtDatePl(plannedEnd)} — ${relativeDays(days)}`,
      detail: detail || null,
      actions: [
        ...(agreementOpen ? (["record_agreement"] as const) : []),
        ...(c.can_reverse_termination ? (["reverse_termination"] as const) : []),
      ],
    });
  } else if (c.status === "ended" && agreementOpen) {
    items.push({
      id: "end",
      tone: "warning",
      lead: `Współpraca zakończona${c.end_date ? ` ${fmtDatePl(c.end_date)}` : ""} — umowa B2B nie jest rozwiązana`,
      detail: "Zostaw ją tylko, jeśli osoba wraca na inny projekt.",
      actions: ["record_agreement"],
    });
  } else if (live && c.client_order_end_date) {
    const days = dayDiff(today, c.client_order_end_date);
    if (days >= 0 && days <= ORDER_END_HORIZON_DAYS) {
      items.push({
        id: "order_end",
        tone: days <= URGENT_DAYS ? "danger" : "warning",
        lead: `Zamówienie kończy się ${fmtDatePl(c.client_order_end_date)} — ${relativeDays(days)}`,
        detail: `${capitalize(PROLONGATION_SENTENCE[c.prolongation_status ?? "unknown"] ?? PROLONGATION_SENTENCE.unknown)}.`,
        actions: ["add_order", "terminate"],
      });
    }
  }

  if (care && care.level !== "ok" && care.reasons.length > 0) {
    // Koniec zamówienia stoi już wyżej — nie powtarzamy go w powodach opieki.
    const reasons = items.length
      ? care.reasons.filter((r) => !/zamówienie kończy/i.test(r))
      : care.reasons;
    if (reasons.length > 0) {
      const [first, ...rest] = reasons;
      items.push({
        id: "care",
        tone: care.level === "risk" ? "danger" : "warning",
        lead: `Opieka: ${first}`,
        detail:
          [rest.map(capitalize).join(" · "), care.ownerName ? `Opiekun: ${care.ownerName}` : ""]
            .filter(Boolean)
            .join(" · ") || null,
        actions: ["log_conversation"],
      });
    }
  }

  if (live && c.rate_client == null) {
    items.push({
      id: "rate",
      tone: "info",
      lead: "Brak stawki klienta",
      detail: "Przychód i marża tego kontraktu nie liczą się w sumach, dopóki stawka nie zostanie wpisana.",
      actions: ["fill_rate"],
    });
  }
  return items;
}
