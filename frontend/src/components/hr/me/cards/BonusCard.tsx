"use client";

import { useMyPayroll } from "@/lib/api/hr-payroll";
import { formatDayMonthPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

import { bonusAmountLabel } from "../BonusStagesTable";
import {
  assignedInYear,
  inTransitLabel,
  inTransitSummary,
  myBonusItems,
  totalsLabel,
} from "../overview-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

export function BonusCard({ today, onOpenTab }: { today: string; onOpenTab: (value: string) => void }) {
  const me = useMyPayroll();
  const state = stateOf(me);
  if (state === "loading") {
    return (
      <OverviewCard title="Premie">
        <Loading />
      </OverviewCard>
    );
  }
  if (state !== "ready" || !me.data) {
    return (
      <OverviewCard title="Premie">
        <PartError label="Nie udało się wczytać premii." onRetry={() => me.refetch()} />
      </OverviewCard>
    );
  }
  const data = me.data;
  const year = Number(today.slice(0, 4));
  const items = myBonusItems(data, today).filter((item) => item.inTransit);
  const summary = inTransitSummary(items);
  const rate = data.current_rate;
  return (
    <OverviewCard
      title="Premie"
      aside={
        rate
          ? `stawka ${formatMoney(rate.hourly_rate, rate.currency)}/h od ${formatDayMonthPl(rate.effective_from)}`
          : "stawka nie ustawiona"
      }
    >
      {summary.count > 0 ? (
        <p className="text-lg font-semibold tabular-nums text-foreground">
          {inTransitLabel(summary)}{" "}
          <span className="text-sm font-normal text-muted-foreground">w drodze</span>
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">Nie ma premii w drodze.</p>
      )}
      {items.length > 0 ? (
        <ul className="space-y-1">
          {items.slice(0, 3).map((item) => {
            const current = item.stages.find((stage) => stage.state === "current");
            return (
              <li key={item.key} className="text-xs">
                <span className="block truncate font-medium text-foreground" title={item.title}>
                  {item.title.replace(/^Placement: /, "")}
                </span>
                <span className="text-muted-foreground">
                  {[current?.label, bonusAmountLabel(item), item.when].filter(Boolean).join(" · ")}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className="mt-auto text-xs text-muted-foreground">
        Przyznane w {year}: {totalsLabel(assignedInYear(data.bonuses, year))} ·{" "}
        <button
          type="button"
          className="font-medium text-primary underline-offset-2 hover:underline"
          onClick={() => onOpenTab("bonuses")}
        >
          Szczegóły i rozliczenie
        </button>
      </p>
    </OverviewCard>
  );
}
