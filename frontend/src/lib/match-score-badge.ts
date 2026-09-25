/**
 * Kolor odznaki kanonicznego dopasowania (0–100) — jeden dla wyszukiwarki
 * i dla „Szukaj ręcznie” w trybie listy Kandydatów.
 */
export function scoreBadgeClass(score: number): string {
  if (score >= 70) return "bg-success-muted text-success-muted-foreground";
  if (score >= 40) return "bg-warning-muted text-warning-muted-foreground";
  return "bg-muted text-muted-foreground";
}
