"use client";

import { ArrowLeft, PartyPopper } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { TraineeToday } from "@/lib/api/trainee";
import { isCompleteProfile } from "@/lib/trainee-call";

function lastClosedAt(today: TraineeToday): string | null {
  const times = today.items
    .map((i) => (i.closed_at ? new Date(i.closed_at).getTime() : Number.NaN))
    .filter((t) => Number.isFinite(t));
  if (times.length === 0) return null;
  return new Date(Math.max(...times)).toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Ekran końca dnia (makieta „DzienZaliczony”): wszystkie pozycje mają wynik. */
export function DayCompleteView({
  today,
  onBackToList,
}: {
  today: TraineeToday;
  onBackToList: () => void;
}) {
  const { counts } = today;
  const calls = today.items.filter((i) => i.closed_at && i.outcome === "call");
  const complete = calls.filter((i) => isCompleteProfile(i.facts)).length;
  const employmentOnly = calls.filter((i) => i.facts.b2b_willingness === "employment_only").length;
  const at = lastClosedAt(today);
  const stats: Array<[string, number]> = [
    ["Rozmowy", counts.call],
    ["Nie odbiera (2 próby)", counts.noanswer],
    ["Telefon innego dnia", counts.later],
    ["Zły numer", counts.wrong],
    ["Niezainteresowani", counts.declined],
  ];
  return (
    <section
      aria-label="Dzień zaliczony"
      className="mx-auto flex max-w-3xl flex-col gap-5 rounded-xl border border-border bg-card p-5 md:p-8"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-success-muted text-success-muted-foreground">
          <PartyPopper className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <h2 className="text-2xl font-bold text-foreground">Dzień zaliczony</h2>
          <p className="text-sm text-muted-foreground">
            {counts.closed} z {counts.total} pozycji zamkniętych{at ? ` o ${at}` : ""}. Możesz
            skończyć pracę.
          </p>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-lg bg-muted px-3 py-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-lg font-semibold tabular-nums text-foreground">{value}</dd>
          </div>
        ))}
      </dl>

      {calls.length > 0 ? (
        <div className="rounded-lg border border-border px-4 py-3">
          <p className="text-sm text-foreground">
            <b className="font-semibold">Pełne profile po rozmowie:</b> {complete} z {calls.length}{" "}
            ({Math.round((complete / calls.length) * 100)}%)
          </p>
          {employmentOnly > 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Tylko etat: {employmentOnly} — te osoby wypadły z wyszukiwarki.
            </p>
          ) : null}
        </div>
      ) : null}

      {today.program ? (
        <p className="text-sm text-muted-foreground">
          Program: dzień {today.program.day} z {today.program.total_days}
        </p>
      ) : null}

      <p className="text-sm text-muted-foreground">
        Jutrzejsza lista będzie gotowa rano — najpierw osoby pasujące do otwartych rekrutacji.
      </p>

      <div>
        <Button variant="outline" size="lg" className="min-h-11" onClick={onBackToList}>
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Wróć do listy (zamknięte pozycje)
        </Button>
      </div>
    </section>
  );
}
