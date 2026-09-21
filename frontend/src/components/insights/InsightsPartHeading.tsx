/**
 * Nagłówek części rozdziału („Wynik", „Zespół", …).
 *
 * Rozdział Wyniki składa się z czterech części na jednym przewijaniu; bez
 * wyraźnego nagłówka karty zlewały się w jedną ścianę (uwaga z makiet
 * 21.09.2026 — „wszystko jest zlane i nie można się w tym połapać").
 */
export function InsightsPartHeading({
  title,
  hint,
}: {
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border pb-2">
      <h2 className="text-lg font-bold tracking-tight text-foreground">{title}</h2>
      {hint ? <span className="text-sm text-muted-foreground">{hint}</span> : null}
    </div>
  );
}
