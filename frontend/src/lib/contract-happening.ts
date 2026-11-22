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
  | "fill_rate"
  | "extend_agreement"
  | "reassign_order"
  | "cancel_order_draft";

/**
 * Zamówienie złożone na okres po końcu współpracy (`order_after_end`
 * z `GET /api/contracts/{id}`, decyzja Artura 19.11.2026).
 */
export interface HappeningOrderAfterEnd {
  order_id: number;
  client_id: number;
  order_group_id: number | null;
  order_number: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
  /** Szkic, którego wypowiedzenie nie pozwala aktywować (automat poczty). */
  held_by_termination: boolean;
}

/**
 * Wypowiedzenie albo porozumienie z Dokumentów kontraktu (`termination_document`
 * z API, 22.11.2026). Tylko wskazówka: pól rozwiązania z pliku nie wypełniamy,
 * bo ostatni dzień umowy przesuwa okres wypowiedzenia i zakaz konkurencji.
 */
export interface TerminationDocumentRef {
  id: number;
  doc_type: "termination_notice" | "termination_agreement";
  filename: string;
  content_type?: string | null;
  source?: string | null;
  created_at: string;
}

/** „Wypowiedzenie” / „Porozumienie” — rodzaj dokumentu w zdaniu. */
export function terminationDocKind(doc: Pick<TerminationDocumentRef, "doc_type">): string {
  return doc.doc_type === "termination_notice" ? "wypowiedzenie" : "porozumienie";
}

/** „„plik.pdf”, dodane 29.09.2026 z SharePointa” — skąd i kiedy plik. */
export function terminationDocWhere(doc: TerminationDocumentRef): string {
  const fromSharePoint = doc.source === "sharepoint" || doc.source === "sharepoint_import";
  return `„${doc.filename}”, dodane ${fmtDatePl(doc.created_at)}${fromSharePoint ? " z SharePointa" : ""}`;
}

const RECORD_FROM_DOC =
  "Zapisz rozwiązanie z ostatnim dniem umowy z dokumentu — NEXUS nie odczytuje go z pliku, bo od tej daty liczy się okres wypowiedzenia i zakaz konkurencji.";

export interface HappeningItem {
  id: "end" | "order_end" | "care" | "rate" | "order_after_end";
  /** Klucz wiersza: kilka zamówień po końcu to kilka pozycji tego samego rodzaju. */
  key?: string;
  tone: HappeningTone;
  lead: string;
  detail: string | null;
  actions: HappeningActionId[];
  /** Zamówienie, którego dotyczą akcje pozycji `order_after_end`. */
  order?: HappeningOrderAfterEnd;
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
  order_after_end?: HappeningOrderAfterEnd[] | null;
  /** Wypowiedzenie/porozumienie w Dokumentach umowy bez zapisanego rozwiązania. */
  termination_document?: TerminationDocumentRef | null;
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

/** Umowy z datą końca w treści — zamówienie ich nie przedłuża (nie-B2B). */
const AGREEMENT_LABEL: Record<string, string> = {
  uzlecenie: "Umowa zlecenie",
  uop: "Umowa o pracę",
};

function orderPeriod(order: HappeningOrderAfterEnd): string {
  if (!order.start_date) return "bez dat";
  if (!order.end_date) return `od ${fmtDatePl(order.start_date)} bez daty końca`;
  return `${fmtDatePl(order.start_date)} – ${fmtDatePl(order.end_date)}`;
}

/**
 * „Klient zamówił okres po zakończeniu” — jedna pozycja na zamówienie.
 * Konflikt liczy serwer (`services/contract_order_after_end.py`); tu tylko
 * zdanie i wyjścia: przedłużenie umowy albo cofnięcie zakończenia, zamówienie
 * dla innej osoby, anulowanie szkicu.
 */
function orderAfterEndItems(c: HappeningContract): HappeningItem[] {
  const projectEnd = c.end_date ?? c.terminated_at;
  if ((c.status !== "ending" && c.status !== "ended") || !projectEnd) return [];
  const agreement = AGREEMENT_LABEL[c.contract_type] ?? null;
  return (c.order_after_end ?? []).map((order) => {
    const draft = order.status === "draft";
    const line = order.order_group_id != null;
    const what = line ? "Linia zamówienia zbiorczego" : draft ? "Szkic zamówienia" : "Zamówienie";
    const number = order.order_number ? ` ${order.order_number}` : "";
    const when = c.status === "ended" ? "zakończyła się" : "kończy się";
    const detail = [
      `${what}${number}: ${orderPeriod(order)}, a współpraca ${when} ${fmtDatePl(projectEnd)}.`,
      order.held_by_termination
        ? "NEXUS nie aktywuje go sam, bo zakończenie współpracy to decyzja człowieka."
        : null,
      agreement
        ? `${agreement} nie przedłuża się zamówieniem — przedłuż ją aneksem albo załóż nowy kontrakt.`
        : null,
    ]
      .filter(Boolean)
      .join(" ");
    const actions: HappeningActionId[] = [];
    if (agreement) actions.push("extend_agreement");
    else if (c.can_reverse_termination) actions.push("reverse_termination");
    actions.push("reassign_order");
    if (draft && !line) actions.push("cancel_order_draft");
    return {
      id: "order_after_end",
      key: `order_after_end:${order.order_id}`,
      tone: "danger",
      lead: "Klient zamówił okres po zakończeniu współpracy",
      detail,
      actions,
      order,
    };
  });
}

function reasonLabel(value: string | null): string | null {
  if (!value) return null;
  return CONTRACT_TERMINATION_REASONS.find((r) => r.value === value)?.label ?? value;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export interface HappeningOptions {
  /**
   * Czy osoba widzi kwoty (`canViewFinance`). Bez tego serwer zeruje stawki
   * (`_redact_contract_finance`), więc „brak stawki klienta” byłby fałszywy.
   */
  canSeeRates: boolean;
}

export function buildContractHappening(
  c: HappeningContract,
  care: HappeningCare | null,
  today: string,
  options: HappeningOptions = { canSeeRates: false },
): HappeningItem[] {
  const items: HappeningItem[] = [];
  const afterEnd = orderAfterEndItems(c);
  const agreementOpen = c.contract_type === "b2b" && !c.agreement_termination_mode;
  const live = c.status === "active" || c.status === "ending";
  // Dokument w aktach przy niezapisanym rozwiązaniu: umowa najpewniej jest
  // rozwiązana, brakuje tylko wpisu — inne zdanie niż „nie jest rozwiązana”.
  const doc = agreementOpen ? (c.termination_document ?? null) : null;

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
      doc
        ? `${capitalize(terminationDocKind(doc))} umowy B2B jest w Dokumentach (${terminationDocWhere(doc)}), ale rozwiązanie nie jest zapisane.`
        : agreementOpen
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
        // Przy zamówieniu po końcu „Cofnij zakończenie” stoi w jego pozycji.
        ...(c.can_reverse_termination && afterEnd.length === 0
          ? (["reverse_termination"] as const)
          : []),
      ],
    });
  } else if (c.status === "ended" && doc) {
    items.push({
      id: "end",
      tone: "info",
      lead: `Współpraca zakończona${c.end_date ? ` ${fmtDatePl(c.end_date)}` : ""} — ${terminationDocKind(doc)} umowy B2B jest w Dokumentach, rozwiązanie niezapisane`,
      detail: `${capitalize(terminationDocWhere(doc))}. ${RECORD_FROM_DOC}`,
      actions: ["record_agreement"],
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

  items.push(...afterEnd);

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

  if (options.canSeeRates && live && c.rate_client == null) {
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
