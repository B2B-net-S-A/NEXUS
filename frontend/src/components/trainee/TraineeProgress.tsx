"use client";

import { Progress } from "@/components/ui/progress";
import type { TraineeToday } from "@/lib/api/trainee";

function pct(value: number | null): string {
  return value == null ? "—" : `${Math.round(value)}%`;
}

/** Karta „N z 70 pozycji zamkniętych” + liczniki wyników (makieta „Main”). */
export function TraineeProgress({ today }: { today: TraineeToday }) {
  const { counts } = today;
  const done = counts.total > 0 ? Math.round((counts.closed / counts.total) * 100) : 0;
  const stats: Array<[string, number]> = [
    ["Rozmowy", counts.call],
    ["Nie odbiera (2 próby)", counts.noanswer],
    ["Telefon innego dnia", counts.later],
    ["Zły numer", counts.wrong],
    ["Niezainteresowani", counts.declined],
  ];
  return (
    <section
      aria-label="Postęp dnia"
      className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4 md:p-5 xl:flex-row xl:items-center xl:gap-8"
    >
      <div className="flex min-w-0 flex-col gap-2 xl:w-80 xl:shrink-0">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-foreground">
            {counts.closed} z {counts.total}
          </span>
          <span className="text-sm text-muted-foreground">pozycji zamkniętych</span>
        </div>
        <Progress value={done} aria-label={`Zamknięte pozycje: ${done}%`} />
        <span className="text-xs text-muted-foreground">
          Zostało {counts.open}. Gdy każda pozycja ma wynik, dzień jest zaliczony — także
          jeśli skończysz wcześniej.
        </span>
      </div>
      <dl className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-lg bg-muted px-3 py-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-lg font-semibold tabular-nums text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col xl:w-44 xl:shrink-0">
        <span className="text-xs text-muted-foreground">Odebrane telefony</span>
        <span className="text-2xl font-bold tabular-nums text-foreground">
          {pct(today.answered_pct)}
        </span>
        <span className="text-xs text-muted-foreground">
          średnia praktykantów: {pct(today.team_answered_pct)}
        </span>
      </div>
    </section>
  );
}
