"use client";

import type { BonusClawback } from "@/lib/api/hr-payroll";

import { totalsLabel } from "../me/overview-format";
import { clawbackActive, clawbackProgress, clawbackReason, clawbackRemaining } from "./clawback-format";

/**
 * „Do zwrotu z gwarancji” nad premiami w „Moim czasie” (05.11.2026): konsultant
 * nie przepracował 12 miesięcy, więc premia DL za placement wraca — potrąca się
 * sama z kolejnych premii. Bez długów karty nie ma.
 */
export function MyClawbacksCard({ items }: { items: BonusClawback[] | undefined }) {
  const shown = (items ?? []).filter(clawbackActive);
  if (shown.length === 0) return null;
  const remaining = clawbackRemaining(shown);
  return (
    <section
      aria-labelledby="my-clawbacks"
      className="rounded-lg border border-warning/40 bg-warning-muted/30 px-4 py-3"
    >
      <h2 id="my-clawbacks" className="text-sm font-semibold text-foreground">
        Do zwrotu z gwarancji:{" "}
        {Object.keys(remaining).length > 0 ? totalsLabel(remaining) : "nic"}
      </h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Konsultant nie przepracował 12 miesięcy od startu, więc premia za placement wraca. Kwota
        potrąca się sama z Twoich kolejnych premii.
      </p>
      <ul className="mt-2 space-y-1.5">
        {shown.map((item) => (
          <li key={item.id} className="text-sm">
            <span className="block font-medium text-foreground">
              {item.description ?? "Premia DL"}
            </span>
            <span className="block text-xs text-muted-foreground">
              {clawbackReason(item)} · {clawbackProgress(item)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
