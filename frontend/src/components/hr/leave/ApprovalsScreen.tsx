"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { CalendarPlus, ChevronDown, ChevronRight } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { yearMonthFromParams } from "@/components/hr/MyTimeScreen";
import { TimesheetApprovalsSection } from "@/components/hr/time/TimesheetApprovalsSection";
import { defaultQueueMonth } from "@/components/hr/time/time-format";
import { ConsentsInbox } from "@/components/hr/approvals/ConsentsInbox";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useHrCounts, type HrConfig } from "@/lib/api/hr";
import {
  useCancelTeamLeave,
  useDecideLeave,
  useLeaveCovering,
  useLeaveHistory,
  useOnBehalfPeople,
  usePendingLeave,
  useReportedLeave,
  type LeaveRequestRow,
  type LeaveStatus,
} from "@/lib/api/hr-leave";
import { forwardStillAhead } from "@/lib/api/hr-m365";
import { useTeamQueue, type QueueStatus } from "@/lib/api/hr-time";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";
import { formatWeekdayDayPl, monthTitlePl, type YearMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { personInitials } from "../people/hr-format";
import {
  inboxItems,
  substituteAbsent,
  termDays,
  termRows,
  timesheetSummary,
  timesheetSummaryText,
  workSummary,
  dayMonthRange,
  type ChipTone,
  type InboxItem,
} from "./approvals-inbox";
import { EditLeaveDialog } from "./EditLeaveDialog";
import { ForwardOffDialog } from "./ForwardOffDialog";
import { LeaveRequestDialog } from "./LeaveRequestDialog";
import { ApproverProofNote } from "./LeaveProofs";
import { RejectLeaveDialog } from "./RejectLeaveDialog";
import { ReportConflictDialog } from "./ReportConflictDialog";
import {
  HALF_DAY_LABELS,
  LEAVE_STATUS_LABELS,
  LEAVE_STATUS_TONE,
  canEditRow,
  daysLabel,
  formatRange,
  historyCapNote,
  leaveToast,
  sourceBadge,
  statusFilterLabel,
  statusLabel,
} from "./leave-format";

/** Plakietka źródła wniosku („Z Outlooka”, „Wpis za konsultanta/kontraktora”, „Import z Compassa”). */
function SourceBadge({ row }: { row: LeaveRequestRow }) {
  const label = sourceBadge(row.source);
  if (!label) return null;
  return (
    <Badge size="sm" variant="outline" className="ml-1.5 align-middle font-normal">
      {label}
    </Badge>
  );
}

const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

const CHIP: Record<ChipTone, string> = {
  warning: "bg-warning-muted text-warning-muted-foreground",
  neutral: "bg-muted text-foreground",
  danger: "bg-destructive/10 text-destructive",
  info: "bg-info-muted text-info-muted-foreground",
};

function Avatar({ name, large = false }: { name: string; large?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full bg-primary/10 font-semibold text-primary",
        large ? "h-11 w-11 text-sm" : "h-8 w-8 text-[11px]",
      )}
    >
      {personInitials(name)}
    </span>
  );
}

function InboxRow({
  item,
  active,
  onSelect,
}: {
  item: InboxItem;
  active: boolean;
  onSelect: () => void;
}) {
  const name = item.row.user_name ?? "Osoba";
  return (
    <li>
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        aria-label={`${name}: ${item.line}`}
        onClick={onSelect}
        className={cn(
          "flex w-full items-start gap-2.5 border-t border-border/60 px-3.5 py-2.5 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          active && "bg-primary/5 shadow-[inset_3px_0_0_hsl(var(--primary))]",
        )}
      >
        <Avatar name={name} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate font-semibold text-foreground">{name}</span>
            {item.waited ? (
              <span className="shrink-0 text-xs text-muted-foreground">{item.waited}</span>
            ) : null}
          </span>
          <span className="block text-[13px] text-foreground">{item.line}</span>
          {item.chips.length > 0 ? (
            <span className="mt-1 flex flex-wrap gap-1">
              {item.chips.map((chip) => (
                <span
                  key={chip.text}
                  className={cn("rounded-full px-2 py-px text-xs font-medium", CHIP[chip.tone])}
                >
                  {chip.text}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

/**
 * Skrzynka (makieta 19.10.2026): lista spraw po lewej — „Do decyzji” (wnioski
 * z umowy o pracę) i „Do wiadomości · B2B i zlecenie” (zgłoszenia, D5) —
 * i szczegół po prawej. Jedno zapytanie (`GET /approvals/pending`).
 */
function LeaveInbox({ viewerIsHr }: { viewerIsHr: boolean }) {
  const pending = usePendingLeave();
  const reported = useReportedLeave();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const today = warsawToday();
  const { decide, info } = inboxItems(pending.data ?? [], reported.data ?? [], today);
  const state = resolveViewState({
    isLoading: pending.isLoading,
    isError: pending.isError,
    error: pending.error,
    isSuccess: pending.isSuccess,
    isEmpty: decide.length === 0 && info.length === 0,
  });

  if (state === "loading") {
    return <p className="py-4 text-sm text-muted-foreground">Wczytywanie wniosków…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={
          state === "forbidden" ? "Akceptacje widzą przełożeni i Kadry." : undefined
        }
        onRetry={() => pending.refetch()}
      />
    );
  }
  if (state === "empty") {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Nic nie czeka na Twoją decyzję. Nikt z zespołu na B2B ani na zleceniu nie ma zgłoszonej
        przerwy.
      </p>
    );
  }

  const all = [...decide, ...info];
  const current = all.find((item) => item.key === selectedKey) ?? all[0];
  return (
    <div className="flex flex-wrap overflow-hidden rounded-xl border border-border bg-card">
      <div className="min-w-0 flex-[1_1_340px] border-b border-border/60 md:border-b-0 md:border-r">
        <div data-help="hr.approvals.pending">
          <div className="flex items-center justify-between px-3.5 py-2.5">
            <h2 className={LABEL}>Do decyzji</h2>
            <span
              className={cn(
                "rounded-full px-2 py-px text-[11px] font-semibold",
                decide.length > 0 ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
              )}
            >
              {decide.length}
            </span>
          </div>
          {decide.length === 0 ? (
            <p className="border-t border-border/60 px-3.5 py-3 text-sm text-muted-foreground">
              Nic nie czeka na Twoją decyzję.
            </p>
          ) : (
            <ul aria-label="Wnioski do decyzji (umowa o pracę)">
              {decide.map((item) => (
                <InboxRow
                  key={item.key}
                  item={item}
                  active={item.key === current.key}
                  onSelect={() => setSelectedKey(item.key)}
                />
              ))}
            </ul>
          )}
        </div>
        <div data-help="hr.approvals.reported">
          <div className="flex items-center justify-between border-t border-border/60 bg-muted/40 px-3.5 py-2.5">
            <h2 className={LABEL}>Do wiadomości · B2B i zlecenie</h2>
            <span className="rounded-full bg-muted px-2 py-px text-[11px] font-semibold text-foreground">
              {info.length}
            </span>
          </div>
          {info.length === 0 ? (
            <p className="border-t border-border/60 px-3.5 py-3 text-sm text-muted-foreground">
              Nikt z zespołu na B2B ani na zleceniu nie ma zgłoszonej przerwy.
            </p>
          ) : (
            <ul aria-label="Zgłoszone przerwy i nieobecności (B2B, zlecenie) — do wiadomości">
              {info.map((item) => (
                <InboxRow
                  key={item.key}
                  item={item}
                  active={item.key === current.key}
                  onSelect={() => setSelectedKey(item.key)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
      <LeaveDetail key={current.key} item={current} viewerIsHr={viewerIsHr} />
    </div>
  );
}

/** Szczegół sprawy: przyciski, kafle „Zastępca / Wypada / Też nieobecni” i mini-kalendarz. */
function LeaveDetail({ item, viewerIsHr }: { item: InboxItem; viewerIsHr: boolean }) {
  const { row } = item;
  const decide = useDecideLeave();
  const { showToast } = useToast();
  const [rejecting, setRejecting] = useState<LeaveRequestRow | null>(null);
  const [editing, setEditing] = useState<LeaveRequestRow | null>(null);
  const [conflicting, setConflicting] = useState<LeaveRequestRow | null>(null);
  const name = row.user_name ?? "Osoba";
  const work = workSummary(row);
  const subAbsent = substituteAbsent(row);

  // `mutateAsync`, nie callbacki `mutate()`: po akceptacji lista odświeża się
  // bez tej sprawy i szczegół (z `key` sprawy) się odmontowuje, a callbacki
  // `mutate()` TanStack Query wtedy pomija — toast „Wniosek zaakceptowany”
  // znikał (20.10.2026, e2e flow-hr-leave).
  const approve = () =>
    decide.mutateAsync({ id: row.id, decision: "approve" }).then(
      (saved) => showToast(...leaveToast("Wniosek zaakceptowany", saved)),
      (err) => showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error"),
    );

  const actions =
    item.kind === "decide" ? (
      row.can_decide === false ? (
        <span className="text-sm text-muted-foreground">do wiadomości — decydują Kadry</span>
      ) : (
        <>
          {/* Zastępca przełożonego tylko decyduje — zmienia przełożony albo Kadry. */}
          {row.as_substitute_for ? null : (
            <Button variant="ghost" onClick={() => setEditing(row)}>
              Edytuj
            </Button>
          )}
          <Button variant="outline" onClick={() => setRejecting(row)}>
            Odrzuć
          </Button>
          <Button disabled={decide.isPending} onClick={approve}>
            Akceptuj
          </Button>
        </>
      )
    ) : (
      <>
        {/* Zgłoszenie z B2B/zlecenia zmieniają tylko Kadry (D5). */}
        {canEditRow(row, viewerIsHr) ? (
          <Button variant="ghost" onClick={() => setEditing(row)}>
            Edytuj
          </Button>
        ) : null}
        {row.can_report_conflict ? (
          <Button variant="outline" onClick={() => setConflicting(row)}>
            Zgłoś kolizję
          </Button>
        ) : (
          <span className="text-sm text-muted-foreground">do wiadomości</span>
        )}
      </>
    );

  const days = termDays(row.start_date, row.end_date);
  const rows = termRows(row, days);
  return (
    <section
      aria-label={`Szczegóły: ${name}`}
      className="flex min-w-0 flex-[999_1_520px] flex-col gap-4 p-4 md:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={name} large />
          <div className="min-w-0">
            <h3 className="text-lg font-semibold text-foreground">
              {row.leave_type_label} · {formatRange(row.start_date, row.end_date)}
              <SourceBadge row={row} />
            </h3>
            <p className="text-[13px] text-muted-foreground">
              {[
                name,
                row.department,
                daysLabel(row.days_total),
                row.half_day ? HALF_DAY_LABELS[row.half_day] : null,
                viewerIsHr && row.manager_name ? `koordynator: ${row.manager_name}` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {row.as_substitute_for ? (
              <p className="text-[13px] text-muted-foreground">
                w zastępstwie za {row.as_substitute_for}
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">{actions}</div>
      </div>

      {row.note ? <p className="text-sm text-foreground">„{row.note}”</p> : null}
      <ApproverProofNote row={row} />
      {row.conflict ? (
        <p className="text-sm text-warning-muted-foreground">
          Kolizja zgłoszona{row.conflict.by_name ? ` · ${row.conflict.by_name}` : ""}:{" "}
          {row.conflict.note}
        </p>
      ) : null}

      <div className="grid gap-2.5 sm:grid-cols-3">
        <div className="rounded-lg bg-muted/50 p-3">
          <div className={LABEL}>Zastępca</div>
          {row.substitute_name ? (
            <>
              <div className="mt-1.5 font-medium text-foreground">{row.substitute_name}</div>
              <div
                className={cn(
                  "mt-1 text-xs",
                  subAbsent ? "text-warning-muted-foreground" : "text-muted-foreground",
                )}
              >
                {subAbsent ? "też nieobecny w tym czasie" : "zastępuje w tym terminie"}
              </div>
            </>
          ) : (
            <div className="mt-1.5 text-sm text-muted-foreground">bez zastępcy</div>
          )}
        </div>
        <div className="rounded-lg bg-muted/50 p-3">
          <div className={LABEL}>Wypada w tym czasie</div>
          <div className="mt-1.5 text-[13px] text-foreground">
            {work ?? <span className="text-muted-foreground">nic z kalendarza pracy</span>}
          </div>
        </div>
        <div
          className={cn(
            "rounded-lg p-3",
            row.department_absent.length > 0 ? "bg-warning-muted/60" : "bg-muted/50",
          )}
        >
          <div
            className={cn(
              LABEL,
              row.department_absent.length > 0 && "text-warning-muted-foreground",
            )}
          >
            Też nieobecni
          </div>
          {row.department_absent.length > 0 ? (
            <ul className="mt-1.5 space-y-0.5 text-[13px] text-foreground">
              {row.department_absent.map((other) => (
                <li key={`${other.user_id}-${other.start_date}`}>
                  <b className="font-semibold">{other.name}</b>{" "}
                  {dayMonthRange(other.start_date, other.end_date)}
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-1.5 text-[13px] text-muted-foreground">nikt z działu</div>
          )}
        </div>
      </div>

      <div>
        <div className={cn(LABEL, "mb-1.5")}>Zespół w tym terminie</div>
        <div className="relative overflow-x-auto rounded-lg border border-border/60 px-2.5 py-2">
          <div
            role="table"
            aria-label="Zespół w tym terminie"
            className="min-w-[480px] text-xs"
          >
            <div
              role="row"
              className="grid items-center text-center text-[11px] text-muted-foreground"
              style={{ gridTemplateColumns: `150px repeat(${days.length}, minmax(0, 1fr))` }}
            >
              <span role="columnheader">
                <span className="sr-only">Osoba</span>
              </span>
              {days.map((day) => (
                <span key={day} role="columnheader">
                  {formatWeekdayDayPl(day).slice(0, -3)}
                </span>
              ))}
            </div>
            {rows.map((line) => (
              <div
                key={line.key}
                role="row"
                className="grid items-center"
                style={{ gridTemplateColumns: `150px repeat(${days.length}, minmax(0, 1fr))` }}
              >
                <span
                  role="rowheader"
                  className={cn("truncate text-[13px] text-foreground", line.self && "font-semibold")}
                >
                  {line.name}
                </span>
                {line.cells.map((cell, index) => (
                  <span
                    key={days[index]}
                    role="cell"
                    aria-label={
                      cell === "none"
                        ? undefined
                        : `${line.name}: ${cell === "pending" ? "wniosek czeka" : "nieobecność"} ${formatWeekdayDayPl(days[index])}`
                    }
                    className={cn(
                      "m-0.5 h-[22px] rounded-[5px]",
                      cell === "absent" && "bg-primary/25",
                      cell === "pending" && "border-[1.5px] border-dashed border-primary/60 bg-card",
                    )}
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <RejectLeaveDialog
        request={rejecting}
        onClose={(rejected) => {
          setRejecting(null);
          if (rejected) showToast("Wniosek odrzucony", "success");
        }}
      />
      <ReportConflictDialog
        request={conflicting}
        onClose={(done) => {
          setConflicting(null);
          if (done) showToast("Kolizja zgłoszona — osoba dostała powiadomienie", "success");
        }}
      />
      <EditLeaveDialog
        request={editing}
        onClose={(saved) => {
          setEditing(null);
          if (saved) showToast(...leaveToast(item.kind === "info" ? "Zgłoszenie zmienione" : "Wniosek zmieniony", saved));
        }}
      />
    </section>
  );
}

const SLICE: Record<QueueStatus, string> = {
  draft: "bg-muted-foreground/40",
  missing: "bg-warning",
  submitted: "bg-info",
  approved: "bg-success",
};

/**
 * Podsumowanie statusów timesheetów (pasek złożony + liczby) za miesiąc, od
 * którego otwiera się sekcja „Timesheety” — ta sama kolejka i ten sam klucz
 * zapytania, więc bez drugiego żądania.
 */
function TimesheetSummary({ config, period }: { config: HrConfig; period: YearMonth }) {
  const canApprove =
    config.me.is_admin ||
    config.me.people_admin ||
    config.me.is_manager ||
    (config.me.covering?.length ?? 0) > 0;
  const queue = useTeamQueue(period.year, period.month, config.open_modules.time && canApprove);
  if (!queue.isSuccess) return null;
  const slices = timesheetSummary(queue.data.items);
  if (slices.length === 0) return null;
  const total = slices.reduce((sum, slice) => sum + slice.count, 0);
  const text = timesheetSummaryText(slices);
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs" data-testid="timesheet-summary">
      <span className="font-medium text-foreground">{monthTitlePl(period)}:</span>
      <div
        role="img"
        aria-label={`Timesheety, ${monthTitlePl(period).toLowerCase()}: ${text}`}
        className="flex h-2 w-[220px] overflow-hidden rounded-full bg-muted"
      >
        {slices.map((slice) => (
          <span
            key={slice.status}
            className={SLICE[slice.status]}
            style={{ width: `${(slice.count / total) * 100}%` }}
          />
        ))}
      </div>
      <span className="text-muted-foreground">{text}</span>
    </div>
  );
}

/** „Historia wniosków” zwinięta do linku — filtry i akcje dopiero po rozwinięciu. */
function HistoryToggle({ viewerIsHr }: { viewerIsHr: boolean }) {
  const [open, setOpen] = useState(false);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="space-y-2" data-help="hr.approvals.history">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
      >
        Historia wniosków
        <Icon className="h-4 w-4" aria-hidden />
      </button>
      {open ? <LeaveHistory viewerIsHr={viewerIsHr} /> : null}
    </div>
  );
}

const STATUS_FILTERS: { value: LeaveStatus | "all"; label: string }[] = [
  { value: "all", label: "Wszystkie statusy" },
  { value: "pending", label: LEAVE_STATUS_LABELS.pending },
  { value: "approved", label: "Zatwierdzone i zgłoszone" },
  { value: "rejected", label: LEAVE_STATUS_LABELS.rejected },
  { value: "cancelled", label: LEAVE_STATUS_LABELS.cancelled },
];

function LeaveHistory({ viewerIsHr }: { viewerIsHr: boolean }) {
  const [status, setStatus] = useState<LeaveStatus | "all">("all");
  const [person, setPerson] = useState("all");
  const people = useOnBehalfPeople();
  const history = useLeaveHistory({
    status: status === "all" ? null : status,
    user_id: person === "all" ? null : Number(person),
  });
  const cancel = useCancelTeamLeave();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [editing, setEditing] = useState<LeaveRequestRow | null>(null);
  const [forwardOff, setForwardOff] = useState<LeaveRequestRow | null>(null);
  const rows = history.data?.items ?? [];
  const counts = history.data?.counts;
  const state = resolveViewState({
    isLoading: history.isLoading,
    isError: history.isError,
    error: history.error,
    isSuccess: history.isSuccess,
    isEmpty: rows.length === 0,
  });

  const cancelRow = async (row: LeaveRequestRow) => {
    const ok = await askConfirm({
      title: "Anulować nieobecność?",
      description: `${row.user_name ?? "Osoba"} · ${formatRange(row.start_date, row.end_date)}. Osoba i zastępca dostaną powiadomienie, a autoodpowiedź zostanie zdjęta.`,
      confirmLabel: "Anuluj nieobecność",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(row.id, {
      onSuccess: (saved) => showToast(...leaveToast("Nieobecność anulowana", saved)),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
    });
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Wszystkie wnioski</h2>
        <div className="ml-auto flex flex-wrap gap-2">
          <Select value={status} onValueChange={(value) => setStatus(value as LeaveStatus | "all")}>
            <SelectTrigger className="h-8 w-[240px]" aria-label="Status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {statusFilterLabel(option.label, option.value, counts)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={person} onValueChange={setPerson}>
            <SelectTrigger className="h-8 w-[220px]" aria-label="Osoba">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Wszystkie osoby</SelectItem>
              {(people.data ?? []).map((row) => (
                <SelectItem key={row.user_id} value={String(row.user_id)}>
                  {row.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {state === "loading" ? (
        <p className="py-4 text-sm text-muted-foreground">Wczytywanie historii…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => history.refetch()} />
      ) : state === "empty" ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Brak wniosków dla tych filtrów.
        </p>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Kto</TableHead>
                <TableHead className={CALM_HEAD}>Rodzaj</TableHead>
                <TableHead className={CALM_HEAD}>Termin</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Dni</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                <TableHead className={CALM_HEAD}>
                  <span className="sr-only">Akcje</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} h-[48px]`}>
                  <TableCell className="font-medium text-foreground">
                    {row.user_name}
                    <SourceBadge row={row} />
                  </TableCell>
                  <TableCell>
                    {row.leave_type_label}
                    <ApproverProofNote row={row} />
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatRange(row.start_date, row.end_date)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums">
                    {daysLabel(row.days_total)}
                  </TableCell>
                  <TableCell>
                    <StatusDot
                      tone={LEAVE_STATUS_TONE[row.status]}
                      note={
                        row.decision_note ??
                        (row.decided_by_name ? `decyzja: ${row.decided_by_name}` : undefined)
                      }
                    >
                      {statusLabel(row)}
                    </StatusDot>
                  </TableCell>
                  <TableCell className="text-right">
                    {/* Zgłoszenie z B2B/zlecenia zmienia i anuluje osoba albo Kadry — nie koordynator (D5). */}
                    {canEditRow(row, viewerIsHr) ? (
                      <div className="flex justify-end gap-1.5">
                        <Button size="sm" variant="quiet" onClick={() => setEditing(row)}>
                          Edytuj
                        </Button>
                        {viewerIsHr &&
                        row.forward_mail_consent &&
                        forwardStillAhead(row.end_date) ? (
                          <Button size="sm" variant="quiet" onClick={() => setForwardOff(row)}>
                            Wyłącz przekierowanie
                          </Button>
                        ) : null}
                        <Button
                          size="sm"
                          variant="quiet"
                          disabled={cancel.isPending}
                          onClick={() => void cancelRow(row)}
                        >
                          Anuluj
                        </Button>
                      </div>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {historyCapNote(rows.length, status, counts) ? (
        <p className="px-1 text-xs text-muted-foreground">
          {historyCapNote(rows.length, status, counts)}
        </p>
      ) : null}
      {confirmDialog}
      <EditLeaveDialog
        request={editing}
        onClose={(saved) => {
          setEditing(null);
          if (saved) showToast(...leaveToast("Wniosek zmieniony", saved));
        }}
      />
      <ForwardOffDialog
        target={forwardOff}
        onClose={(done) => {
          setForwardOff(null);
          if (done) showToast("Przekierowanie wyłączone — reguła zostanie zamknięta", "success");
        }}
      />
    </div>
  );
}

/**
 * „Ludzie → Akceptacje” (makieta 19.10.2026): skrzynka wniosków i zgłoszeń
 * (lista + szczegół), timesheety z podsumowaniem statusów, „Historia
 * wniosków” zwinięta do linku i wpis nieobecności za pracownika.
 */
function LeaveAndTimeApprovals({ config }: { config: HrConfig }) {
  const params = useSearchParams();
  const pending = usePendingLeave(config.open_modules.leave);
  const covering = useLeaveCovering(config.open_modules.leave);
  const [entering, setEntering] = useState(false);
  const viewerIsHr = config.me.people_admin || config.me.is_admin;

  const timesheetViewer =
    config.me.is_manager ||
    (config.me.covering?.length ?? 0) > 0 ||
    config.me.people_admin ||
    config.me.payroll ||
    config.me.is_admin;
  const showTimesheets = config.open_modules.time && timesheetViewer;
  const focusUser = Number(params.get("user"));
  const initialMonth = yearMonthFromParams(params);
  const timesheets = showTimesheets ? (
    <section
      key="timesheets"
      aria-label="Timesheety"
      className="space-y-3 rounded-xl border border-border bg-card p-4"
    >
      <TimesheetSummary config={config} period={initialMonth ?? defaultQueueMonth()} />
      <TimesheetApprovalsSection
        config={config}
        initialMonth={initialMonth}
        focusUserId={Number.isInteger(focusUser) && focusUser > 0 ? focusUser : null}
      />
    </section>
  ) : null;
  const inbox = config.open_modules.leave ? (
    <section key="leave" aria-label="Wnioski i zgłoszenia" className="space-y-2">
      <LeaveInbox viewerIsHr={viewerIsHr} />
    </section>
  ) : null;
  // Link z powiadomienia o timesheecie otwiera kolejkę od timesheetów.
  const sections =
    params.get("kind") === "timesheet" ? [timesheets, inbox] : [inbox, timesheets];

  const waiting = pending.data?.length ?? null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <InlineStats
          stats={[
            {
              id: "waiting",
              // Licznik wniosków (umowa o pracę); zgłoszenia z B2B i zlecenia się
              // nie liczą (D5), timesheety mają własny stan w swojej sekcji.
              label: "wnioski do decyzji",
              value: waiting === null ? "—" : waiting,
            },
            {
              id: "scope",
              label: viewerIsHr ? "zakres" : "mój zespół",
              value: viewerIsHr
                ? "wszyscy"
                : countPl(config.me.direct_reports, "osoba", "osoby", "osób"),
            },
          ]}
        />
        {config.open_modules.leave ? (
          <Button
            className="ml-auto h-auto min-h-9 max-w-full whitespace-normal py-1.5 text-left"
            variant="outline"
            data-help="hr.approvals.on_behalf"
            onClick={() => setEntering(true)}
          >
            <CalendarPlus className="h-4 w-4" aria-hidden />
            Wpisz nieobecność za konsultanta/kontraktora
          </Button>
        ) : null}
      </div>

      {covering.data && covering.data.length > 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="approvals-covering">
          {covering.data
            .map((cover) => `W zastępstwie za ${cover.manager_name} do ${formatWeekdayDayPl(cover.until)}`)
            .join(" · ")}
          {" — decydujesz o wnioskach i timesheetach zastępowanego zespołu; L4 i pokrewne tylko do wiadomości."}
        </p>
      ) : null}

      {!inbox && !timesheets ? (
        <p className="text-sm text-muted-foreground">
          Akceptacje ruszą po włączeniu modułu urlopów albo czasu pracy.
        </p>
      ) : (
        sections
      )}

      {config.open_modules.leave ? <HistoryToggle viewerIsHr={viewerIsHr} /> : null}

      <LeaveRequestDialog open={entering} onOpenChange={setEntering} mode="on_behalf" />
    </div>
  );
}

type ApprovalsTab = "consents" | "leave";

/**
 * „Ludzie → Akceptacje” z modułem „Zgody” (0483, 20.10.2026): przełącznik
 * „Zgody | Urlopy i timesheety”. Link z powiadomienia o zgodzie niesie
 * `?tab=consents`; bez urlopu i czasu zostają same zgody.
 */
export function ApprovalsScreen({ config }: { config: HrConfig }) {
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const counts = useHrCounts(config.open_modules.approvals);
  const leaveOpen = config.open_modules.leave || config.open_modules.time;
  const consentsOpen = config.open_modules.approvals;
  const [tab, setTab] = useState<ApprovalsTab>(
    !leaveOpen || params.get("tab") === "consents" ? "consents" : "leave",
  );
  if (!consentsOpen) return <LeaveAndTimeApprovals config={config} />;
  if (!leaveOpen) return <ConsentsInbox />;

  const current = counts.isSuccess ? counts.data : undefined;
  const withCount = (label: string, value: number | null | undefined) =>
    typeof value === "number" && value > 0 ? `${label} · ${value}` : label;
  return (
    <div className="space-y-4">
      <SegmentedRadio
        label="Co akceptujesz"
        value={tab}
        onChange={(value) => {
          setTab(value);
          replaceUrl(value === "consents" ? "?tab=consents" : "?");
        }}
        options={[
          { value: "consents", label: withCount("Zgody", current?.consents) },
          { value: "leave", label: withCount("Urlopy i timesheety", current?.approvals) },
        ]}
      />
      {tab === "consents" ? <ConsentsInbox /> : <LeaveAndTimeApprovals config={config} />}
    </div>
  );
}
