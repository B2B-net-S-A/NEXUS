"use client";

/**
 * Pasek filtrów listy rekrutacji nad tabelą (wariant A, decyzja Artura
 * 25.09.2026 — makieta https://claude.ai/artifact/4nGFAJ6N3NpjVWvLH9yjBH).
 * Zastępuje lewą kolumnę filtrów: przyciski z okienkiem (ten sam wzorzec co
 * lista kandydatów, `FilterPill`) i trzy przełączniki „wymaga uwagi”.
 *
 * Stan żyje w `JobsListV2` (i w adresie) — pasek tylko go pokazuje i zmienia.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  CalendarClock,
  Shapes,
  SlidersHorizontal,
  UserCheck,
  UserCircle,
} from "lucide-react";
import api, { type JobAttentionCounts } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FieldLabel, FilterPill } from "@/components/v2/filters/FilterBarPill";
import { ClientMultiSelect } from "@/components/v2/filters/ClientMultiSelect";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";
import { CompetenceCategoryMultiSelect } from "@/components/v2/filters/CompetenceCategoryMultiSelect";
import {
  DEADLINE_LABEL,
  SENT_LABEL,
  deadlineSummary,
  namesSummary,
  whoSummary,
} from "@/lib/jobs-filter-groups";
import {
  JOB_DEADLINE_PRESETS,
  JOB_SENT_VALUES,
  type JobDeadlinePreset,
  type JobDeadlineRange,
  type JobSentFilterValue,
} from "@/lib/jobs-url-filters";

export interface JobsFilterBarValue {
  clientIds: number[];
  deliveryLeadIds: number[];
  workedBy: number[];
  nobodyWorking: boolean;
  ccIds: number[];
  deadline: JobDeadlinePreset;
  deadlineRange: JobDeadlineRange;
  sent: JobSentFilterValue;
}

export interface JobsFilterBarProps {
  value: JobsFilterBarValue;
  /** Łatka filtrów — wołający sam wraca na pierwszą stronę. */
  onPatch: (patch: Partial<JobsFilterBarValue>) => void;
  /** Id zalogowanej osoby — pozycja „Ja” w „Kto pracuje”. */
  meId: number | null;
  /** Liczby przełączników dla bieżącego zakresu; `undefined` = brak liczby. */
  attention?: JobAttentionCounts;
  activeCount: number;
  /** „Wyczyść filtry” widać też przy samym jawnym zakresie (wraca do domyślnego roli). */
  canClear: boolean;
  onClearAll: () => void;
}

interface NamedRow {
  id: number;
  name: string;
}

function useNames(queryKey: string, url: string): (id: number) => string | undefined {
  // Te same klucze co pickery (`ClientMultiSelect`, `UserMultiSelect`) —
  // jedno zapytanie, a przycisk zna nazwę wybranej pozycji.
  const { data } = useQuery<NamedRow[]>({
    queryKey: [queryKey],
    queryFn: () => api.get(url).then((r) => r.data),
    staleTime: 60_000,
  });
  const byId = new Map(Array.isArray(data) ? data.map((row) => [row.id, row.name]) : []);
  return (id) => byId.get(id);
}

function AttentionToggle({
  label,
  active,
  count,
  tone,
  onToggle,
}: {
  label: string;
  active: boolean;
  count?: number;
  tone: "danger" | "warning" | "neutral";
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors md:h-8",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-accent",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          tone === "danger"
            ? "bg-destructive"
            : tone === "warning"
              ? "bg-warning"
              : "bg-muted-foreground/50",
        )}
      />
      {label}
      {count != null && (
        <span className="tabular-nums text-muted-foreground">{count.toLocaleString("pl-PL")}</span>
      )}
    </button>
  );
}

export function JobsFilterBar({
  value,
  onPatch,
  meId,
  attention,
  activeCount,
  canClear,
  onClearAll,
}: JobsFilterBarProps) {
  const clientName = useNames("clients-lookup", "/api/clients-lookup");
  const userName = useNames("users-directory", "/api/users");
  const who = whoSummary(value.workedBy, value.nobodyWorking, meId, userName);
  const whoCount = value.workedBy.length + (value.nobodyWorking ? 1 : 0);
  const meSelected = meId != null && value.workedBy.includes(meId);

  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label="Filtry listy rekrutacji"
      data-help="jobs.list.filters"
    >
      <FilterPill
        label="Klient"
        icon={<Building2 />}
        summary={namesSummary(value.clientIds, clientName)}
        count={value.clientIds.length}
        onClear={() => onPatch({ clientIds: [] })}
      >
        <ClientMultiSelect value={value.clientIds} onChange={(ids) => onPatch({ clientIds: ids })} />
      </FilterPill>

      <FilterPill
        label="Delivery Lead"
        icon={<UserCircle />}
        summary={namesSummary(value.deliveryLeadIds, userName)}
        count={value.deliveryLeadIds.length}
        onClear={() => onPatch({ deliveryLeadIds: [] })}
      >
        <UserMultiSelect
          value={value.deliveryLeadIds}
          onChange={(ids) => onPatch({ deliveryLeadIds: ids })}
          onlyRoles={["delivery_lead"]}
          placeholder="Dowolny"
          searchPlaceholder="Szukaj Delivery Leada…"
          triggerWidthClass="w-full"
        />
      </FilterPill>

      <FilterPill
        label="Kto pracuje"
        icon={<UserCheck />}
        summary={who}
        count={whoCount}
        onClear={() => onPatch({ workedBy: [], nobodyWorking: false })}
      >
        <div className="space-y-1">
          {meId != null && (
            <label className="flex items-center gap-2 rounded-md px-1 py-1 text-sm">
              <input
                type="checkbox"
                checked={meSelected}
                onChange={() =>
                  onPatch({
                    workedBy: meSelected
                      ? value.workedBy.filter((id) => id !== meId)
                      : [...value.workedBy, meId],
                  })
                }
              />
              Ja
            </label>
          )}
          <label className="flex items-center gap-2 rounded-md px-1 py-1 text-sm">
            <input
              type="checkbox"
              checked={value.nobodyWorking}
              onChange={() => onPatch({ nobodyWorking: !value.nobodyWorking })}
            />
            Nikt (request bez osoby)
          </label>
        </div>
        <div className="space-y-1">
          <FieldLabel>Zespół</FieldLabel>
          <UserMultiSelect
            value={value.workedBy.filter((id) => id !== meId)}
            onChange={(ids) => onPatch({ workedBy: meSelected && meId != null ? [meId, ...ids] : ids })}
            placeholder="Dowolna osoba"
            searchPlaceholder="Szukaj osoby…"
            triggerWidthClass="w-full"
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Osoby przypisane do requestu (automat albo ręcznie), także prowadzący. Kilka pozycji
          naraz to „którakolwiek z nich”.
        </p>
      </FilterPill>

      <FilterPill
        label="Kategoria"
        icon={<Shapes />}
        count={value.ccIds.length}
        onClear={() => onPatch({ ccIds: [] })}
      >
        <CompetenceCategoryMultiSelect
          value={value.ccIds}
          onChange={(ids) => onPatch({ ccIds: ids })}
          triggerWidthClass="w-full"
        />
      </FilterPill>

      <FilterPill
        label="Termin"
        icon={<CalendarClock />}
        summary={deadlineSummary(value.deadline, value.deadlineRange)}
        count={value.deadline === "any" ? 0 : 1}
        onClear={() => onPatch({ deadline: "any", deadlineRange: {} })}
      >
        <Select
          value={value.deadline}
          onValueChange={(v) => onPatch({ deadline: v as JobDeadlinePreset })}
        >
          <SelectTrigger className="h-9 w-full" aria-label="Filtr: Termin">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {JOB_DEADLINE_PRESETS.map((preset) => (
              <SelectItem key={preset} value={preset}>
                {preset === "any"
                  ? "Dowolny"
                  : preset === "range"
                    ? "Zakres dat…"
                    : DEADLINE_LABEL[preset][0].toUpperCase() + DEADLINE_LABEL[preset].slice(1)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {value.deadline === "range" && (
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <FieldLabel htmlFor="jobs-deadline-from">Od</FieldLabel>
              <Input
                id="jobs-deadline-from"
                type="date"
                value={value.deadlineRange.from ?? ""}
                onChange={(e) =>
                  onPatch({ deadlineRange: { ...value.deadlineRange, from: e.target.value || undefined } })
                }
                aria-label="Termin od"
              />
            </div>
            <div className="space-y-1">
              <FieldLabel htmlFor="jobs-deadline-to">Do</FieldLabel>
              <Input
                id="jobs-deadline-to"
                type="date"
                value={value.deadlineRange.to ?? ""}
                onChange={(e) =>
                  onPatch({ deadlineRange: { ...value.deadlineRange, to: e.target.value || undefined } })
                }
                aria-label="Termin do"
              />
            </div>
          </div>
        )}
      </FilterPill>

      <FilterPill
        label="Więcej filtrów"
        icon={<SlidersHorizontal />}
        summary={value.sent !== "any" ? `wysłanych: ${SENT_LABEL[value.sent]}` : null}
        count={value.sent !== "any" ? 1 : 0}
        onClear={() => onPatch({ sent: "any" })}
      >
        <div className="space-y-1">
          <FieldLabel>Wysłanych do klienta</FieldLabel>
          <Select value={value.sent} onValueChange={(v) => onPatch({ sent: v as JobSentFilterValue })}>
            <SelectTrigger className="h-9 w-full" aria-label="Filtr: Wysłanych do klienta">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {JOB_SENT_VALUES.map((sent) => (
                <SelectItem key={sent} value={sent}>
                  {SENT_LABEL[sent][0].toUpperCase() + SENT_LABEL[sent].slice(1)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Osoby, które w tej rekrutacji doszły do „CV wysłane” albo dalej.
          </p>
        </div>
      </FilterPill>

      <span aria-hidden="true" className="mx-1 hidden h-5 w-px bg-border sm:block" />

      <AttentionToggle
        label="Po terminie"
        tone="danger"
        active={value.deadline === "overdue"}
        count={attention?.overdue}
        onToggle={() =>
          onPatch({ deadline: value.deadline === "overdue" ? "any" : "overdue", deadlineRange: {} })
        }
      />
      <AttentionToggle
        label="Nikt nie pracuje"
        tone="warning"
        active={value.nobodyWorking}
        count={attention?.nobody_working}
        onToggle={() => onPatch({ nobodyWorking: !value.nobodyWorking })}
      />
      <AttentionToggle
        label="Nikogo nie wysłano"
        tone="neutral"
        active={value.sent === "none"}
        count={attention?.nobody_sent}
        onToggle={() => onPatch({ sent: value.sent === "none" ? "any" : "none" })}
      />

      {canClear && (
        <button
          type="button"
          onClick={onClearAll}
          className="ml-auto text-xs text-primary hover:underline"
        >
          Wyczyść filtry{activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
      )}
    </div>
  );
}
