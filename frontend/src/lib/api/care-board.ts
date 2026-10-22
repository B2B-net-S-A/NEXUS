// Opieka · tablica „Do zrobienia” (22.10.2026) — karty opieki na wspólnej
// tablicy ze sprawami (`components/work-board/`).
//
// Lustro `backend/app/api/care_board.py` (prefiks `/api/care`). Karty liczy
// serwer przy odczycie (odczyt nic nie zapisuje): rozmowy z terminem do piątku
// i po terminie, prośby o opinię menedżera (D11), aktywne decyzje „Do
// przepięcia” i — u Delivery Leada klienta — popyt do sprawdzenia. Stan karty
// na tablicy (umówiona, nie odbiera, notatka) zapisuje `PUT /board/state`;
// kolumna „Nowa” kasuje wiersz stanu. Bez stawek i bez danych o zdrowiu.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

/** Zdrowie relacji (krąg D11); poza nim serwer daje `null` i etykiety nie ma. */
export type CareHealthLevel = "ok" | "watch" | "risk";

export interface CareHealth {
  level: CareHealthLevel;
  label: string;
  /** Zdania „dlaczego”, np. „zamówienie kończy się za 32 dni”. */
  reasons: string[];
}

/** `data` — „Dane do uzupełnienia” u klienta (propozycje menedżera, luki mapy); nie przesuwa się. */
export type CareBoardKind = "contact" | "feedback" | "decision" | "demand" | "data";
/** Kolumny kart opieki; „Zrobione” nie jest stanem — zamyka je zapis rozmowy albo opinii. */
export type CareBoardColumn = "new" | "in_progress" | "waiting";
export type CareBoardScope = "mine" | "all";

export interface CareBoardCard {
  /**
   * `contact:plan:<id>` · `contact:followup:<conv_id>` · `feedback:<contact_id>` ·
   * `decision:<redeploy_id>` · `decision:end:<contract_id>` (koniec zamówienia ≤ 60 dni
   * bez wpisu — pierwszy ruch go zakłada) · `demand:<client>:<conv>` · `data:<client_id>`.
   */
  key: string;
  kind: CareBoardKind;
  column: CareBoardColumn;
  title: string;
  subtitle: string | null;
  reason_label: string | null;
  /** Rodzaj powodu: punkt planu (`day_7`, `cadence`, `pre_end`, `follow_up`…) albo powód decyzji (`wants_change`…). */
  reason_kind?: string | null;
  /** Dział menedżera albo rola z kontraktu („QA”); przy opinii — stanowisko menedżera. */
  role_label?: string | null;
  due_on: string | null;
  overdue_days: number;
  scheduled_at: string | null;
  retry_on: string | null;
  note_excerpt: string | null;
  /** Data rozmowy, z której jest cytat. */
  note_on?: string | null;
  /** Koniec zamówienia (rozmowa, decyzja). */
  end_on?: string | null;
  /** Notatka z przeniesienia karty („W toku” / „Czeka na kogoś”) — `care_board_states.note`. */
  state_note?: string | null;
  contract_id?: number | null;
  candidate_id?: number | null;
  client_id: number | null;
  client_name: string | null;
  /** `feedback_due_on` — prośba o opinię tego menedżera czeka od (krąg D11). */
  manager?: { contact_id: number; name: string; feedback_due_on?: string | null } | null;
  owner_user_id: number | null;
  owner_name: string | null;
  health: CareHealth | null;
  last_satisfaction?: number | null;
  consultants?: { contract_id: number; name: string }[];
  /** Opinia menedżera: ostatnia rozmowa z nim i średnia ocen. */
  last_feedback?: { held_on: string; average: number | null } | null;
  /** „Dane do uzupełnienia”: pewne / niepewne propozycje menedżera, luki mapy (`null` = nie liczone). */
  data?: { certain: number; uncertain: number; gaps: number | null; consultants: number } | null;
  demand?: {
    roles: string[];
    source: string | null;
    area: { id: number; name: string } | null;
    conversation_id: number | null;
    /** Menedżer działu (menedżer konsultanta ze źródła); brak = „Uzupełnij menedżera”. */
    manager?: { contact_id: number; name: string } | null;
    open_job?: { id: number; title: string } | null;
  } | null;
}

export interface CareBoardDone {
  this_week: number;
  recent: { key: string; kind: CareBoardKind; title: string; done_on: string }[];
}

export interface CareBoard {
  today: string;
  week_end: string;
  cards: CareBoardCard[];
  done: CareBoardDone;
  /** „Ten tydzień: X z Y zapisane” — punkty planu z terminem pon–pt (bez pominiętych). */
  week_progress?: { done: number; total: number };
}

export interface CareBoardStateInput {
  key: string;
  column: CareBoardColumn;
  /** Wymagane dla rozmowy i opinii w „W toku” (umówiony termin). */
  scheduled_at?: string | null;
  /** Wymagane w „Czeka na kogoś” — dzień ponownej próby. */
  retry_on?: string | null;
  note?: string | null;
}

export const HEALTH_LABELS: Record<CareHealthLevel, string> = {
  ok: "Dobrze",
  watch: "Uwaga",
  risk: "Ryzyko",
};

/** Kropka zdrowia — tokeny, nie kolory na sztywno. */
export const HEALTH_DOT: Record<CareHealthLevel, string> = {
  ok: "bg-success",
  watch: "bg-warning",
  risk: "bg-destructive",
};

/** Zdrowie słowem — kolor tekstu. */
export const HEALTH_TEXT: Record<CareHealthLevel, string> = {
  ok: "text-success",
  watch: "text-warning-muted-foreground",
  risk: "text-destructive",
};

export const CARE_KIND_LABELS: Record<CareBoardKind, string> = {
  contact: "rozmowa",
  feedback: "opinia menedżera",
  decision: "decyzja",
  demand: "popyt",
  data: "dane",
};

export const careBoardKeys = {
  all: ["care", "board"] as const,
  board: (scope: CareBoardScope) => ["care", "board", scope] as const,
  /** Klucz tej samej trasy co Karta konsultanta F2 — dane są te same. */
  contractCard: (contractId: number) => ["care", "contract", contractId, "card"] as const,
};

export function useCareBoard(scope: CareBoardScope, enabled = true) {
  return useQuery({
    queryKey: careBoardKeys.board(scope),
    queryFn: async () =>
      (await api.get<CareBoard>("/api/care/board", { params: { scope } })).data,
    enabled,
  });
}

/**
 * Przesunięcie karty opieki na tablicy. Zapis zmienia też listy opieki
 * (decyzja w „W toku” = wpis „Do przepięcia” w toku), więc odświeża cały
 * prefiks `care`.
 */
export function useSetCareBoardState() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: CareBoardStateInput) =>
      (await api.put<unknown>("/api/care/board/state", input)).data,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["care"] }),
  });
}
