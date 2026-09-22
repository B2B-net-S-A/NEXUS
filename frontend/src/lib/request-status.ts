/**
 * Status requestu (0341) — liczy serwer (`job_similarity.request_status_expr`),
 * front tylko nazywa. „Szukamy" trwa, dopóki Delivery Lead nie oznaczy
 * „Mamy championa" (decyzja Artura 22.09.2026).
 */

export type RequestStatus =
  | "closed"
  | "filled"
  | "contract"
  | "champion"
  | "incomplete"
  | "searching";

export type RequestStatusTone = "search" | "client" | "need" | "done";

export const REQUEST_STATUS_META: Record<
  RequestStatus,
  { label: string; tone: RequestStatusTone; hint: string }
> = {
  searching: { label: "Szukamy", tone: "search", hint: "Szukamy kandydatów." },
  champion: {
    label: "Mamy championa",
    tone: "client",
    hint: "Delivery Lead ma kandydata — dalej nie szukamy.",
  },
  contract: { label: "Umowa", tone: "client", hint: "Ktoś jest na etapie umowy." },
  filled: { label: "Obsadzona", tone: "done", hint: "Komplet zatrudnionych." },
  incomplete: {
    label: "Do uzupełnienia",
    tone: "need",
    hint: "Zlecenie jest szkicem — nieprzekazane do searchu.",
  },
  closed: { label: "Zamknięta", tone: "done", hint: "Rekrutacja zamknięta." },
};

/** Kolejność w filtrze „Status" (zamknięte mają własną zakładkę). */
export const REQUEST_STATUS_FILTER_ORDER: RequestStatus[] = [
  "searching",
  "champion",
  "contract",
  "filled",
  "incomplete",
];

export function requestStatusOf(raw: unknown): RequestStatus | null {
  return typeof raw === "string" && raw in REQUEST_STATUS_META
    ? (raw as RequestStatus)
    : null;
}

/** Kto może oznaczyć „Mamy championa" — lustro `_CHAMPION_ROLES` w backendzie. */
export const CHAMPION_ROLES = ["admin", "delivery_lead", "head_of_recruitment"] as const;
