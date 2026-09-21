"use client";

/**
 * Prezentacyjna połowa panelu „Moi ludzie" — bez zapytań i bez stanu
 * serwera. Kontener (`MyPeoplePanel`) podaje dane i akcje; harness
 * `/preview/my-people` renderuje te same widoki na danych fikcyjnych.
 */

import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  BellRing,
  BriefcaseBusiness,
  ChevronDown,
  ChevronRight,
  Moon,
  Pin,
  RotateCcw,
  UserPlus,
} from "lucide-react";

import type { ForJobResponse, ForJobRow, MyPeopleRow, SnoozeReason } from "@/lib/api/myPeople";
import { SNOOZE_REASON_LABELS } from "@/lib/api/myPeople";
import {
  daysAgoLabel,
  furthestStageLabel,
  groupByCategory,
  plural,
  type PeopleGroup,
} from "@/lib/my-people-summary";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import { MatchScoreBadge } from "@/components/ds/MatchScoreBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const GROUP_PREVIEW = 8;

export interface RowActions {
  onAdd?: (row: { candidate_id: number; full_name: string }) => void;
  onSnooze?: (candidateId: number, reason: SnoozeReason) => void;
  onUnsnooze?: (candidateId: number) => void;
  busyIds?: ReadonlySet<number>;
}

function formatRate(rate: number | null): string | null {
  if (rate == null) return null;
  return `${Math.round(rate)} zł/h`;
}

function SnoozeMenu({
  candidateId,
  name,
  onSnooze,
  disabled,
}: {
  candidateId: number;
  name: string;
  onSnooze: NonNullable<RowActions["onSnooze"]>;
  disabled?: boolean;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Uśpij: ${name}`}
          title="Uśpij"
          disabled={disabled}
        >
          <Moon className="h-4 w-4" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Dlaczego usypiasz?</DropdownMenuLabel>
        {(Object.keys(SNOOZE_REASON_LABELS) as SnoozeReason[]).map((reason) => (
          <DropdownMenuItem key={reason} onSelect={() => onSnooze(candidateId, reason)}>
            {SNOOZE_REASON_LABELS[reason]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function PersonRowView({ row, actions }: { row: MyPeopleRow; actions: RowActions }) {
  const busy = actions.busyIds?.has(row.candidate_id) ?? false;
  const stage = furthestStageLabel(row.furthest_stage);
  const ago = daysAgoLabel(row.days_since_last_send);
  const rate = formatRate(row.expected_rate_hourly);
  return (
    <li className="flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-muted/60">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <Link
            href={`/candidates/${row.candidate_id}`}
            className="truncate text-sm font-medium text-foreground hover:underline"
          >
            {row.full_name}
          </Link>
          {row.source === "pinned" ? (
            <Pin className="h-3 w-3 text-muted-foreground" aria-label="Przypięty ręcznie" />
          ) : null}
          {row.new_matches > 0 ? (
            <Badge size="sm" variant="soft" className="gap-1">
              <BellRing className="h-3 w-3" aria-hidden />
              {row.new_matches} {plural(row.new_matches, "nowa rekrutacja", "nowe rekrutacje", "nowych rekrutacji")}
            </Badge>
          ) : null}
          {row.active_processes > 0 ? (
            <Badge size="sm" variant="neutral">
              w procesie: {row.active_processes}
            </Badge>
          ) : null}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {[
            stage,
            row.last_sent_client_name ? `ostatnio: ${row.last_sent_client_name}` : null,
            ago,
            rate,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {row.snoozed && row.snooze_reason ? (
          <p className="mt-0.5 text-xs text-muted-foreground">
            Uśpiony: {SNOOZE_REASON_LABELS[row.snooze_reason] ?? row.snooze_reason}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {row.snoozed ? (
          actions.onUnsnooze ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Przywróć: ${row.full_name}`}
              title="Przywróć na listę"
              disabled={busy}
              onClick={() => actions.onUnsnooze?.(row.candidate_id)}
            >
              <RotateCcw className="h-4 w-4" aria-hidden />
            </Button>
          ) : null
        ) : (
          <>
            {actions.onAdd && !row.working ? (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Dodaj do rekrutacji: ${row.full_name}`}
                title="Dodaj do rekrutacji"
                disabled={busy}
                onClick={() => actions.onAdd?.(row)}
              >
                <UserPlus className="h-4 w-4" aria-hidden />
              </Button>
            ) : null}
            {actions.onSnooze ? (
              <SnoozeMenu
                candidateId={row.candidate_id}
                name={row.full_name}
                onSnooze={actions.onSnooze}
                disabled={busy}
              />
            ) : null}
          </>
        )}
      </div>
    </li>
  );
}

function CollapsibleGroup({
  group,
  actions,
  defaultOpen = true,
}: {
  group: PeopleGroup;
  actions: RowActions;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? group.rows : group.rows.slice(0, GROUP_PREVIEW);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <section aria-label={group.label}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-md px-1 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
      >
        <Icon className="h-3.5 w-3.5" aria-hidden />
        <span className="flex-1">{group.label}</span>
        <span className="tabular-nums">{group.rows.length}</span>
      </button>
      {open ? (
        <>
          <ul className="space-y-0.5">
            {shown.map((row) => (
              <PersonRowView key={row.candidate_id} row={row} actions={actions} />
            ))}
          </ul>
          {group.rows.length > GROUP_PREVIEW ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="ml-2 mt-1 text-xs font-medium text-primary hover:underline"
            >
              {expanded ? "Pokaż mniej" : `Pokaż wszystkich (${group.rows.length})`}
            </button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

export function PeopleListView({
  active,
  working,
  snoozed,
  categories,
  actions,
  truncated,
}: {
  active: MyPeopleRow[];
  working: MyPeopleRow[];
  snoozed: MyPeopleRow[];
  categories: { id: number; name_pl: string }[];
  actions: RowActions;
  truncated?: boolean;
}) {
  const groups = groupByCategory(active, categories);
  return (
    <div className="space-y-3">
      {truncated ? (
        <p className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Lista jest bardzo długa — pokazujemy pierwsze 2000 osób.
        </p>
      ) : null}
      {groups.map((group) => (
        <CollapsibleGroup key={group.key} group={group} actions={actions} />
      ))}
      {working.length ? (
        <CollapsibleGroup
          group={{ key: "working", categoryId: null, label: "Pracują", rows: working }}
          actions={{ ...actions, onAdd: undefined }}
          defaultOpen={false}
        />
      ) : null}
      {snoozed.length ? (
        <CollapsibleGroup
          group={{ key: "snoozed", categoryId: null, label: "Uśpieni", rows: snoozed }}
          actions={actions}
          defaultOpen={false}
        />
      ) : null}
    </div>
  );
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function ForJobRowView({ row, actions }: { row: ForJobRow; actions: RowActions }) {
  const busy = actions.busyIds?.has(row.candidate_id) ?? false;
  const sentHere = formatDate(row.sent_to_client_at);
  const incomplete = row.score == null;
  return (
    <li className="flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-muted/60">
      <MatchScoreBadge
        score={row.score}
        emptyLabel={row.measurement === "not_in_pool" ? "Nie liczono" : "Ocena niepełna"}
        className="mt-0.5 shrink-0"
      />
      <div className="min-w-0 flex-1">
        <Link
          href={`/candidates/${row.candidate_id}`}
          className="truncate text-sm font-medium text-foreground hover:underline"
        >
          {row.full_name}
        </Link>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {[
            sentHere ? `wysłany do tego klienta ${sentHere}` : null,
            row.active_processes > 0 ? `w procesie: ${row.active_processes}` : null,
            formatRate(row.expected_rate_hourly),
          ]
            .filter(Boolean)
            .join(" · ") || (incomplete ? "Brak wektora albo spoza najbliższych — wynik niepoliczony." : "")}
        </p>
        {row.eligibility ? (
          <span
            className={cn(
              "mt-1 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px]",
              eligibilityBadgeClass(row.eligibility),
            )}
          >
            <AlertTriangle className="h-3 w-3" aria-hidden />
            {row.eligibility.reason}
          </span>
        ) : null}
      </div>
      {actions.onAdd ? (
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          disabled={busy || row.eligibility?.assignment_allowed === false}
          aria-label={`Dodaj do tej rekrutacji: ${row.full_name}`}
          onClick={() => actions.onAdd?.(row)}
        >
          Dodaj
        </Button>
      ) : null}
    </li>
  );
}

export function ForJobView({ data, actions }: { data: ForJobResponse; actions: RowActions }) {
  const scored = data.rows.filter((r) => r.score != null);
  const rest = data.rows.filter((r) => r.score == null);
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        <BriefcaseBusiness className="mr-1 inline h-3.5 w-3.5 align-[-2px]" aria-hidden />
        „{data.job_title}”
        {data.in_job_count > 0
          ? ` · ${data.in_job_count} ${plural(data.in_job_count, "osoba", "osoby", "osób")} z Twojej listy już tu jest`
          : ""}
      </p>
      {data.degraded ? (
        <p
          role="status"
          className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          Nie udało się teraz policzyć dopasowania (wyszukiwanie wektorowe jest niedostępne).
          Lista poniżej to Twoi ludzie bez oceny — nie znaczy, że nikt nie pasuje.
        </p>
      ) : null}
      {scored.length ? (
        <ul className="space-y-0.5">
          {scored.map((row) => (
            <ForJobRowView key={row.candidate_id} row={row} actions={actions} />
          ))}
        </ul>
      ) : null}
      {rest.length ? (
        <details className="group">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
            Pozostali bez oceny ({rest.length})
          </summary>
          <ul className="mt-1 space-y-0.5">
            {rest.map((row) => (
              <ForJobRowView key={row.candidate_id} row={row} actions={actions} />
            ))}
          </ul>
        </details>
      ) : null}
      {!data.rows.length ? (
        <p className="px-2 py-6 text-center text-sm text-muted-foreground">
          {data.in_job_count > 0
            ? "Wszyscy Twoi ludzie, którzy mogliby tu pasować, są już w tej rekrutacji."
            : "Nikt z Twojej listy nie jest dostępny do tej rekrutacji."}
        </p>
      ) : null}
    </div>
  );
}

export function EmptyListView() {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-sm font-medium text-foreground">Twoja lista jeszcze jest pusta</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Zbuduje się sama: trafia tu każdy, kogo zweryfikujesz jako pierwszy, gdy jego CV pójdzie do klienta.
      </p>
    </div>
  );
}

export function ErrorView({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="m-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3">
      <p className="text-sm text-destructive">{message}</p>
      <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
        Ponów
      </Button>
    </div>
  );
}
