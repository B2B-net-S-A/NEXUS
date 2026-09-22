/**
 * Identyfikator jednej operacji zapisu nadawany przy otwarciu formularza
 * (np. okna wysyłki maila) i powtarzany przy każdym ponowieniu. Serwer
 * rozpoznaje po nim ponowienie i nie wykonuje skutku drugi raz (INT-04/05).
 *
 * Format zgodny z walidacją backendu: `[A-Za-z0-9-]{8,64}`.
 */
export function newClientRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Kontekst bez `crypto.randomUUID` (http poza localhostem) — wystarczy
  // unikalność w obrębie jednego użytkownika.
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
