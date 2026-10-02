"use client";

/**
 * Pasek filtrów listy rekrutacji nad tabelą (wariant A, decyzja Artura
 * 25.09.2026 — makieta https://claude.ai/artifact/4nGFAJ6N3NpjVWvLH9yjBH).
 * Zastępuje lewą kolumnę filtrów: przyciski z okienkiem (ten sam wzorzec co
 * lista kandydatów, `FilterPill`) i trzy przełączniki „wymaga uwagi”.
 *
 * Od 02.10.2026: „Kto pracuje” to „Rekruter”, doszły „Priorytet” i „Data
 * otwarcia”, a pasek układa się po WŁASNEJ szerokości (`jobsFilterBarLayout`).
 *
 * Stan żyje w `JobsListV2` (i w adresie) — pasek tylko go pokazuje i zmienia.
 */

import { useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  CalendarClock,
  CalendarPlus,
  Flag,
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
  openedRangeSet,
  openedSummary,
  prioritySummary,
  whoSummary,
} from "@/lib/jobs-filter-groups";
import {
  JOB_DEADLINE_PRESETS,
  JOB_SENT_VALUES,
  isFilterDate,
  openedRangeReversed,
  type JobDeadlinePreset,
  type JobDeadlineRange,
  type JobOpenedRange,
  type JobSentFilterValue,
} from "@/lib/jobs-url-filters";
import { PRIORITY_LEVEL_OPTIONS, type PriorityLevel } from "@/lib/request-priority";

export interface JobsFilterBarValue {
  clientIds: number[];
  deliveryLeadIds: number[];
  /** „Rekruter” — id osób. */
  workedBy: number[];
  /** „Bez rekrutera”. */
  nobodyWorking: boolean;
  ccIds: number[];
  deadline: JobDeadlinePreset;
  deadlineRange: JobDeadlineRange;
  sent: JobSentFilterValue;
  priorityLevels: PriorityLevel[];
  openedRange: JobOpenedRange;
}

/**
 * Układ paska zależy od JEGO szerokości, nie od okna: przypięte menu, szyna
 * otwartych kart i dok podglądu zabierają mu miejsce niezależnie od ekranu
 * (okno 1280 px to ~1100 px paska przy zwiniętym menu i ~920 px przy
 * przypiętym, z paskiem otwartych kart po lewej).
 *
 * - `narrow` — krótkie etykiety, ciasne odstępy, „Data otwarcia” siedzi
 *   w „Więcej filtrów”;
 * - `medium` — krótkie etykiety, „Data otwarcia” ma własny przycisk;
 * - `wide` — pełne etykiety, ikony i strzałki.
 *
 * To zapytanie o kontener w JS (`ResizeObserver`), a nie klasy `@container`:
 * wynik musi znać także kod. Okienko „Więcej filtrów” renderuje się w portalu,
 * czyli poza kontenerem CSS, a jego przycisk liczy filtr schowany do środka.
 */
export type JobsFilterBarLayout = "narrow" | "medium" | "wide";

/**
 * Progi w px szerokości paska. Zmierzone w Chromium 02.10.2026 na pasku bez
 * ustawionych filtrów (Inter 12 px, liczniki jednocyfrowe): układ `narrow`
 * zajmuje ~860 px, `medium` ~1000 px, `wide` ~1460 px. Do tego dochodzi do
 * ~35 px na dłuższe liczniki i ~70–100 px na link „Wyczyść (N)”, a reszta
 * zapasu (≥ 100 px) jest na wartość jednego ustawionego filtra — pasek ma
 * zostać w jednym rzędzie także po ustawieniu filtra.
 */
export const JOBS_FILTER_BAR_OPENED_PILL_MIN_WIDTH = 1220;
export const JOBS_FILTER_BAR_FULL_MIN_WIDTH = 1600;

/** `null` = jeszcze nie zmierzono (pierwszy render, testy bez układu). */
export function jobsFilterBarLayout(width: number | null): JobsFilterBarLayout {
  if (width == null || width < JOBS_FILTER_BAR_OPENED_PILL_MIN_WIDTH) return "narrow";
  return width < JOBS_FILTER_BAR_FULL_MIN_WIDTH ? "medium" : "wide";
}

/**
 * Układ wynikający ze zmierzonej szerokości elementu. Stan trzyma UKŁAD, nie
 * szerokość — pasek renderuje się ponownie tylko przy przejściu przez próg,
 * nie przy każdym pikselu zmiany okna.
 */
function useJobsFilterBarLayout() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [layout, setLayout] = useState<JobsFilterBarLayout>("narrow");
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const width = Math.round(el.getBoundingClientRect().width);
      // jsdom nie liczy układu (szerokość 0) — zostaje układ najwęższy.
      setLayout(jobsFilterBarLayout(width > 0 ? width : null));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, layout] as const;
}

export interface JobsFilterBarProps {
  value: JobsFilterBarValue;
  /** Łatka filtrów — wołający sam wraca na pierwszą stronę. */
  onPatch: (patch: Partial<JobsFilterBarValue>) => void;
  /** Id zalogowanej osoby — pozycja „Ja” w „Rekruter”. */
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

// Odstępy przełącznika per układ paska — pełne literały klas dla Tailwinda.
const TOGGLE_SPACING: Record<JobsFilterBarLayout, string> = {
  narrow: "gap-1 px-2",
  medium: "gap-1.5 px-2.5",
  wide: "gap-1.5 px-3",
};

function AttentionToggle({
  label,
  active,
  count,
  tone,
  layout,
  onToggle,
}: {
  label: string;
  active: boolean;
  count?: number;
  tone: "danger" | "warning" | "neutral";
  layout: JobsFilterBarLayout;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      className={cn(
        "inline-flex h-9 shrink-0 items-center rounded-full border text-xs font-medium transition-colors md:h-8",
        TOGGLE_SPACING[layout],
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

/** Pola „Data otwarcia” — we własnym okienku albo w „Więcej filtrów”. */
function OpenedRangeFields({
  value,
  onChange,
}: {
  value: JobOpenedRange;
  onChange: (next: JobOpenedRange) => void;
}) {
  const reversed = openedRangeReversed(value);
  // Pole daty w trakcie wpisywania roku oddaje „0002-10-01” — tego nie
  // wysyłamy, a osoba ma wiedzieć, dlaczego lista jeszcze się nie zawęziła.
  const incomplete = [value.from, value.to].some((date) => Boolean(date) && !isFilterDate(date));
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <FieldLabel htmlFor="jobs-opened-from">Od</FieldLabel>
          <Input
            id="jobs-opened-from"
            type="date"
            value={value.from ?? ""}
            onChange={(e) => onChange({ ...value, from: e.target.value || undefined })}
            aria-label="Data otwarcia od"
            aria-invalid={reversed || undefined}
          />
        </div>
        <div className="space-y-1">
          <FieldLabel htmlFor="jobs-opened-to">Do</FieldLabel>
          <Input
            id="jobs-opened-to"
            type="date"
            value={value.to ?? ""}
            onChange={(e) => onChange({ ...value, to: e.target.value || undefined })}
            aria-label="Data otwarcia do"
            aria-invalid={reversed || undefined}
          />
        </div>
      </div>
      {/* Odwrócony zakres nie idzie do serwera (422) — mówimy to przy polu,
          zamiast pokazać pustą listę pod niemożliwym warunkiem. */}
      {reversed ? (
        <p role="alert" className="text-xs text-destructive">
          Data „od” jest późniejsza niż „do” — popraw zakres, żeby go zastosować.
        </p>
      ) : incomplete ? (
        <p className="text-xs text-muted-foreground">Wpisz pełną datę z lat 1900–2100.</p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Dzień otwarcia rekrutacji, a gdy go nie ma — dzień dodania do NEXUSA.
      </p>
    </div>
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

  const [barRef, layout] = useJobsFilterBarLayout();
  const roomy = layout === "wide";
  const density = roomy ? "full" : "compact";
  // Wąski pasek: „Data otwarcia” mieszka w „Więcej filtrów”, a tamten
  // przycisk ją liczy — schowany, ale ustawiony filtr ma być widać.
  const openedFolded = layout === "narrow";
  const openedSet = openedRangeSet(value.openedRange);
  const opened = openedSummary(value.openedRange);
  const sentSet = value.sent !== "any";
  const moreCount = (sentSet ? 1 : 0) + (openedFolded && openedSet ? 1 : 0);
  const moreSummary =
    moreCount !== 1
      ? null
      : sentSet
        ? `wysłanych: ${SENT_LABEL[value.sent]}`
        : `otwarta: ${opened}`;
  const openedFields = (
    <OpenedRangeFields
      value={value.openedRange}
      onChange={(openedRange) => onPatch({ openedRange })}
    />
  );

  return (
    <div
      ref={barRef}
      className="flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label="Filtry listy rekrutacji"
      data-help="jobs.list.filters"
      data-layout={layout}
    >
      <FilterPill
        label="Delivery Lead"
        shortLabel="DL"
        icon={<UserCircle />}
        density={density}
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
        label="Klient"
        icon={<Building2 />}
        density={density}
        summary={namesSummary(value.clientIds, clientName)}
        count={value.clientIds.length}
        onClear={() => onPatch({ clientIds: [] })}
      >
        <ClientMultiSelect value={value.clientIds} onChange={(ids) => onPatch({ clientIds: ids })} />
      </FilterPill>

      <FilterPill
        label="Rekruter"
        icon={<UserCheck />}
        density={density}
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
            Bez rekrutera
          </label>
        </div>
        <div className="space-y-1">
          <FieldLabel>Osoby</FieldLabel>
          <UserMultiSelect
            value={value.workedBy.filter((id) => id !== meId)}
            onChange={(ids) => onPatch({ workedBy: meSelected && meId != null ? [meId, ...ids] : ids })}
            placeholder="Dowolna osoba"
            searchPlaceholder="Szukaj osoby…"
            triggerWidthClass="w-full"
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Osoby, które pracują nad rekrutacją w roli Rekrutera. Propozycja automatu, której nikt
          jeszcze nie zaakceptował, się nie liczy. Kilka pozycji naraz to „którakolwiek z nich”.
        </p>
      </FilterPill>

      <FilterPill
        label="Kategoria"
        icon={<Shapes />}
        density={density}
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
        label="Priorytet"
        icon={<Flag />}
        density={density}
        summary={prioritySummary(value.priorityLevels)}
        count={value.priorityLevels.length}
        onClear={() => onPatch({ priorityLevels: [] })}
      >
        <div className="space-y-1" role="group" aria-label="Priorytet rekrutacji">
          {PRIORITY_LEVEL_OPTIONS.map((option) => {
            const checked = value.priorityLevels.includes(option.value);
            return (
              <label
                key={option.value}
                className="flex items-center gap-2 rounded-md px-1 py-1 text-sm"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() =>
                    onPatch({
                      priorityLevels: checked
                        ? value.priorityLevels.filter((level) => level !== option.value)
                        : [...value.priorityLevels, option.value],
                    })
                  }
                />
                {option.label}
              </label>
            );
          })}
        </div>
        <p className="text-xs text-muted-foreground">
          Kilka poziomów naraz to „którykolwiek z nich”. Rekrutacja bez plakietki ma P2.
        </p>
      </FilterPill>

      <FilterPill
        label="Termin"
        icon={<CalendarClock />}
        density={density}
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

      {!openedFolded && (
        <FilterPill
          label="Data otwarcia"
          icon={<CalendarPlus />}
          density={density}
          summary={opened}
          count={openedSet ? 1 : 0}
          onClear={() => onPatch({ openedRange: {} })}
        >
          {openedFields}
        </FilterPill>
      )}

      <FilterPill
        label="Więcej filtrów"
        shortLabel="Więcej"
        icon={<SlidersHorizontal />}
        density={density}
        summary={moreSummary}
        count={moreCount}
        onClear={() =>
          onPatch(openedFolded ? { sent: "any", openedRange: {} } : { sent: "any" })
        }
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
        {openedFolded && (
          <div className="space-y-1 border-t border-border pt-3">
            <p className="text-xs font-medium text-foreground">Data otwarcia</p>
            {openedFields}
          </div>
        )}
      </FilterPill>

      {/* Kreska oddziela filtry od przełączników; na wąskim pasku ustępuje
          miejsca — przełączniki odróżnia kropka. */}
      {layout !== "narrow" && (
        <span
          aria-hidden="true"
          className={cn("hidden h-5 w-px bg-border sm:block", roomy && "mx-1")}
        />
      )}

      <AttentionToggle
        label="Po terminie"
        tone="danger"
        layout={layout}
        active={value.deadline === "overdue"}
        count={attention?.overdue}
        onToggle={() =>
          onPatch({ deadline: value.deadline === "overdue" ? "any" : "overdue", deadlineRange: {} })
        }
      />
      <AttentionToggle
        label="Bez rekrutera"
        tone="warning"
        layout={layout}
        active={value.nobodyWorking}
        count={attention?.nobody_working}
        onToggle={() => onPatch({ nobodyWorking: !value.nobodyWorking })}
      />
      <AttentionToggle
        label="Nikogo nie wysłano"
        tone="neutral"
        layout={layout}
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
          {/* Na wąskim pasku krótko — link spadał do osobnej linii. */}
          {roomy ? (
            "Wyczyść filtry"
          ) : (
            <>
              <span className="sr-only">Wyczyść filtry</span>
              <span aria-hidden="true">Wyczyść</span>
            </>
          )}
          {activeCount > 0 ? ` (${activeCount})` : ""}
        </button>
      )}
    </div>
  );
}
