import { cn } from "@/lib/utils";
import { formatPlnAmount, formatWholeAmount } from "./rate-format";

/** „≈ 166,68 zł/h” przy kwocie w EUR; bez kursu albo bez kwoty — nic. */
export function PlnConversion({
  amount,
  exchangeRate,
  unitSuffix = "",
  testId,
  whole = false,
  className,
}: {
  amount: number | null;
  /** Kurs EUR/PLN, gdy kwota jest w EUR; inaczej `null`. */
  exchangeRate: number | null;
  unitSuffix?: string;
  testId?: string;
  /** Kwota miesięczna — w pełnych złotych. */
  whole?: boolean;
  className?: string;
}) {
  if (amount === null || exchangeRate === null) return null;
  const pln = amount * exchangeRate;

  return (
    <span
      className={cn("whitespace-nowrap text-xs font-normal text-muted-foreground", className)}
      data-testid={testId}
    >
      <span className="sr-only">W przybliżeniu </span>
      <span aria-hidden="true">≈</span> {whole ? `${formatWholeAmount(pln)} zł` : formatPlnAmount(pln)}
      {unitSuffix}
    </span>
  );
}
