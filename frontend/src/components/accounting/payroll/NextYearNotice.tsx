"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { usePayrollParameters, type NextYearGap } from "@/lib/api/payroll-lists";

import { datePl } from "../ledger-model";
import { NEXT_YEAR_DRAFT_HREF, nextYearSummary, nextYearTitle } from "./parameters-model";

/** „Brak parametrów płac od 01.01.RRRR” — pas nad ekranem z przyciskiem do szkicu. */
export function NextYearNotice({ gap, action }: { gap: NextYearGap; action: ReactNode }) {
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-warning/40 bg-warning-muted px-3.5 py-2.5 text-[13px] text-warning-muted-foreground"
    >
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0">
          <p className="font-medium">{nextYearTitle(gap)}</p>
          <p className="mt-0.5">{nextYearSummary(gap)}</p>
        </div>
      </div>
      <div className="shrink-0">{action}</div>
    </div>
  );
}

/**
 * Ekrany miesięcy płac: pobiera parametry (ten sam cache co „Parametry”) i nic
 * nie pokazuje, gdy luki nie ma, moduł jest wyłączony albo osoba nie ma Płac.
 * `onOpen` — gdy ekran sam przełącza widok na „Parametry”; bez niego link.
 */
export function NextYearBanner({ enabled = true, onOpen }: { enabled?: boolean; onOpen?: () => void }) {
  const query = usePayrollParameters(enabled);
  const gap = query.data?.next_year;
  if (!enabled || !query.isSuccess || !gap) return null;
  const label = `Otwórz szkic od ${datePl(gap.effective_from)}`;
  return (
    <NextYearNotice
      gap={gap}
      action={
        onOpen ? (
          <Button size="sm" onClick={onOpen}>
            {label}
          </Button>
        ) : (
          <Button size="sm" asChild>
            <Link href={NEXT_YEAR_DRAFT_HREF}>{label}</Link>
          </Button>
        )
      }
    />
  );
}
