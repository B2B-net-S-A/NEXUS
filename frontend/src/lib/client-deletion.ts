import api from "@/lib/api";

/** Blokada twarda: otwarte zamówienia, aktywni kontraktorzy, kandydaci
 *  w otwartych rekrutacjach. Pozycje to pierwsze nazwy/numery (reszta jako
 *  „… i N więcej"). */
export interface ClientDeletionBlocker {
  code: string;
  label: string;
  count: number;
  items: string[];
}

export interface ClientDeletionHistoryItem {
  code: string;
  label: string;
  count: number;
}

/**
 * Wynik kliknięcia „Usuń klienta" (POST /deletion-check).
 * - `blocked` — nie można usunąć; próba jest już w Historii zdarzeń,
 * - `purge` — klient pusty, usunięcie trwałe,
 * - `archive` — klient z historią: znika z list, dane historyczne zostają.
 */
export interface ClientDeletionCheck {
  client_id: number;
  client_name: string;
  status: string | null;
  mode: "blocked" | "purge" | "archive";
  can_delete: boolean;
  blockers: ClientDeletionBlocker[];
  history: ClientDeletionHistoryItem[];
  history_sentence: string | null;
  confirmation_phrase: string;
}

export interface ClientDeletionResult {
  client_id: number;
  client_name: string;
  result: "purged" | "archived";
  history: ClientDeletionHistoryItem[];
  history_sentence: string | null;
}

/** Dokładnie to, co trzeba wpisać w oknie potwierdzenia (wymóg ticketu). */
export const CLIENT_DELETION_CONFIRMATION = "0";

export function isConfirmationValid(value: string): boolean {
  return value.trim() === CLIENT_DELETION_CONFIRMATION;
}

export const clientDeletionApi = {
  check: (clientId: number) =>
    api
      .post<ClientDeletionCheck>(`/api/clients/${clientId}/deletion-check`)
      .then((r) => r.data),
  execute: (clientId: number, confirmation: string) =>
    api
      .delete<ClientDeletionResult>(`/api/clients/${clientId}`, {
        params: { confirmation },
      })
      .then((r) => r.data),
};
