/**
 * Status requestu (0341) — liczy serwer (`job_similarity.request_status_expr`),
 * front tylko nazywa. „Szukamy" trwa, dopóki Delivery Lead nie wskaże
 * championów na tyle miejsc, ile ma rekrutacja (decyzje Artura 22.09
 * i 15.10.2026, `lib/job-champions.ts`).
 */

export type RequestStatus =
  | "closed"
  | "filled"
  | "contract"
  | "champion"
  | "incomplete"
  | "on_hold"
  | "searching";

/** `hold` — „Wstrzymana” (26.11.2026): ostrzegawcze paski z ikoną pauzy. */
export type RequestStatusTone = "search" | "client" | "need" | "done" | "hold";

export const REQUEST_STATUS_META: Record<
  RequestStatus,
  { label: string; tone: RequestStatusTone; hint: string }
> = {
  searching: { label: "Szukamy", tone: "search", hint: "Szukamy kandydatów." },
  champion: {
    label: "Mamy championa",
    tone: "client",
    hint: "Delivery Lead wskazał championów — dalej nie szukamy.",
  },
  contract: { label: "Umowa", tone: "client", hint: "Ktoś jest na etapie umowy." },
  filled: { label: "Obsadzona", tone: "done", hint: "Komplet zatrudnionych." },
  incomplete: {
    label: "Do uzupełnienia",
    tone: "need",
    hint: "Zlecenie jest szkicem — nieprzekazane do searchu.",
  },
  closed: { label: "Zamknięta", tone: "done", hint: "Rekrutacja zamknięta." },
  on_hold: {
    label: "Wstrzymana",
    tone: "hold",
    hint: "Klient wstrzymał rekrutację — nie proponuj tego projektu kandydatom.",
  },
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

/** Kto wskazuje championów rekrutacji — lustro `_CHAMPION_ROLES` w backendzie. */
export const CHAMPION_ROLES = ["admin", "delivery_lead", "head_of_recruitment"] as const;
