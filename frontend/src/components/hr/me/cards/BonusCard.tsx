"use client";

import type { EmploymentType } from "@/lib/api/hr";
import { useMyPayroll } from "@/lib/api/hr-payroll";
import { formatDayMonthPl } from "@/lib/date-pl";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";
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

/** Karta premii w „Przeglądzie”; przy B2B i zleceniu „Wynagrodzenie dodatkowe” (21.10.2026). */
export function BonusCard({
  form,
  today,
  onOpenTab,
}: {
  form?: EmploymentType | null;
  today: string;
  onOpenTab: (value: string) => void;
}) {
  const words = employmentTerms(form);
  const title = capitalize(words.bonuses);
  const me = useMyPayroll();
  const state = stateOf(me);
  if (state === "loading") {
    return (
      <OverviewCard title={title}>
        <Loading />
      </OverviewCard>
    );
  }
  if (state !== "ready" || !me.data) {
    return (
      <OverviewCard title={title}>
        <PartError
          label={`Nie udało się wczytać ${words.bonuses_genitive}.`}
          onRetry={() => me.refetch()}
        />
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
      title={title}
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
        <p className="text-sm text-muted-foreground">Nie ma {words.bonuses_genitive} w drodze.</p>
      )}
      {items.length > 0 ? (
        <ul className="space-y-2.5">
          {items.slice(0, 3).map((item) => (
            <li key={item.key} className="text-xs">
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 truncate" title={item.title}>
                  <span className="font-semibold text-foreground">
                    {item.title.replace(/^Placement: /, "")}
                  </span>
                  <span className="text-muted-foreground"> · {item.subtitle}</span>
                </span>
                <span className="shrink-0 tabular-nums text-foreground">{bonusAmountLabel(item)}</span>
              </div>
              {item.progress !== null ? (
                <div
                  role="progressbar"
                  aria-label={`Dni do terminu: ${item.title}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={item.progress}
                  className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"
                >
                  <div className="h-full bg-success" style={{ width: `${item.progress}%` }} />
                </div>
              ) : null}
              <p className="mt-0.5 text-muted-foreground">{item.timeline}</p>
            </li>
          ))}
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
