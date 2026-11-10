"use client";

import Link from "next/link";

import type { CompanyIdentityMatch } from "@/lib/api/sales-handoffs";

const REASONS: Record<CompanyIdentityMatch["reason"], string> = {
  name: "ta sama nazwa",
  domain: "ta sama domena",
  similar: "podobna nazwa",
};

function details(match: CompanyIdentityMatch): string {
  const open =
    match.open_opportunities === 0
      ? null
      : match.open_opportunities === 1
        ? "1 otwarta szansa"
        : `otwarte szanse: ${match.open_opportunities}`;
  return [REASONS[match.reason], match.hq_city, match.domain, open].filter(Boolean).join(" · ");
}

interface CompanyIdentityHintsProps {
  matches: CompanyIdentityMatch[];
  /** Z funkcją: wiersz jest przyciskiem „użyj tej karty”. Bez niej: odnośnik do karty w nowej karcie. */
  onPick?: (match: CompanyIdentityMatch) => void;
}

/**
 * Karty, które już mogą być tą firmą (ta sama nazwa, domena albo podobna nazwa).
 * To podpowiedź przy zakładaniu: niczego nie blokuje.
 */
export function CompanyIdentityHints({ matches, onPick }: CompanyIdentityHintsProps) {
  if (matches.length === 0) return null;
  return (
    <div className="rounded-md border border-border bg-muted/30 px-2.5 py-1.5" data-testid="company-identity-hints">
      <p className="text-xs font-medium text-foreground">
        {onPick ? "Ta firma może już być w kartotece. Kliknij, żeby użyć karty:" : "Ta firma może już być w kartotece:"}
      </p>
      <ul className="mt-1 space-y-0.5">
        {matches.map((match) => (
          <li key={match.id} className="flex min-w-0 items-baseline gap-2 text-xs">
            {onPick ? (
              <button
                type="button"
                className="shrink-0 font-medium text-primary hover:underline"
                onClick={() => onPick(match)}
              >
                {match.name}
              </button>
            ) : (
              <Link
                href={`/sales/companies/${match.id}`}
                target="_blank"
                className="shrink-0 font-medium text-primary hover:underline"
              >
                {match.name}
              </Link>
            )}
            <span className="min-w-0 truncate text-muted-foreground">{details(match)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
