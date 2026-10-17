"use client";

import { useState, type ReactNode } from "react";
import { CalendarPlus, Clock, Download } from "lucide-react";
import Link from "next/link";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import { PersonEquipmentPanel } from "@/components/equipment/PersonEquipmentPanel";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { hoursLabel } from "@/components/v2/dashboard/custom/HrMyTimeTile";
import { apiErrorMessage } from "@/lib/api-error";
import { useMyEquipment } from "@/lib/api/equipment";
import type { HrConfig, PersonFull } from "@/lib/api/hr";
import {
  useAbsences,
  useLeaveBalance,
  useMyLeaveRequests,
  type LeaveBalance,
  type LeaveRequestRow,
} from "@/lib/api/hr-leave";
import { useMyLifecycleTasks } from "@/lib/api/hr-lifecycle";
import { useMyPayroll } from "@/lib/api/hr-payroll";
import {
  TIMESHEET_STATUS_LABELS,
  downloadTimeFile,
  timePaths,
  useMyMonth,
  useMyTimesheetHistory,
  type TimesheetHistoryItem,
} from "@/lib/api/hr-time";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState, type ViewState } from "@/lib/view-state";

import { LeaveRequestDialog } from "../leave/LeaveRequestDialog";
import { daysLabel, formatRange, shortDate, shortName, warsawToday } from "../leave/leave-format";
import { formatDay, formatMoney } from "../payroll/payroll-format";
import { currentYearMonth, monthTitle, statusLine } from "../time/time-format";
import { bonusAmountLabel } from "./BonusStagesTable";
import {
  MANDATE_HOURS_NOTE,
  absenceActionLabel,
  absenceCardKind,
  absenceCardTitle,
  assignedInYear,
  compactDays,
  inTransitLabel,
  inTransitSummary,
  missingDaysUntil,
  myBonusItems,
  nextAbsence,
  poolSegments,
  segmentPercent,
  timesheetAccusative,
  timesheetCardTitle,
  totalsLabel,
  type AbsenceCardKind,
} from "./overview-format";

const CARD_TITLE = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

function OverviewCard({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card size="sm" className={cn("flex min-w-0 flex-col gap-2", className)} aria-label={title}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <h2 className={CARD_TITLE}>{title}</h2>
        {aside ? <span className="text-xs text-muted-foreground">{aside}</span> : null}
      </div>
      {children}
    </Card>
  );
}

/** Awaria jednej części karty: zdanie z ponowieniem, nigdy „0”. */
function PartError({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {label}{" "}
      <button
        type="button"
        onClick={onRetry}
        className="font-medium text-primary underline-offset-2 hover:underline"
      >
        Spróbuj ponownie
      </button>
    </p>
  );
}

function stateOf(query: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
}): ViewState {
  return resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
}

function Loading() {
  return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
}

// ── Nieobecności ─────────────────────────────────────────────────────────────

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

function AbsenceCard({ form, year, today }: { form: PersonFull["employment_type"]; year: number; today: string }) {
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

// ── Miesiąc ──────────────────────────────────────────────────────────────────

function previousTimesheet(
  items: readonly TimesheetHistoryItem[],
  current: { year: number; month: number },
): TimesheetHistoryItem | null {
  return (
    items.find((item) => item.year * 12 + item.month < current.year * 12 + current.month) ?? null
  );
}

function MonthCard({
  form,
  today,
  onOpenTab,
}: {
  form: PersonFull["employment_type"];
  today: string;
  onOpenTab: (value: string) => void;
}) {
  const current = currentYearMonth();
  const month = useMyMonth(current.year, current.month);
  const history = useMyTimesheetHistory();
  const { showToast } = useToast();
  const state = stateOf(month);
  const title = `${timesheetCardTitle(form)} · ${monthTitle(current).split(" ")[0]}`;

  const download = async (item: TimesheetHistoryItem) => {
    try {
      await downloadTimeFile(
        timePaths.myPdf(item.year, item.month),
        `timesheet-${item.year}-${String(item.month).padStart(2, "0")}.pdf`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać PDF."), "error");
    }
  };

  if (state === "loading") {
    return (
      <OverviewCard title={title}>
        <Loading />
      </OverviewCard>
    );
  }
  if (state !== "ready" || !month.data) {
    return (
      <OverviewCard title={title}>
        <PartError label="Nie udało się wczytać miesiąca." onRetry={() => month.refetch()} />
      </OverviewCard>
    );
  }
  const view = month.data;
  const missing = missingDaysUntil(view, today);
  const previous =
    history.isSuccess && history.data ? previousTimesheet(history.data, current) : null;
  return (
    <OverviewCard title={title} aside={statusLine(view)}>
      <p className="text-lg font-semibold tabular-nums text-foreground">{hoursLabel(view.totals)}</p>
      <p className="text-xs text-muted-foreground">
        {missing.length > 0
          ? `${countPl(missing.length, "dzień", "dni", "dni")} do uzupełnienia: ${compactDays(missing)}`
          : "Dni do dziś uzupełnione"}
        {` · akceptuje ${view.approver_name ? shortName(view.approver_name) : "Kadry"}`}
      </p>
      {form === "zlecenie" ? <p className="text-xs text-muted-foreground">{MANDATE_HOURS_NOTE}</p> : null}
      <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <button
          type="button"
          className="font-medium text-primary underline-offset-2 hover:underline"
          onClick={() => onOpenTab("month")}
        >
          Archiwum timesheetów
        </button>
        {history.isError ? (
          <PartError label="Nie udało się wczytać archiwum." onRetry={() => history.refetch()} />
        ) : previous ? (
          <span className="inline-flex items-center gap-1">
            · {monthTitle(previous).split(" ")[0]}: {TIMESHEET_STATUS_LABELS[previous.status].toLowerCase()}
            {previous.status === "approved" ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-1.5"
                onClick={() => void download(previous)}
                aria-label={`Pobierz PDF ${monthTitle(previous).toLowerCase()}`}
              >
                <Download className="mr-1 h-3.5 w-3.5" aria-hidden />
                PDF
              </Button>
            ) : null}
          </span>
        ) : null}
      </div>
    </OverviewCard>
  );
}

// ── Premie ───────────────────────────────────────────────────────────────────

function BonusCard({ today, onOpenTab }: { today: string; onOpenTab: (value: string) => void }) {
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
          ? `stawka ${formatMoney(rate.hourly_rate, rate.currency)}/h od ${formatDay(rate.effective_from).slice(0, 5)}`
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

// ── Przełożony, sprzęt, do zrobienia ─────────────────────────────────────────

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function ManagerCard({ person, leaveOpen }: { person: PersonFull; leaveOpen: boolean }) {
  const managerId = person.manager_user_id;
  const absences = useAbsences(managerId ? [managerId] : [], { enabled: leaveOpen && Boolean(managerId) });
  const absence = managerId ? absences.byUser.get(managerId) : undefined;
  return (
    <OverviewCard title="Mój przełożony">
      {person.manager_name && managerId ? (
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground"
          >
            {initials(person.manager_name)}
          </span>
          <div className="min-w-0">
            <Link href={`/people/${managerId}`} className="block truncate text-sm font-medium text-foreground hover:underline">
              {person.manager_name}
            </Link>
            {leaveOpen && absences.isSuccess ? (
              absence ? (
                <AbsenceBadge absence={absence} />
              ) : (
                <span className="text-xs text-muted-foreground">w pracy</span>
              )
            ) : null}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Przełożony nie jest ustawiony — ustawią go Kadry.</p>
      )}
      {leaveOpen ? (
        <p className="text-xs text-muted-foreground">Zastępcę na czas nieobecności wskazujesz we wniosku.</p>
      ) : null}
    </OverviewCard>
  );
}

interface TodoItem {
  key: string;
  title: string;
  detail: string;
  href?: string;
  onClick?: () => void;
  overdue?: boolean;
}

function TodoCard({
  config,
  person,
  onOpenTab,
}: {
  config: HrConfig;
  person: PersonFull;
  onOpenTab: (value: string) => void;
}) {
  const open = config.open_modules;
  const current = currentYearMonth();
  const tasks = useMyLifecycleTasks(open.lifecycle);
  const equipment = useMyEquipment(open.equipment);
  const month = useMyMonth(current.year, current.month, open.time);
  const history = useMyTimesheetHistory(open.time);
  const form = timesheetAccusative(person.employment_type);
  const monthName = (value: { year: number; month: number }) =>
    monthTitle(value).toLowerCase().split(" ")[0];

  const items: TodoItem[] = [];
  const failures: { label: string; retry: () => void }[] = [];

  if (open.lifecycle) {
    if (tasks.isError) failures.push({ label: "zadań wejścia i odejścia", retry: () => tasks.refetch() });
    for (const task of tasks.data ?? []) {
      items.push({
        key: `task-${task.task_id}`,
        title: task.title,
        detail: [task.person_name, task.due_date ? `do ${shortDate(task.due_date)}` : null]
          .filter(Boolean)
          .join(" · "),
        href: task.link,
        overdue: task.overdue,
      });
    }
  }
  if (open.equipment) {
    if (equipment.isError && stateOf(equipment) === "error") {
      failures.push({ label: "protokołów sprzętu", retry: () => equipment.refetch() });
    }
    for (const protocol of equipment.data?.protocols ?? []) {
      if (protocol.status !== "oczekuje") continue;
      items.push({
        key: `protocol-${protocol.id}`,
        title: `Podpisz protokół ${protocol.number}`,
        detail: `Recepcja · link w mailu · z ${shortDate(protocol.protocol_date)}`,
      });
    }
  }
  if (open.time && person.timesheet_required) {
    if (month.isError || history.isError) {
      failures.push({
        label: "timesheetów",
        retry: () => {
          void month.refetch();
          void history.refetch();
        },
      });
    }
    for (const item of history.data ?? []) {
      const older = item.year * 12 + item.month < current.year * 12 + current.month;
      if (older && item.status === "draft") {
        items.push({
          key: `ts-${item.id}`,
          title: `Wyślij ${form} za ${monthTitle(item).toLowerCase()}`,
          detail: "termin minął",
          onClick: () => onOpenTab("month"),
          overdue: true,
        });
      }
    }
    const view = month.data;
    const status = view?.timesheet?.status ?? (view ? "draft" : null);
    if (view && status === "draft") {
      items.push({
        key: "ts-current",
        title: view.timesheet?.return_note
          ? `Popraw ${form} za ${monthName(current)}`
          : `Wyślij ${form} za ${monthName(current)}`,
        detail: view.timesheet?.return_note
          ? `zwrócono do poprawy · do ${shortDate(view.deadline)}`
          : `do ${shortDate(view.deadline)}`,
        onClick: () => onOpenTab("month"),
      });
    }
  }

  const loading =
    (open.lifecycle && tasks.isLoading) ||
    (open.equipment && equipment.isLoading) ||
    (open.time && person.timesheet_required && (month.isLoading || history.isLoading));

  return (
    <OverviewCard title="Do zrobienia">
      {items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.key} className="text-sm">
              {item.href ? (
                <Link href={item.href} className="font-medium text-foreground hover:underline">
                  {item.title}
                </Link>
              ) : item.onClick ? (
                <button
                  type="button"
                  onClick={item.onClick}
                  className="text-left font-medium text-foreground hover:underline"
                >
                  {item.title}
                </button>
              ) : (
                <span className="font-medium text-foreground">{item.title}</span>
              )}
              {item.detail ? (
                <span className={cn("block text-xs", item.overdue ? "text-destructive" : "text-muted-foreground")}>
                  {item.detail}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : loading ? (
        <Loading />
      ) : failures.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nic do zrobienia.</p>
      ) : null}
      {failures.map((failure) => (
        <PartError
          key={failure.label}
          label={`Nie udało się wczytać ${failure.label}.`}
          onRetry={failure.retry}
        />
      ))}
    </OverviewCard>
  );
}

// ── Zakładka ─────────────────────────────────────────────────────────────────

export interface MyOverviewTabProps {
  config: HrConfig;
  person: PersonFull;
  /** Przejście do innej zakładki „Mojego czasu” (wartość `?tab=`). */
  onOpenTab: (value: string) => void;
}

/**
 * „Mój czas → Przegląd” (etap 2, D1): ile mam nieobecności, co z moim
 * miesiącem, ile i kiedy dostanę, przełożony, sprzęt i moje zadania. Każda
 * karta zależy od swojego modułu (wyłączony = brak karty) i ma własny stan:
 * awaria to zdanie z ponowieniem, nigdy „0”.
 */
export function MyOverviewTab({ config, person, onOpenTab }: MyOverviewTabProps) {
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const open = config.open_modules;
  const [dialogOpen, setDialogOpen] = useState(false);
  const balance = useLeaveBalance(year, open.leave);
  const form = person.employment_type;
  const firstName = person.name.split(/\s+/)[0] ?? person.name;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Dzień dobry, {firstName}</p>
        <div className="flex flex-wrap gap-2">
          {open.time ? (
            <Button variant="outline" size="sm" onClick={() => onOpenTab("month")}>
              <Clock className="mr-1.5 h-4 w-4" aria-hidden />
              Uzupełnij dzień
            </Button>
          ) : null}
          {open.leave ? (
            <Button size="sm" onClick={() => setDialogOpen(true)}>
              <CalendarPlus className="mr-1.5 h-4 w-4" aria-hidden />
              {absenceActionLabel(form)}
            </Button>
          ) : null}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {open.leave ? <AbsenceCard form={form} year={year} today={today} /> : null}
        {open.time ? <MonthCard form={form} today={today} onOpenTab={onOpenTab} /> : null}
        {open.payroll ? <BonusCard today={today} onOpenTab={onOpenTab} /> : null}
        <ManagerCard person={person} leaveOpen={open.leave} />
        {open.equipment ? (
          <OverviewCard title="Mój sprzęt">
            <PersonEquipmentPanel userId="mine" />
          </OverviewCard>
        ) : null}
        <TodoCard config={config} person={person} onOpenTab={onOpenTab} />
      </div>
      {open.leave ? (
        <LeaveRequestDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          mode="self"
          allowedTypes={balance.data?.allowed_types}
        />
      ) : null}
    </div>
  );
}
