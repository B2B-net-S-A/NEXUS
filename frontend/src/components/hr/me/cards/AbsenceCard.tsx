"use client";

import type { PersonFull } from "@/lib/api/hr";
import {
  useLeaveBalance,
  useMyLeaveRequests,
  type LeaveBalance,
  type LeaveRequestRow,
} from "@/lib/api/hr-leave";

import { daysLabel, formatRange, shortName } from "../../leave/leave-format";
import {
  absenceCardKind,
  absenceCardTitle,
  nextAbsence,
  poolSegments,
  segmentPercent,
  type AbsenceCardKind,
} from "../overview-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

function PoolBar({ balance }: { balance: LeaveBalance }) {
  const parts = poolSegments(balance);
  if (!parts || parts.total <= 0) return null;
  const label = `Wykorzystane ${daysLabel(parts.used)}, zaplanowane ${daysLabel(
    parts.planned,
  )}, czeka ${daysLabel(parts.pending)}, zostało ${daysLabel(parts.remaining)}`;
  return (
    <div role="img" aria-label={label} className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
      <span className="h-full bg-primary" style={{ width: `${segmentPercent(parts.used, parts.total)}%` }} />
      <span
        className="h-full bg-primary/50"
        style={{ width: `${segmentPercent(parts.planned, parts.total)}%` }}
      />
      <span
        className="h-full bg-warning"
        style={{ width: `${segmentPercent(parts.pending, parts.total)}%` }}
      />
    </div>
  );
}

function nextLine(kind: AbsenceCardKind, row: LeaveRequestRow | null): string {
  const leave = kind === "leave";
  const lead = leave ? "Najbliższy urlop" : "Najbliższa nieobecność";
  if (!row) return `${lead}: brak zaplanowane${leave ? "go" : "j"}`;
  const state =
    row.status === "approved" ? (leave ? "zatwierdzony" : "zatwierdzona") : "czeka na akceptację";
  const stand = row.substitute_name ? ` · zastępuje ${shortName(row.substitute_name)}` : "";
  return `${lead}: ${formatRange(row.start_date, row.end_date)} · ${state}${stand}`;
}

export function AbsenceCard({ form, year, today }: { form: PersonFull["employment_type"]; year: number; today: string }) {
  const balance = useLeaveBalance(year);
  const requests = useMyLeaveRequests();
  const balanceState = stateOf(balance);
  const requestsState = stateOf(requests);
  const kind = absenceCardKind(form, balance.data);
  const title = absenceCardTitle(kind, year);

  if (balanceState === "loading") {
    return (
      <OverviewCard title={title}>
        <Loading />
      </OverviewCard>
    );
  }
  if (balanceState !== "ready" || !balance.data) {
    return (
      <OverviewCard title={title}>
        <PartError label="Nie udało się wczytać nieobecności." onRetry={() => balance.refetch()} />
      </OverviewCard>
    );
  }
  const data = balance.data;
  const next =
    requestsState === "ready" && requests.data
      ? nextLine(kind, nextAbsence(requests.data, today, kind !== "absences"))
      : null;
  const nextPart =
    requestsState === "loading" ? null : next ? (
      <p className="text-xs text-muted-foreground">{next}</p>
    ) : (
      <PartError label="Nie udało się wczytać wniosków." onRetry={() => requests.refetch()} />
    );

  if (kind === "absences") {
    return (
      <OverviewCard title={title}>
        <p className="text-lg font-semibold tabular-nums text-foreground">
          {daysLabel(data.planned_days)}{" "}
          <span className="text-sm font-normal text-muted-foreground">zaplanowane</span>
        </p>
        <p className="text-xs text-muted-foreground">
          wykorzystane {daysLabel(data.used_days)} · czeka na akceptację {daysLabel(data.pending_days)}
        </p>
        {nextPart}
      </OverviewCard>
    );
  }

  const hasPool = data.has_paid_pool;
  return (
    <OverviewCard
      title={title}
      aside={
        hasPool
          ? `pula ${daysLabel(Number(data.entitlement_days ?? 0) + Number(data.carried_over_days ?? 0))}`
          : undefined
      }
    >
      {hasPool ? (
        <>
          <p
            className="text-lg font-semibold tabular-nums text-foreground"
            title="Pula minus wykorzystane, zaplanowane i czekające na akceptację."
          >
            {daysLabel(data.remaining_days ?? "0")}{" "}
            <span className="text-sm font-normal text-muted-foreground">zostało</span>
          </p>
          <PoolBar balance={data} />
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Pula na {year} nie jest ustawiona — zrobią to Kadry.
        </p>
      )}
      <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
        <span>
          <span className="mr-1 inline-block size-2 rounded-full bg-primary" aria-hidden />
          wykorzystane {daysLabel(data.used_days)}
        </span>
        <span>
          <span className="mr-1 inline-block size-2 rounded-full bg-primary/50" aria-hidden />
          zaplanowane {daysLabel(data.planned_days)}
        </span>
        <span>
          <span className="mr-1 inline-block size-2 rounded-full bg-warning" aria-hidden />
          czeka {daysLabel(data.pending_days)}
        </span>
      </p>
      {nextPart}
      {kind === "leave" && (data.on_demand_limit !== null || data.childcare_limit !== null) ? (
        <p className="text-xs text-muted-foreground">
          {[
            data.on_demand_limit !== null
              ? `Na żądanie ${Number(data.on_demand_used ?? 0).toLocaleString("pl-PL")} z ${Number(data.on_demand_limit)}`
              : null,
            data.childcare_limit !== null
              ? `opieka nad dzieckiem ${Number(data.childcare_used ?? 0).toLocaleString("pl-PL")} z ${Number(data.childcare_limit)}`
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}
    </OverviewCard>
  );
}
