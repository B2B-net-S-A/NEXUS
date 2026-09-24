/**
 * Jeden słownik etykiet statusów kontraktu, zamówienia i zamówienia MD/kosztowego.
 *
 * Do 24.09.2026 te same statusy miały 7+ osobnych słowników, które się
 * rozjechały: szkic był „Draft”, „Szkic” i „Do uzupełnienia”, a szczegóły
 * kontraktu nie znały „Do podpisu” ani „Anulowany” (surowy kod na plakietce).
 * Nowy ekran pokazujący status bierze etykietę i wariant stąd.
 *
 * Nieznany status zwraca sam siebie — lepiej pokazać kod niż pustkę.
 */

export type StatusVariant = "neutral" | "soft" | "success" | "warning" | "danger";

export const CONTRACT_STATUS_LABELS: Record<string, string> = {
  draft: "Szkic",
  ready_for_signature: "Do podpisu",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
  void: "Anulowany",
};

export const CONTRACT_STATUS_VARIANTS: Record<string, StatusVariant> = {
  draft: "soft",
  ready_for_signature: "soft",
  active: "success",
  ending: "warning",
  ended: "neutral",
  void: "danger",
};

/** Zamówienie okresowe i linia zamówienia MD/kosztowego (`client_orders.status`). */
export const ORDER_STATUS_LABELS: Record<string, string> = {
  draft: "Szkic",
  active: "Aktywne",
  paused: "Wstrzymane",
  completed: "Zakończone",
  cancelled: "Anulowane",
  scheduled: "Zaplanowane",
};

export const ORDER_STATUS_VARIANTS: Record<string, StatusVariant> = {
  draft: "soft",
  active: "success",
  paused: "warning",
  completed: "neutral",
  cancelled: "danger",
  scheduled: "soft",
};

/** Zamówienie MD / kosztowe jako całość (`client_order_groups.status`). */
export const ORDER_GROUP_STATUS_LABELS: Record<string, string> = {
  draft: "Szkic",
  scheduled: "Zaplanowane",
  active: "Aktywne",
  exhausted: "Wyczerpane",
  completed: "Zakończone",
  cancelled: "Anulowane",
};

export const ORDER_GROUP_STATUS_VARIANTS: Record<string, StatusVariant> = {
  draft: "soft",
  scheduled: "soft",
  active: "success",
  exhausted: "warning",
  completed: "neutral",
  cancelled: "danger",
};

function pick(map: Record<string, string>, status: string | null | undefined): string {
  if (!status) return "—";
  return map[status] ?? status;
}

export function contractStatusLabel(status: string | null | undefined): string {
  return pick(CONTRACT_STATUS_LABELS, status);
}

export function orderStatusLabel(status: string | null | undefined): string {
  return pick(ORDER_STATUS_LABELS, status);
}

export function orderGroupStatusLabel(status: string | null | undefined): string {
  return pick(ORDER_GROUP_STATUS_LABELS, status);
}

export function contractStatusVariant(status: string | null | undefined): StatusVariant {
  return (status && CONTRACT_STATUS_VARIANTS[status]) || "neutral";
}

export function orderStatusVariant(status: string | null | undefined): StatusVariant {
  return (status && ORDER_STATUS_VARIANTS[status]) || "neutral";
}

export function orderGroupStatusVariant(status: string | null | undefined): StatusVariant {
  return (status && ORDER_GROUP_STATUS_VARIANTS[status]) || "neutral";
}
