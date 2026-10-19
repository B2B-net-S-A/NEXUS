"use client";

import type { OwnProfile } from "@/lib/api/hr";
import {
  useLeaveBalance,
  useMyLeaveRequests,
  type LeaveBalance,
  type LeaveRequestRow,
} from "@/lib/api/hr-leave";
import { reportsAbsence } from "@/lib/hr-employment-terms";

import { daysLabel, formatRange, shortName } from "../../leave/leave-format";
import {
  absenceCardKind,
  absenceCardTitle,
  nextAbsence,
  poolSegments,
  ringArcs,
  type AbsenceCardKind,
  type RingArc,
} from "../overview-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

const ARC_TONE: Record<RingArc["key"], string> = {
  used: "stroke-primary",
  planned: "stroke-primary/50",
  pending: "stroke-warning",
};

/** Pierścień puli: wykorzystane, zaplanowane, czeka; w środku „zostało”. */
function PoolRing({ balance }: { balance: LeaveBalance }) {
  const parts = poolSegments(balance);
  if (!parts || parts.total <= 0) return null;
  const label = `Wykorzystane ${daysLabel(parts.used)}, zaplanowane ${daysLabel(
    parts.planned,
  )}, czeka ${daysLabel(parts.pending)}, zostało ${daysLabel(parts.remaining)}`;
  return (
    <div role="img" aria-label={label} className="relative size-24 shrink-0">
      <svg viewBox="0 0 36 36" className="size-full -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r="15.9" fill="none" strokeWidth="4" className="stroke-muted" />
        {ringArcs(parts).map((arc) =>
          arc.percent > 0 ? (
            <circle
              key={arc.key}
              cx="18"
              cy="18"
              r="15.9"
              fill="none"
              strokeWidth="4"
              pathLength={100}
              strokeDasharray={`${arc.percent} ${100 - arc.percent}`}
              strokeDashoffset={-arc.start}
              className={ARC_TONE[arc.key]}
            />
          ) : null,
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-bold tabular-nums leading-none text-foreground">
          {Number(balance.remaining_days ?? 0).toLocaleString("pl-PL", { maximumFractionDigits: 1 })}
        </span>
        <span className="text-[11px] text-muted-foreground">zostało</span>
      </div>
    </div>
  );
}

function Legend({ data }: { data: LeaveBalance }) {
  return (
    <ul className="space-y-1 text-xs text-muted-foreground">
      <li>
        <span className="mr-1.5 inline-block size-2 rounded-sm bg-primary" aria-hidden />
        wykorzystane {daysLabel(data.used_days)}
      </li>
      <li>
        <span className="mr-1.5 inline-block size-2 rounded-sm bg-primary/50" aria-hidden />
        zaplanowane {daysLabel(data.planned_days)}
      </li>
      <li>
        <span className="mr-1.5 inline-block size-2 rounded-sm bg-warning" aria-hidden />
        czeka {daysLabel(data.pending_days)}
      </li>
    </ul>
  );
}

/** Najbliższa nieobecność w dwóch liniach: termin i stan (z zastępcą). */
function nextParts(kind: AbsenceCardKind, row: LeaveRequestRow | null): { head: string; sub: string | null } {
  const leave = kind === "leave";
  const lead = leave ? "Najbliższy urlop" : "Najbliższa nieobecność";
  if (!row) return { head: `${lead}: brak zaplanowane${leave ? "go" : "j"}`, sub: null };
  // Zgłoszenie z B2B i zlecenia wchodzi od razu — „zgłoszona”, nikt jej nie
  // zatwierdza (D5); to samo słowo co w liście „Moje” (`statusLabel`).
  const approved = row.is_report
    ? leave ? "zgłoszony" : "zgłoszona"
    : leave ? "zatwierdzony" : "zatwierdzona";
  const state = row.status === "approved" ? approved : "czeka na akceptację";
  const stand = row.substitute_name ? ` · zastępuje ${shortName(row.substitute_name)}` : "";
  return { head: `${lead}: ${formatRange(row.start_date, row.end_date)}`, sub: `${state}${stand}` };
}

export function AbsenceCard({ form, year, today }: { form: OwnProfile["employment_type"]; year: number; today: string }) {
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
      ? nextParts(kind, nextAbsence(requests.data, today, kind !== "absences"))
      : null;
  const nextPart =
    requestsState === "loading" ? null : next ? (
      <div className="rounded-md bg-muted/50 px-3 py-2 text-xs">
        <p className="font-semibold text-foreground">{next.head}</p>
        {next.sub ? <p className="text-muted-foreground">{next.sub}</p> : null}
      </div>
    ) : (
      <PartError label="Nie udało się wczytać wniosków." onRetry={() => requests.refetch()} />
    );

  if (kind === "absences") {
    // Na B2B i zleceniu nic nie czeka na akceptację (D5) — liczba tylko, gdy
    // coś zostało sprzed zmiany formy (jak `balanceStats`).
    const pending =
      reportsAbsence(form) && !(Number(data.pending_days) > 0)
        ? ""
        : ` · czeka na akceptację ${daysLabel(data.pending_days)}`;
    return (
      <OverviewCard title={title}>
        <p className="text-lg font-semibold tabular-nums text-foreground">
          {daysLabel(data.planned_days)}{" "}
          <span className="text-sm font-normal text-muted-foreground">zaplanowane</span>
        </p>
        <p className="text-xs text-muted-foreground">
          wykorzystane {daysLabel(data.used_days)}
          {pending}
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
        <div className="flex items-center gap-4" title="Pula minus wykorzystane, zaplanowane i czekające na akceptację.">
          <PoolRing balance={data} />
          <Legend data={data} />
        </div>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            Pula na {year} nie jest ustawiona — zrobią to Kadry.
          </p>
          <Legend data={data} />
        </>
      )}
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
