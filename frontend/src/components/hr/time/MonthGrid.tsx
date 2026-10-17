"use client";

import { Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { LOCATION_LABELS, type WorkLocation } from "@/lib/api/hr";
import type { MonthDay, MonthView, TimesheetEntry } from "@/lib/api/hr-time";
import { CALM_EMPTY, CALM_HEAD } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { dayRowTone, formatHours } from "./time-format";

export interface MonthGridProps {
  view: MonthView;
  /** Dzisiejszy dzień kalendarza firmy („RRRR-MM-DD”) — wyróżniony wiersz. */
  today: string;
  /** Czy wolno dodawać i poprawiać wpisy (szkic osoby albo akceptujący). */
  editable: boolean;
  onEntryClick?: (day: MonthDay, entry: TimesheetEntry | null) => void;
  /** Przełącznik „Biuro/Zdalnie” — tylko we własnym miesiącu. */
  onLocationChange?: (day: MonthDay, location: WorkLocation) => void;
  /** Dzień, którego miejsce pracy właśnie się zapisuje. */
  locationPending?: string | null;
}

const LOCATION_OPTIONS = [
  { value: "onsite" as const, label: LOCATION_LABELS.onsite },
  { value: "remote" as const, label: LOCATION_LABELS.remote },
];

function PlaceCell({
  day,
  onLocationChange,
  pending,
}: {
  day: MonthDay;
  onLocationChange?: MonthGridProps["onLocationChange"];
  pending: boolean;
}) {
  if (day.leave && (day.leave.full || day.leave.paid_work)) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
        {day.leave.label}
        {day.leave.status === "pending" ? " · czeka na decyzję" : ""}
      </span>
    );
  }
  if (day.holiday || day.day_off) {
    return <span className="text-xs text-muted-foreground">{day.holiday ?? day.day_off}</span>;
  }
  if (day.attendance_status === "business_trip") {
    return <span className="text-xs text-foreground">Delegacja</span>;
  }
  if (!day.location) {
    return <span className={CALM_EMPTY}>—</span>;
  }
  if (!onLocationChange) {
    return <span className="text-xs text-foreground">{LOCATION_LABELS[day.location]}</span>;
  }
  return (
    <div className="flex items-center gap-1.5">
      <SegmentedRadio
        size="sm"
        label={`Miejsce pracy ${day.date}`}
        value={day.location}
        options={LOCATION_OPTIONS}
        disabled={pending}
        onChange={(value) => onLocationChange(day, value)}
      />
      {day.leave ? (
        <span className="text-[11px] text-muted-foreground">
          pół dnia: {day.leave.label.toLowerCase()}
        </span>
      ) : null}
    </div>
  );
}

/** Siatka miesiąca: jeden wiersz na dzień (miejsce, godziny, projekt, opis). */
export function MonthGrid({
  view,
  today,
  editable,
  onEntryClick,
  onLocationChange,
  locationPending,
}: MonthGridProps) {
  return (
    <div className="max-h-[calc(100dvh-17rem)] min-h-[16rem] overflow-auto rounded-lg border border-border/60">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-card">
          <tr className="border-b border-border/60">
            <th className={cn(CALM_HEAD, "sticky left-0 z-20 w-[92px] bg-card px-3 py-2 text-left")}>
              Dzień
            </th>
            <th className={cn(CALM_HEAD, "w-[176px] px-2 py-2 text-left")}>Gdzie</th>
            <th className={cn(CALM_HEAD, "w-[64px] px-2 py-2 text-right")}>Godziny</th>
            <th className={cn(CALM_HEAD, "w-[140px] px-2 py-2 text-left")}>Projekt</th>
            <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Opis</th>
            <th className="w-[44px] px-2 py-2">
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {view.days.map((day) => {
            const tone = dayRowTone(day, today);
            const canAdd = editable && day.capacity !== null;
            return (
              <tr
                key={day.date}
                data-testid={`day-${day.date}`}
                className={cn(
                  "border-b border-border/40 align-top",
                  tone.muted && "bg-muted/30",
                  tone.today && "bg-primary/5",
                )}
              >
                <td
                  className={cn(
                    "sticky left-0 whitespace-nowrap px-3 py-1.5 text-xs tabular-nums",
                    tone.today ? "bg-primary/5 font-semibold text-foreground" : "bg-card",
                    tone.muted && !tone.today && "bg-muted/30 text-muted-foreground",
                  )}
                >
                  {formatWeekdayDayPl(day.date)}
                </td>
                <td className="px-2 py-1">
                  <PlaceCell
                    day={day}
                    onLocationChange={onLocationChange}
                    pending={locationPending === day.date}
                  />
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {day.hours > 0 ? formatHours(day.hours) : <span className={CALM_EMPTY}>—</span>}
                  {day.overtime_hours > 0 ? (
                    <span className="mt-0.5 block whitespace-nowrap rounded bg-warning-muted px-1 text-[11px] text-warning-muted-foreground">
                      +{formatHours(day.overtime_hours)} nadg.
                    </span>
                  ) : null}
                </td>
                <td className="px-2 py-1.5 text-xs text-muted-foreground">
                  {day.entries.map((entry) => (
                    <span key={entry.id} className="block truncate leading-5">
                      {entry.project ?? "—"}
                    </span>
                  ))}
                </td>
                <td className="px-2 py-1.5">
                  {day.entries.length === 0 && day.leave?.paid_work ? (
                    <span className="text-xs text-muted-foreground">
                      Praca standardowa · wpisze się z wniosku
                    </span>
                  ) : null}
                  {day.entries.map((entry) => {
                    const locked = entry.source === "leave_paid" || !editable;
                    const label = (
                      <>
                        {day.entries.length > 1 ? (
                          <span className="mr-1 tabular-nums text-muted-foreground">
                            {formatHours(entry.hours)} h ·
                          </span>
                        ) : null}
                        {entry.description}
                        {entry.source === "leave_paid" ? (
                          <span className="ml-1.5 text-[11px] text-muted-foreground">
                            {view.employment_type === "uop"
                              ? "wpisane z wniosku urlopowego"
                              : "płatny dzień przerwy z umowy"}
                          </span>
                        ) : null}
                      </>
                    );
                    return locked ? (
                      <span key={entry.id} className="block leading-5 text-foreground">
                        {label}
                      </span>
                    ) : (
                      <button
                        key={entry.id}
                        type="button"
                        className="block w-full rounded-sm text-left leading-5 text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => onEntryClick?.(day, entry)}
                      >
                        {label}
                      </button>
                    );
                  })}
                </td>
                <td className="px-1 py-1 text-right">
                  {canAdd ? (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Dodaj wpis ${day.date}`}
                      onClick={() => onEntryClick?.(day, null)}
                    >
                      <Plus className="h-4 w-4" aria-hidden />
                    </Button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
