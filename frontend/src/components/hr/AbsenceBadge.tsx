"use client";

// Plakietka nieobecności przy osobie („Nieobecność do 24.10 · zastępuje Anna P.”).
//
// Do wpięcia w listy osób w całym NEXUSIE: lista pobiera nieobecności RAZ
// (`useAbsences(ids)` z `@/lib/api/hr-leave` → `byUser`), a wiersz rysuje
// `<AbsenceBadge absence={byUser.get(id)} />`. Bez rodzaju nieobecności (D6) —
// plakietkę widzi cały zespół. Brak nieobecności = nic się nie renderuje.

import { warsawToday, absenceBadgeText } from "@/components/hr/leave/leave-format";
import type { PersonAbsence } from "@/lib/api/hr-leave";
import { cn } from "@/lib/utils";

export interface AbsenceBadgeProps {
  absence: PersonAbsence | null | undefined;
  /** Dzień kalendarza firmy („YYYY-MM-DD”); domyślnie dziś w Warszawie. */
  today?: string;
  className?: string;
}

export function AbsenceBadge({ absence, today, className }: AbsenceBadgeProps) {
  if (!absence) return null;
  const text = absenceBadgeText(absence, today ?? warsawToday());
  return (
    <span
      title={text}
      className={cn(
        "inline-flex max-w-full items-center truncate rounded-full border border-warning/25 bg-warning-muted px-2 py-0.5 text-[11px] font-medium leading-4 text-warning-muted-foreground",
        className,
      )}
    >
      {text}
    </span>
  );
}
