"use client";

/**
 * „Gdy Cię nie było” na górze „Czeka na Ciebie” (decyzja Artura 16.11.2026,
 * wariant A z makiet). Po powrocie z urlopu osoba widzi pracę, która w tym
 * czasie poszła do zastępcy: na górze zamknięcia rekrutacji z jej osobami,
 * resztę jako licznik. Sprawę może oznaczyć jako załatwioną ona albo zastępca.
 * Reguła: `docs/claude/powiadomienia/gdy-cie-nie-bylo-po-powrocie.md`.
 */

import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button, buttonVariants } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  WHILE_AWAY_QUERY_KEY,
  dismissWhileAway,
  markWhileAwayHandled,
  useWhileAway,
  type WhileAwayAction,
  type WhileAwaySummary,
} from "@/lib/api/whileAway";
import { countPl } from "@/lib/plural-pl";
import { warsawClock } from "@/lib/warsaw-date";

function dayMonth(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split("-");
  return `${Number(day)}.${month}`;
}

function whenLabel(value: string): string {
  const date = new Date(value);
  const day = new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "numeric",
    month: "2-digit",
  }).format(date);
  return `${day} ${warsawClock(date)}`;
}

export function periodLabel(summary: Pick<WhileAwaySummary, "since" | "until">): string {
  return summary.since === summary.until
    ? dayMonth(summary.since)
    : `${dayMonth(summary.since)}–${dayMonth(summary.until)}`;
}

/** `standalone` — własna ramka, gdy panel „Czeka na Ciebie” jest pusty. */
export function WhileAwaySection({ standalone = false }: { standalone?: boolean }) {
  const query = useWhileAway();
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [busy, setBusy] = useState(false);

  if (query.isError) {
    return (
      <p role="alert" className="mb-3 text-xs text-destructive">
        Nie udało się wczytać pracy z Twojej nieobecności. Odśwież stronę za chwilę.
      </p>
    );
  }
  if (!query.isSuccess || query.data == null) return null;
  const summary = query.data;
  const open = summary.actions.filter((row) => row.handled_at == null).length;
  const rest = summary.others.reduce((sum, group) => sum + group.count, 0);

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    try {
      await action();
      await queryClient.invalidateQueries({ queryKey: WHILE_AWAY_QUERY_KEY });
    } catch (error) {
      showError(apiErrorMessage(error, fallback));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Gdy Cię nie było"
      className={
        standalone ? "grid gap-2 rounded-xl border border-border bg-card px-4 py-3" : "mb-4 grid gap-2"
      }
    >
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Gdy Cię nie było · {periodLabel(summary)}
        </h3>
        <p className="min-w-0 flex-1 text-xs text-muted-foreground">
          {summary.substitute_names.length > 0
            ? `Zastępstwo: ${summary.substitute_names.join(", ")} · `
            : ""}
          {countPl(summary.total, "zdarzenie", "zdarzenia", "zdarzeń")} w Twoich sprawach
        </p>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => run(dismissWhileAway, "Nie udało się zamknąć podsumowania.")}
        >
          Zamknij podsumowanie
        </Button>
      </header>
      {summary.actions.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">Rekrutacje zamknięte z Twoimi osobami</h4>
            <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
              {summary.actions.length}
            </span>
            {open > 0 ? (
              <span className="rounded-full bg-destructive/10 px-2 text-xs font-medium text-destructive">
                {open} do załatwienia
              </span>
            ) : null}
          </div>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {summary.actions.map((row) => (
              <ActionRow
                key={row.id}
                row={row}
                busy={busy}
                onHandled={() =>
                  run(() => markWhileAwayHandled(row.id), "Nie udało się oznaczyć sprawy.")
                }
              />
            ))}
          </ul>
        </>
      ) : null}
      {rest > 0 ? (
        <p className="text-xs text-muted-foreground">
          {summary.actions.length > 0 ? "Pozostałe" : "Do zastępcy trafiło"} {rest}:{" "}
          {summary.others.map((group) => `${group.label} ${group.count}`).join(", ")}
        </p>
      ) : null}
    </section>
  );
}

function ActionRow({
  row,
  busy,
  onHandled,
}: {
  row: WhileAwayAction;
  busy: boolean;
  onHandled: () => void;
}) {
  const handled = row.handled_at != null;
  return (
    <li className="grid grid-cols-[minmax(0,1fr)] items-center gap-x-3 gap-y-1.5 px-3 py-2 md:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium">{row.title}</span>
          <span className="inline-flex shrink-0 items-center rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
            {whenLabel(row.created_at)}
          </span>
          {handled ? (
            <span className="inline-flex shrink-0 items-center rounded-full bg-success-muted px-2 py-0.5 text-xs font-medium text-success-muted-foreground">
              Załatwione{row.handled_by_name ? ` · ${row.handled_by_name}` : ""}
            </span>
          ) : null}
        </div>
        <p className="line-clamp-2 text-xs text-muted-foreground">{row.message}</p>
      </div>
      <div className="flex gap-1.5">
        {row.link ? (
          <Link
            href={row.link}
            className={buttonVariants({ size: "sm", variant: handled ? "outline" : "primary" })}
          >
            Otwórz
          </Link>
        ) : null}
        {!handled ? (
          <Button size="sm" variant="ghost" disabled={busy} onClick={onHandled}>
            Załatwione
          </Button>
        ) : null}
      </div>
    </li>
  );
}
