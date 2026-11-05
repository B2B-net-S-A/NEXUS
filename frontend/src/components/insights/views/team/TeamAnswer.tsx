"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ArrowRight, Check } from "lucide-react";

import { cn } from "@/lib/utils";
import { teamVerdict, tempoRows, type TeamSignal, type TempoRow } from "@/lib/insights-team-view";
import { SectionError } from "@/components/insights/sections/_shared";

import { PanelLoading } from "../ViewKit";
import type { TeamViewData } from "./useTeamViewData";

/** Ile sygnałów widać przed „Pokaż pozostałe”. */
const VISIBLE_SIGNALS = 3;

function TempoBar({ row }: { row: TempoRow }) {
  // Bez celu pasek zawsze byłby pełny, a to czyta się jak wykonany plan.
  if (row.target === null) return <div />;
  const current = row.current ?? 0;
  const scale = Math.max(row.target ?? 0, current, row.forecast ?? 0, 1);
  const pct = (v: number) => `${Math.min(100, (100 * v) / scale)}%`;
  const hit = row.target !== null && current >= row.target;
  return (
    <div className="relative h-5" aria-hidden>
      <div className="absolute inset-x-0 top-1.5 h-2 rounded-full bg-border" />
      {row.forecast != null && row.forecast > current ? (
        <div className="absolute left-0 top-1.5 h-2 rounded-full bg-primary/30" style={{ width: pct(row.forecast) }} />
      ) : null}
      <div className={cn("absolute left-0 top-1.5 h-2 rounded-full", hit ? "bg-success" : "bg-primary")} style={{ width: pct(current) }} />
      {row.expected !== null ? (
        <span className="absolute top-0 h-5 w-0.5 rounded-full bg-foreground" style={{ left: pct(row.expected) }} title={`Plan na teraz: ${Math.round(row.expected)}`} />
      ) : null}
    </div>
  );
}

function TempoStatus({ row }: { row: TempoRow }) {
  if (row.current === null) return <span className="text-muted-foreground">nie policzono</span>;
  const hit = row.target !== null && row.current >= row.target;
  const gap = row.expected !== null ? Math.round(row.current - row.expected) : null;
  if (hit) {
    return (
      <span className="inline-flex items-center gap-1 font-medium text-success-muted-foreground">
        <Check className="h-3.5 w-3.5" aria-hidden />
        cel zrobiony
      </span>
    );
  }
  if (gap !== null) {
    return gap < 0 ? (
      <span className="font-medium text-warning-muted-foreground">{Math.abs(gap)} poniżej planu</span>
    ) : (
      <span className="text-muted-foreground">zgodnie z planem</span>
    );
  }
  return row.target !== null ? <span className="text-muted-foreground">{Math.round((100 * row.current) / row.target)}% celu</span> : null;
}

function TempoLine({ row }: { row: TempoRow }) {
  const unit = row.unit ?? "";
  return (
    <li className="grid grid-cols-[7rem_minmax(0,1fr)_auto] items-center gap-x-3 py-2 sm:grid-cols-[9.5rem_minmax(0,1fr)_5.5rem_7.5rem]">
      <div className="min-w-0">
        <p className="text-sm font-medium leading-tight text-foreground">{row.label}</p>
        <p className="text-xs leading-tight text-muted-foreground">{row.horizon}</p>
      </div>
      <TempoBar row={row} />
      <p className="whitespace-nowrap text-right text-sm tabular-nums">
        <span className="font-semibold text-foreground">{row.current === null ? "—" : `${Math.round(row.current).toLocaleString("pl-PL")}${unit}`}</span>
        {row.target !== null ? <span className="text-muted-foreground"> / {Math.round(row.target).toLocaleString("pl-PL")}{unit}</span> : null}
      </p>
      <p className="col-span-3 text-xs sm:col-span-1">
        <TempoStatus row={row} />
        {row.note ? <span className="block text-muted-foreground">{row.note}</span> : null}
      </p>
    </li>
  );
}

export function SignalRow({ signal, dense = false }: { signal: TeamSignal; dense?: boolean }) {
  const body = (
    <>
      <span className={cn("shrink-0 font-semibold tabular-nums text-foreground", dense ? "w-7 text-sm" : "w-9 text-lg")}>{signal.count}</span>
      <span className="min-w-0 flex-1 text-sm leading-snug text-foreground">
        {signal.label}
        {signal.names.length > 0 ? <span className="block text-xs text-muted-foreground">{signal.names.join(", ")}</span> : null}
      </span>
      {signal.href ? <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden /> : null}
    </>
  );
  const className = cn("flex items-start gap-2 rounded-md px-1.5", dense ? "py-1" : "py-1.5");
  return signal.href ? (
    <Link href={signal.href} className={cn(className, "hover:bg-muted")}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

function SignalsColumn({ data }: { data: TeamViewData }) {
  const [all, setAll] = useState(false);
  const { attention } = data;
  if (attention.isPending) return <PanelLoading />;
  if (attention.isError) {
    return <SectionError label="Najpierw to" error={attention.error} onRetry={() => void attention.refetch()} />;
  }
  const { signals } = data;
  if (signals.length === 0) {
    return <p className="text-sm text-muted-foreground">Nic nie wymaga uwagi. Żaden sygnał nie przekracza progu.</p>;
  }
  const shown = all ? signals : signals.slice(0, VISIBLE_SIGNALS);
  return (
    <>
      <div>
        {shown.map((signal) => (
          <SignalRow key={signal.kind} signal={signal} />
        ))}
      </div>
      {signals.length > VISIBLE_SIGNALS ? (
        <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all} className="px-1.5 text-xs font-semibold text-primary hover:underline">
          {all ? "Zwiń" : `Pokaż pozostałe (${signals.length - VISIBLE_SIGNALS})`}
        </button>
      ) : null}
    </>
  );
}

/** Góra zakładki: pasek okresu, zdanie z odpowiedzią, tempo i sprawy na dziś. */
export function TeamAnswer({
  data,
  picker,
  seesTeam,
  stallHref,
}: {
  data: TeamViewData;
  picker: ReactNode;
  seesTeam: boolean;
  /** Klik w zdanie o zatorze otwiera ten etap w soczewce. */
  stallHref: string | null;
}) {
  const funnel = data.funnel.data;
  // Pasek okresu stoi zawsze: przy awarii jednego okresu trzeba móc przejść na inny.
  const bar = <div className="flex justify-end">{picker}</div>;
  if (data.funnel.isPending) {
    return (
      <>
        {bar}
        <PanelLoading />
      </>
    );
  }
  if (data.funnel.isError || !funnel) {
    return (
      <>
        {bar}
        <SectionError label="Zespół" error={data.funnel.error} onRetry={() => void data.funnel.refetch()} />
      </>
    );
  }
  const input = {
    window: funnel.period,
    running: data.running,
    workdays: data.workdays,
    funnel,
    goals: data.goals.data,
    inFlight: data.inFlight,
    rows: data.rows,
  };
  const { pace, stall } = teamVerdict(input);
  return (
    <>
      <div className="space-y-3">
        {bar}
        <h2 className="max-w-4xl text-xl font-semibold leading-snug tracking-tight text-foreground [text-wrap:pretty]">
          {pace}
          {stall ? (
            stallHref ? (
              <>
                {" "}
                <Link href={stallHref} className="text-muted-foreground underline decoration-dotted underline-offset-4 hover:text-primary">
                  {stall}
                </Link>
              </>
            ) : (
              <span className="text-muted-foreground"> {stall}</span>
            )
          ) : null}
        </h2>
      </div>

      <div className={cn("grid grid-cols-1 gap-6 border-y border-border py-3", seesTeam && "xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]")}>
        <section aria-label="Tempo" className="min-w-0">
          {data.goals.isPending ? (
            <PanelLoading />
          ) : data.goals.isError ? (
            <SectionError label="Cele zespołu" error={data.goals.error} onRetry={() => void data.goals.refetch()} />
          ) : (
            <>
              <ul className="divide-y divide-border/60">
                {tempoRows(input).map((row) => (
                  <TempoLine key={row.id} row={row} />
                ))}
              </ul>
              {!data.running && data.workdays ? (
                <p className="pt-1 text-xs text-muted-foreground">
                  Cel okresu zamkniętego: dzisiejsze cele dnia i tygodnia razy dni robocze. Historii celów nie ma.
                </p>
              ) : null}
            </>
          )}
        </section>
        {seesTeam ? (
          <section className="min-w-0 space-y-1">
            <h3 className="text-sm font-semibold text-foreground">Najpierw to</h3>
            <SignalsColumn data={data} />
          </section>
        ) : null}
      </div>
    </>
  );
}
