"use client";

// „Nieobecni dziś” w górnym pasku (16.10.2026). Kto jest dziś nieobecny, do
// kiedy i kto go zastępuje — bez rodzaju nieobecności (D6). Widać go tylko
// przy włączonym module urlopów i przy co najmniej jednej nieobecności: ikona
// z liczbą (36 px), żeby nie rozpychać paska na laptopie 1280 px.

import { useState } from "react";
import Link from "next/link";
import { UserX } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useHrConfig } from "@/lib/api/hr";
import { useAbsentToday, type AbsentTodayRow } from "@/lib/api/hr-leave";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import { formatDayMonthPl, formatWeekdayDayPl } from "@/lib/date-pl";

import { absentRowText } from "./leave-format";

/** Kalendarz otwarty na „Wszyscy” + „Dziś nieobecni” (parametry z `calendar-filters.ts`). */
export const ABSENT_TODAY_CALENDAR_HREF = "/people/calendar?scope=all&status=absent";

interface AbsentTodayPanelProps {
  date: string;
  items: AbsentTodayRow[];
  onNavigate: () => void;
}

/** Treść okienka — bez zapytań (test i harness). */
export function AbsentTodayPanel({ date, items, onNavigate }: AbsentTodayPanelProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <b className="text-sm text-foreground">Nieobecni dziś · {formatWeekdayDayPl(date)}</b>
        {/* Kalendarz z tym samym zbiorem co okienko: wszyscy, „Dziś nieobecni”. */}
        <Link
          href={ABSENT_TODAY_CALENDAR_HREF}
          onClick={onNavigate}
          className="text-[11.5px] text-primary hover:underline"
        >
          Kalendarz zespołu
        </Link>
      </div>
      <ul className="max-h-[50dvh] space-y-1 overflow-y-auto">
        {items.map((row) => (
          <li key={row.user_id} className="flex items-start gap-2 rounded-md px-1 py-1">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">
                {row.name}
                {row.is_me ? " (Ty)" : ""}
              </p>
              <p className="text-xs text-muted-foreground">{absentRowText(row, date)}</p>
            </div>
            {row.substitute_absent ? (
              <span className="shrink-0 rounded-full border border-warning/25 bg-warning-muted px-1.5 text-[10.5px] text-warning-muted-foreground">
                zastępca nieobecny
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-muted-foreground">
        Rodzaj nieobecności widzą tylko osoba, jej przełożony i Kadry. Dane z {formatDayMonthPl(date)}.
      </p>
    </div>
  );
}

/** Przycisk paska — tylko przy otwartym module urlopów i niepustej liście. */
export function AbsentTodayButton({ className }: { className?: string }) {
  const user = useAuthStore((state) => state.user);
  // Praktykant ma własną powłokę i nie pyta o moduły (jak menu w `useHrNavState`).
  const roles = new Set([user?.role, ...(user?.roles ?? [])].filter(Boolean));
  const traineeOnly = roles.size === 1 && roles.has("trainee");
  const config = useHrConfig(Boolean(user) && !traineeOnly);
  const leaveOpen = Boolean(config.data?.open_modules.leave);
  const absent = useAbsentToday(Boolean(user) && leaveOpen);
  const [open, setOpen] = useState(false);
  const total = absent.data?.total ?? 0;
  if (!leaveOpen || !absent.data || total === 0) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Nieobecni dziś: ${countPl(total, "osoba", "osoby", "osób")}`}
          className={cn(
            "relative rounded-lg p-2 transition-colors",
            open
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
            className,
          )}
        >
          <UserX className="h-5 w-5" aria-hidden />
          <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-muted px-1 text-xs font-bold tabular-nums text-foreground ring-1 ring-border">
            {total > 99 ? "99+" : total}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-3">
        <AbsentTodayPanel
          date={absent.data.date}
          items={absent.data.items}
          onNavigate={() => setOpen(false)}
        />
      </PopoverContent>
    </Popover>
  );
}
