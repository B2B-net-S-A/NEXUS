"use client";

// Plakietka nieobecności przy osobie („Nieobecność do 24.10 · zastępuje Anna P.”).
//
// Do wpięcia w listy osób w całym NEXUSIE: lista pobiera nieobecności RAZ
// (`useAbsences(ids)` z `@/lib/api/hr-leave` → `byUser`), a wiersz rysuje
// `<AbsenceBadge absence={byUser.get(id)} />`. Bez rodzaju nieobecności (D6) —
// plakietkę widzi cały zespół. Brak nieobecności = nic się nie renderuje.

import { absenceBadgeText } from "@/components/hr/leave/leave-format";
import type { PersonAbsence } from "@/lib/api/hr-leave";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

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

export interface AbsentPerson {
  name: string;
  absence: PersonAbsence;
}

export interface AbsenceDotProps {
  people: readonly AbsentPerson[];
  today?: string;
  className?: string;
  "data-testid"?: string;
}

/**
 * Kropka przy osobach w ciasnej kolumnie (lista rekrutacji, 1280 px): nie
 * poszerza komórki, a pełny tekst („Ola Nowak: Nieobecność do 23.10 ·
 * zastępuje Marta Z.”) stoi w podpowiedzi i dla czytnika ekranu. Bez rodzaju
 * nieobecności (D6).
 */
export function AbsenceDot({
  people,
  today,
  className,
  "data-testid": testId,
}: AbsenceDotProps) {
  if (people.length === 0) return null;
  const day = today ?? warsawToday();
  const text = people
    .map((person) => `${person.name}: ${absenceBadgeText(person.absence, day)}`)
    .join("\n");
  return (
    <span
      title={text}
      data-testid={testId}
      className={cn("inline-flex h-4 w-2 shrink-0 items-center justify-center", className)}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-warning" />
      <span className="sr-only">{text}</span>
    </span>
  );
}
