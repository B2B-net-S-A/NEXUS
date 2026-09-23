/**
 * Stan nieudanego otwarcia publicznego linku (karta Championa, podpis umowy).
 *
 * Odpowiedź 4xx = link nieprawidłowy, odwołany, wykorzystany albo wygasły —
 * nic się nie zmieni po ponowieniu. Brak odpowiedzi i 5xx to chwilowa awaria
 * po naszej stronie: odbiorca nie może zobaczyć „link wygasł", bo wyrzuciłby
 * ważny link (UAT M12-B01). Do 09.2026 obie gałęzie kończyły się ogólną
 * stroną 404 aplikacji z przyciskiem „Wróć do dashboardu".
 */
export type PublicLinkFailure = "invalid" | "unavailable";

export function publicLinkFailure(status: number | null): PublicLinkFailure {
  // 429 (limit zapytań) i 408 to też chwilowe — ponowienie pomoże (FE-N01).
  if (status === 429 || status === 408) return "unavailable";
  return status !== null && status >= 400 && status < 500 ? "invalid" : "unavailable";
}
