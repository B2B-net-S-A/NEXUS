/** Kolor pigułki hit ratio względem CELU z backendu (`hit_ratio_target_pct`,
 *  dziś 30%) — do 24.09.2026 progi 50/20 były wpisane na sztywno i klient na
 *  celu świecił na bursztynowo (audyt N8). Mieszka poza `app/clients/[id]/page.tsx`,
 *  bo plik trasy Next.js nie może eksportować pomocników. */
export function hitRatioTone(hitRatio: number, targetPct: number): string {
  if (hitRatio >= targetPct) return "bg-success-muted text-success-muted-foreground";
  if (hitRatio >= targetPct / 2) return "bg-warning-muted text-warning-muted-foreground";
  return "bg-destructive-muted text-destructive-muted-foreground";
}
