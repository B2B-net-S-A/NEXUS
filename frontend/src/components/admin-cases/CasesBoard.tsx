"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  FileText,
  History,
  LogOut,
  Mail,
  PenLine,
  Plus,
  Search,
  type LucideIcon,
} from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { personInitials } from "@/components/hr/people/hr-format";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CASE_AREAS,
  CASE_AREA_LABELS,
  CASE_SOURCE_LABELS,
  CASE_STATUS_LABELS,
  useCases,
  useTakeCase,
  type CaseArea,
  type CaseCard,
  type CaseStatus,
} from "@/lib/api/admin-cases";
import type { HrConfig } from "@/lib/api/hr";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { CaseFormDialog } from "./CaseFormDialog";
import {
  PRIORITY_DOT,
  SOURCE_ICON,
  caseSubline,
  dueBadge,
  groupByStatus,
  type DueTone,
} from "./case-format";

const MODULE_OFF_NOTICE =
  "Moduł „Sprawy administracja@” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";
/** Otwarte kolumny tablicy; „Zrobione” to wąska kolumna obok. */
const OPEN_COLUMNS: readonly CaseStatus[] = ["new", "in_progress", "waiting"];
const ALL_COLUMNS: readonly CaseStatus[] = [...OPEN_COLUMNS, "done", "closed"];
const DONE_PREVIEW = 5;

const ICONS: Record<(typeof SOURCE_ICON)[keyof typeof SOURCE_ICON], LucideIcon> = {
  mail: Mail,
  contract: FileText,
  exit: LogOut,
  manual: PenLine,
  import: History,
};

const DUE_VARIANT: Record<DueTone, "danger" | "warning" | "neutral" | null> = {
  overdue: "danger",
  week: "warning",
  later: "neutral",
  none: null,
};

type Scope = "mine" | "all";

function Chip({
  active,
  onClick,
  children,
  tone,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  tone?: "danger";
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[13px] font-medium transition-colors",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-muted",
        !active && tone === "danger" && "text-destructive",
      )}
    >
      {children}
    </button>
  );
}

function CaseTile({
  card,
  today,
  weekEnd,
  onOpen,
  onTake,
  taking,
}: {
  card: CaseCard;
  today?: string;
  weekEnd?: string;
  onOpen: () => void;
  onTake: (() => void) | null;
  taking: boolean;
}) {
  const due = dueBadge(card, today, weekEnd);
  const subline = caseSubline(card);
  const Icon = ICONS[SOURCE_ICON[card.source]];
  const progress = card.checklist_total
    ? Math.round((card.checklist_done / card.checklist_total) * 100)
    : null;
  const dueVariant = due ? DUE_VARIANT[due.tone] : null;
  return (
    <li
      className="flex flex-col gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-sm shadow-xs"
      aria-label={card.title}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground">
          <Icon className="h-3.5 w-3.5" aria-hidden />
          {CASE_SOURCE_LABELS[card.source]}
        </span>
        {due && dueVariant ? (
          <Badge size="sm" variant={dueVariant} className="h-auto py-0.5">
            {due.text}
          </Badge>
        ) : due ? (
          <span className="text-[11.5px] text-muted-foreground">{due.text}</span>
        ) : null}
      </div>
      <div className="flex items-start gap-1.5">
        <span
          className={cn("mt-1.5 size-2 shrink-0 rounded-full", PRIORITY_DOT[card.priority])}
          title={card.priority}
        >
          <span className="sr-only">{card.priority}</span>
        </span>
        <div className="min-w-0">
          <button
            type="button"
            onClick={onOpen}
            aria-label={`Sprawa: ${card.title}`}
            className="line-clamp-2 text-left font-semibold text-foreground hover:underline"
          >
            {card.title}
          </button>
          <p className="truncate text-xs text-muted-foreground">
            {[
              subline,
              card.contract ? "kontrakt w NEXUSIE" : null,
              CASE_AREA_LABELS[card.area].toLowerCase(),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>
      {card.follow_up_on && card.status === "waiting" ? (
        <p className="rounded-md bg-muted/60 px-2 py-1 text-xs">
          odezwać się <span className="font-semibold">{formatDayMonthPl(card.follow_up_on)}</span>
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        {progress != null ? (
          <>
            <div
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-border"
              role="progressbar"
              aria-valuenow={card.checklist_done}
              aria-valuemin={0}
              aria-valuemax={card.checklist_total}
              aria-label={`Lista kontrolna: ${card.checklist_done} z ${card.checklist_total}`}
            >
              <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
            </div>
            <span className="text-[11.5px] tabular-nums text-muted-foreground">
              {card.checklist_done}/{card.checklist_total}
            </span>
          </>
        ) : (
          <span className="flex-1" />
        )}
        {card.assignee ? (
          <span
            title={card.assignee.name ?? undefined}
            className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
          >
            <span aria-hidden>{personInitials(card.assignee.name ?? "")}</span>
            <span className="sr-only">{card.assignee.name}</span>
          </span>
        ) : onTake ? (
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5"
            disabled={taking}
            onClick={onTake}
            aria-label={`Weź sprawę: ${card.title}`}
          >
            Weź
          </Button>
        ) : (
          <span className="shrink-0 text-xs text-muted-foreground">bez osoby</span>
        )}
      </div>
    </li>
  );
}

function DoneColumn({
  done,
  closed,
  doneThisMonth,
  showClosed,
  onToggleClosed,
  onOpen,
}: {
  done: CaseCard[];
  closed: CaseCard[];
  doneThisMonth: number;
  showClosed: boolean;
  onToggleClosed: () => void;
  onOpen: (card: CaseCard) => void;
}) {
  const [all, setAll] = useState(false);
  const visible = all ? done : done.slice(0, DONE_PREVIEW);
  const row = (card: CaseCard) => (
    <li key={card.id}>
      <button
        type="button"
        onClick={() => onOpen(card)}
        aria-label={`Sprawa: ${card.title}`}
        className="flex w-full items-start gap-1.5 rounded-md bg-card px-2 py-1.5 text-left text-[12.5px] hover:bg-muted"
      >
        <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
        <span className="line-clamp-2">{card.title}</span>
      </button>
    </li>
  );
  return (
    <section
      aria-labelledby="cases-col-done"
      className="flex min-w-0 flex-col gap-2 rounded-xl border border-dashed border-border bg-muted/30 p-2.5"
    >
      <div className="flex items-center justify-between px-1">
        <h3 id="cases-col-done" className="text-[13.5px] font-semibold">
          {CASE_STATUS_LABELS.done}
        </h3>
        <Badge size="sm" variant="success" className="tabular-nums" title="Zrobione w tym miesiącu">
          {doneThisMonth}
        </Badge>
      </div>
      <p className="px-1 text-xs text-muted-foreground">
        {doneThisMonth} w tym miesiącu · na tablicy ostatnie 30 dni
      </p>
      {visible.length ? <ul className="flex flex-col gap-1">{visible.map(row)}</ul> : null}
      {done.length > DONE_PREVIEW ? (
        <button
          type="button"
          className="self-start px-1 text-[12.5px] text-primary hover:underline"
          onClick={() => setAll((value) => !value)}
        >
          {all ? "Zwiń" : `Pokaż wszystkie (${done.length})`}
        </button>
      ) : null}
      {showClosed ? (
        <>
          <h3 className="px-1 pt-1 text-[13px] font-semibold">{CASE_STATUS_LABELS.closed}</h3>
          {closed.length ? (
            <ul className="flex flex-col gap-1">{closed.map(row)}</ul>
          ) : (
            <p className="px-1 text-xs text-muted-foreground">Brak zamkniętych.</p>
          )}
        </>
      ) : null}
      <button
        type="button"
        aria-pressed={showClosed}
        className="self-start px-1 text-[12.5px] text-muted-foreground hover:text-foreground hover:underline"
        onClick={onToggleClosed}
      >
        Pokaż zamknięte
      </button>
    </section>
  );
}

/**
 * Tablica spraw administracja@ (makieta 19.10.2026): chipy obszarów z liczbą,
 * „Na ten tydzień” i „Bez osoby” (filtry serwera — lista ma limit), termin
 * w kolorze, ikona źródła, kropka priorytetu, pasek listy kontrolnej,
 * „Weź” na sprawie bez osoby i wąska kolumna „Zrobione”.
 */
export function CasesBoard({ config }: { config: HrConfig }) {
  const router = useRouter();
  const { showToast } = useToast();
  const me = useAuthStore((s) => s.user?.id ?? null);
  const canManageFromConfig = config.me.cases || config.me.is_admin;
  const [scope, setScope] = useState<Scope>(canManageFromConfig ? "all" : "mine");
  const [area, setArea] = useState<CaseArea | null>(null);
  const [week, setWeek] = useState(false);
  const [unassigned, setUnassigned] = useState(false);
  const [query, setQuery] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [creating, setCreating] = useState(false);
  const take = useTakeCase();

  const cases = useCases({
    mine: scope === "mine",
    area,
    q: query,
    include_closed: showClosed,
    week,
    unassigned,
  });
  const items = useMemo(() => cases.data?.items ?? [], [cases.data]);
  const grouped = useMemo(() => groupByStatus(items, ALL_COLUMNS), [items]);
  const canManage = cases.data?.can_manage ?? canManageFromConfig;
  const counts = cases.data?.counts;

  const state = resolveViewState({
    isLoading: cases.isLoading,
    isError: cases.isError,
    error: cases.error,
    isSuccess: cases.isSuccess,
    isEmpty: items.length === 0,
  });

  if (state === "not_found") {
    return <QueryStateNotice state="not_found" description={MODULE_OFF_NOTICE} />;
  }
  if (state === "forbidden") {
    return (
      <QueryStateNotice
        state="forbidden"
        description="Sprawy widzą osoby z uprawnieniem „Sprawy” i osoby przypisane do sprawy."
      />
    );
  }

  const takeCase = (card: CaseCard) => {
    if (me == null) return;
    take.mutate(
      { id: card.id, userId: me, expectedUpdatedAt: card.updated_at },
      {
        onSuccess: () => showToast("Sprawa jest Twoja", "success"),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się wziąć sprawy."), "error"),
      },
    );
  };
  const areaChips = CASE_AREAS.filter((key) => (counts?.areas[key] ?? 0) > 0 || key === area);
  const filtered = Boolean(query.trim() || area || week || unassigned);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {canManage ? (
          <SegmentedRadio
            label="Zakres spraw"
            size="sm"
            value={scope}
            onChange={setScope}
            options={[
              { value: "mine", label: "Moje" },
              { value: "all", label: "Wszystkie" },
            ]}
          />
        ) : null}
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Obszar">
          <Chip active={area === null} onClick={() => setArea(null)}>
            Wszystkie obszary
          </Chip>
          {areaChips.map((key) => (
            <Chip key={key} active={area === key} onClick={() => setArea(area === key ? null : key)}>
              {CASE_AREA_LABELS[key]}{" "}
              <span className="tabular-nums opacity-70">{counts?.areas[key] ?? 0}</span>
            </Chip>
          ))}
        </div>
        <span aria-hidden className="h-6 w-px bg-border" />
        <Chip active={week} onClick={() => setWeek((v) => !v)} tone="danger">
          Na ten tydzień{" "}
          {counts ? <span className="tabular-nums opacity-70">{counts.week}</span> : null}
        </Chip>
        {canManage ? (
          <Chip active={unassigned} onClick={() => setUnassigned((v) => !v)}>
            Bez osoby{" "}
            {counts ? <span className="tabular-nums opacity-70">{counts.unassigned}</span> : null}
          </Chip>
        ) : null}
        <div className="relative ml-auto w-full sm:w-56">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj sprawy"
            placeholder="Szukaj w tytule i opisie…"
            className="h-8 pl-8"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {canManage ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            Nowa sprawa
          </Button>
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie spraw…</p>
      ) : state === "error" ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać spraw."
          onRetry={() => cases.refetch()}
        />
      ) : (
        <>
          {state === "empty" ? (
            <p className="text-sm text-muted-foreground">
              {filtered
                ? "Żadna sprawa nie pasuje do filtrów."
                : scope === "mine"
                  ? "Nie masz przypisanych spraw."
                  : "Nie ma otwartych spraw."}
            </p>
          ) : null}
          <div
            className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(3,minmax(0,1fr))_200px]"
            aria-label="Sprawy według statusu"
            role="group"
          >
            {OPEN_COLUMNS.map((status) => (
              <section
                key={status}
                aria-labelledby={`cases-col-${status}`}
                className="flex min-w-0 flex-col gap-2 rounded-xl bg-muted/70 p-2.5"
              >
                <div className="flex items-center justify-between px-1">
                  <h3 id={`cases-col-${status}`} className="text-[13.5px] font-semibold">
                    {CASE_STATUS_LABELS[status]}
                  </h3>
                  <Badge size="sm" variant="neutral" className="tabular-nums">
                    {grouped[status].length}
                  </Badge>
                </div>
                <ul className="flex flex-col gap-2">
                  {grouped[status].map((card) => (
                    <CaseTile
                      key={card.id}
                      card={card}
                      today={cases.data?.today}
                      weekEnd={cases.data?.week_end}
                      onOpen={() => router.push(`/people/cases/${card.id}`)}
                      onTake={canManage && me != null ? () => takeCase(card) : null}
                      taking={take.isPending}
                    />
                  ))}
                </ul>
              </section>
            ))}
            <DoneColumn
              done={grouped.done}
              closed={grouped.closed}
              doneThisMonth={cases.data?.done_this_month ?? 0}
              showClosed={showClosed}
              onToggleClosed={() => setShowClosed((value) => !value)}
              onOpen={(card) => router.push(`/people/cases/${card.id}`)}
            />
          </div>
          {cases.data?.truncated ? (
            <p className="text-xs text-muted-foreground">
              Pokazujemy 500 spraw — zawęź obszar albo wyszukiwanie.
            </p>
          ) : null}
        </>
      )}

      {canManage && creating ? (
        <CaseFormDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(id) => router.push(`/people/cases/${id}`)}
        />
      ) : null}
    </div>
  );
}
