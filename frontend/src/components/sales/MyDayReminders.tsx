"use client";

import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { useCallReminders } from "@/lib/api/sales-calling";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { REMINDERS_VIEW, STATE_TONES, stateLabel } from "./calling/calling";

/** Tyle przypomnień widać w „Moim dniu”; resztę pokazuje zakładka w Dzwonieniu. */
export const MY_DAY_REMINDERS = 8;

/**
 * „Mój dzień” → „Przypomnienia na dziś” (lista dzwoniących 13.11.2026): terminy powrotów
 * z Dzwonienia, które przypadają dziś albo minęły. Bez rekordów nie zajmuje miejsca;
 * awaria nie wygląda jak brak przypomnień.
 */
export function MyDayReminders({ today }: { today: string }) {
  const query = useCallReminders("mine", null, today);
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać przypomnień z Dzwonienia."
        onRetry={() => void query.refetch()}
      />
    );
  }
  const items = query.data ?? [];
  if (!query.isSuccess || items.length === 0) return null;
  return (
    <section
      aria-label="Przypomnienia na dziś"
      className="min-w-0 overflow-hidden rounded-lg border border-border bg-card"
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-border bg-muted/40 px-3 py-1">
        <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Przypomnienia na dziś</h2>
        <Link href={`/sales/calling?view=${REMINDERS_VIEW}`} className="text-xs text-primary hover:underline">
          Wszystkie przypomnienia ({items.length})
        </Link>
      </header>
      <ul className="divide-y divide-border">
        {items.slice(0, MY_DAY_REMINDERS).map((item) => (
          <li key={item.key} className="flex min-h-10 items-center gap-2 px-3 py-1 text-sm">
            <span className="w-16 shrink-0 text-xs tabular-nums text-muted-foreground">
              {item.due_on && item.due_on < today ? formatWeekdayDayPl(item.due_on) : "dziś"}
            </span>
            <span className="min-w-0 flex-1 truncate">
              <span className="font-medium text-foreground">{item.company.name}</span>
              {item.person_name && <span className="text-muted-foreground"> · {item.person_name}</span>}
            </span>
            <Badge variant={STATE_TONES[item.state]} size="sm" className="shrink-0 whitespace-nowrap">
              {stateLabel(item.state)}
            </Badge>
          </li>
        ))}
      </ul>
    </section>
  );
}
