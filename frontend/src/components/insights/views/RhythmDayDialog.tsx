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

function fmtHours(value: number): string {
  const total = Math.floor(value * 60 + 1e-6);
  return `${Math.floor(total / 60)} h ${String(total % 60).padStart(2, "0")}`;
}

function toMin(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

/** Przerwy między odcinkami pracy (≥ próg minut bez akcji i prepa). */
function breaks(spans: [string, string][]): string[] {
  return spans.slice(1).map((s, i) => `${spans[i][1]}–${s[0]} (${toMin(s[0]) - toMin(spans[i][1])} min)`);
}

export function DayBreakdown({ data }: { data: WorkRhythmDayDetail }) {
  // Suma ze wszystkich akcji (także przed 7:00 i po 20:00, poza osią godzin).
  const counted = data.events.reduce((a, e) => a + e.points, 0);
  const skipped = (Object.entries(data.skipped) as [WorkRhythmSkipReason, number][]).sort((a, b) => b[1] - a[1]);
  const hours = [...new Set(data.events.map((e) => e.hour))].sort((a, b) => a - b);
  const spans = data.spans ?? [];
  if (data.events.length === 0) {
    return <p className="text-sm text-muted-foreground">Tego dnia nie ma żadnej akcji w NEXUSIE.</p>;
  }
  return (
    <div className="space-y-4">
      <div className="space-y-1 text-sm">
        <p>
          Czas pracy: <b className="tabular-nums">{fmtHours(data.work_time ?? 0)}</b>
          {spans.length ? (
            <span className="text-muted-foreground"> · odcinki: {spans.map(([a, b]) => `${a}–${b}`).join(", ")}</span>
          ) : null}
        </p>
        {spans.length > 1 ? <p className="text-muted-foreground">Przerwy: {breaks(spans).join(", ")}</p> : null}
      </div>
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
