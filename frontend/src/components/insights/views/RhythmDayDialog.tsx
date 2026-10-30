"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { AppModal } from "@/components/ds";
import { SectionError } from "@/components/insights/sections/_shared";
import { cn } from "@/lib/utils";
import {
  WORK_RHYTHM_SKIP_LABELS as SKIP_LABELS,
  workRhythmApi,
  workRhythmQueryKeys,
  type WorkRhythmDayDetail,
  type WorkRhythmSkipReason,
} from "@/lib/work-rhythm-api";
import { PanelLoading } from "./ViewKit";

/**
 * Rozkład dnia osoby w „Rytmie dnia” (decyzja Artura 29.10.2026): każda akcja
 * z godziną, ile dała punktów, a jeśli nic — dlaczego (ochrona przed nabijaniem).
 * Odpowiada na pytanie „czemu mam tak mało punktów”.
 */

function fmtPoints(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1).replace(".", ",");
}

/** Przerwy dnia jako „11:00–13:00”: pełne godziny bez akcji i prepa w środku dnia. */
export function fmtGaps(gaps: [number, number][]): string {
  return gaps.map(([a, b]) => `${a}:00–${b}:00`).join(", ");
}

export function DayBreakdown({ data }: { data: WorkRhythmDayDetail }) {
  // Suma ze wszystkich akcji (także przed 7:00 i po 20:00, poza osią godzin).
  const counted = data.events.reduce((a, e) => a + e.points, 0);
  const skipped = (Object.entries(data.skipped) as [WorkRhythmSkipReason, number][]).sort((a, b) => b[1] - a[1]);
  const hours = [...new Set(data.events.map((e) => e.hour))].sort((a, b) => a - b);
  const gaps = data.gaps ?? [];
  if (data.events.length === 0) {
    return <p className="text-sm text-muted-foreground">Tego dnia nie ma żadnej akcji w NEXUSIE.</p>;
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {gaps.length ? (
          <>
            Przerwy w środku dnia (godzina bez akcji i prepa): <b className="tabular-nums text-foreground">{fmtGaps(gaps)}</b>
          </>
        ) : (
          "Bez pełnej godziny przerwy w środku dnia."
        )}
      </p>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          Liczone: <b className="tabular-nums">{fmtPoints(Math.round(counted * 10) / 10)} pkt</b>
        </span>
        {skipped.map(([reason, value]) => (
          <span key={reason} className="text-muted-foreground">
            −{fmtPoints(value)} pkt: {SKIP_LABELS[reason]}
          </span>
        ))}
      </div>
      <div className="space-y-3">
        {hours.map((hour) => {
          const events = data.events.filter((e) => e.hour === hour);
          const pts = events.reduce((a, e) => a + e.points, 0);
          const thinIdx = hour - 7;
          return (
            <section key={hour} aria-label={`Godzina ${hour}:00`}>
              <p className="mb-1 flex items-baseline gap-2 text-xs font-semibold text-foreground">
                {hour}:00–{hour + 1}:00
                <span className="font-normal tabular-nums text-muted-foreground">{fmtPoints(Math.round(pts * 10) / 10)} pkt</span>
                {data.thin[thinIdx] ? (
                  <span className="font-normal text-warning-muted-foreground">drobiazgi przy jednym kandydacie — nie jest godziną pracy</span>
                ) : null}
              </p>
              <ul className="divide-y divide-border/60 rounded-md border border-border">
                {events.map((e, i) => (
                  <li key={i} className={cn("grid grid-cols-[48px_1fr_auto] items-baseline gap-3 px-3 py-1.5 text-sm", e.reason ? "text-muted-foreground" : "text-foreground")}>
                    <span className="tabular-nums text-xs text-muted-foreground">{e.time}</span>
                    <span className="min-w-0 truncate">
                      {e.label}
                      {e.candidate ? <span className="text-muted-foreground"> · {e.candidate}</span> : null}
                    </span>
                    <span className="text-right text-xs tabular-nums">
                      {e.reason ? `${fmtPoints(e.points)} — ${SKIP_LABELS[e.reason]}` : `${fmtPoints(e.points)} pkt`}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}

export function RhythmDayDialog({
  target,
  onClose,
}: {
  target: { userId: number; name: string; date: string; label: string } | null;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: target ? workRhythmQueryKeys.day(target.userId, target.date) : ["insights", "work-rhythm", "day", "none"],
    queryFn: () => workRhythmApi.day(target!.userId, target!.date),
    enabled: target !== null,
  });
  return (
    <AppModal
      open={target !== null}
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={target ? `${target.name} · ${target.label}` : ""}
      description="Każda akcja z tego dnia: ile dała punktów, a jeśli nic — dlaczego."
      size="lg"
    >
      {query.isPending ? <PanelLoading /> : null}
      {query.isError ? <SectionError label="Rozkład dnia" error={query.error} onRetry={() => void query.refetch()} /> : null}
      {query.isSuccess ? <DayBreakdown data={query.data} /> : null}
    </AppModal>
  );
}
