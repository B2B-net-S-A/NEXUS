"use client";

import Link from "next/link";
import { isAxiosError } from "axios";

import { useMyPayroll } from "@/lib/api/hr-payroll";
import { MONTHS_PL } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";
import {
  inTransitLabel,
  inTransitSummary,
  myBonusItems,
  totalsLabel,
} from "@/components/hr/me/overview-format";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading } from "../ViewKit";

/** Płace wyłączone albo osoba bez kartoteki — karty premii po prostu nie ma. */
function isNoPayroll(error: unknown): boolean {
  return isAxiosError(error) && [403, 404].includes(error.response?.status ?? 0);
}

/**
 * „Moja premia” (decyzja Artura 22.10.2026: tylko własna kwota). Te same dane
 * i reguły co karta premii w „Mój czas” (`/api/hr/payroll/me`): przyznane za
 * bieżący miesiąc i „w drodze” — propozycje i premie z podpisanych umów,
 * których automat jeszcze nie założył.
 */
export function MyBonusPanel() {
  const me = useMyPayroll();
  if (me.isPending) return <PanelLoading />;
  if (me.isError) {
    if (isNoPayroll(me.error)) return null;
    return (
      <SectionError label="Moja premia" error={me.error} onRetry={() => void me.refetch()} />
    );
  }
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  const assignedThisMonth: Record<string, number> = {};
  for (const bonus of me.data.bonuses) {
    if (bonus.status !== "assigned" || bonus.period_year !== year || bonus.period_month !== month) {
      continue;
    }
    assignedThisMonth[bonus.currency] =
      (assignedThisMonth[bonus.currency] ?? 0) + Number(bonus.amount);
  }
  const transit = inTransitSummary(myBonusItems(me.data, today));

  return (
    <Panel title={`Moja premia — ${MONTHS_PL[month - 1]}`} hint="widzisz tylko swoją">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Przyznane za ten miesiąc
          </p>
          <p className="text-2xl font-bold tabular-nums text-foreground">
            {totalsLabel(assignedThisMonth)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            W drodze
          </p>
          <p className="text-2xl font-bold tabular-nums text-foreground">
            {transit.count > 0 ? inTransitLabel(transit) : "—"}
          </p>
          <p className="text-xs text-muted-foreground">
            {transit.count > 0
              ? `${transit.count} — propozycje i premie z podpisanych umów przed terminem`
              : "Nic nie czeka na przyznanie."}
          </p>
        </div>
      </div>
      <Link
        href="/my-time?tab=bonuses"
        className="w-fit text-sm font-semibold text-primary hover:underline"
      >
        Szczegóły w „Mój czas” →
      </Link>
    </Panel>
  );
}
