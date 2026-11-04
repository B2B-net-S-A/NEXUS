"use client";

import Link from "next/link";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { LeagueMedalBadge } from "./LeagueTopbarButton";
import type { LeaguePanelRow, LeagueSentence, LeagueTopbarModel } from "./league-topbar-model";

export interface LeaguePanelProps {
  model: LeagueTopbarModel;
  /** Klik w link zamyka panel — Popover sam tego nie robi. */
  onNavigate?: () => void;
  /** Awaria zapytania: „Ponów” w panelu. */
  onRetry?: () => void;
}

const SENTENCE_CLASS: Record<LeagueSentence["tone"], string> = {
  default: "text-foreground",
  good: "text-success-muted-foreground",
  warn: "text-warning-muted-foreground",
};

const RANK_CLASS: Record<LeaguePanelRow["rankTone"], string> = {
  gold: "text-medal-gold-foreground",
  silver: "text-medal-silver-foreground",
  bronze: "text-medal-bronze-foreground",
  plain: "text-muted-foreground",
};

/**
 * Panel Ligi otwierany z przycisku w górnym pasku. Bez zapytań — rysuje model,
 * więc harness `/preview/kpi-topbar` pokazuje go z propsów.
 */
export function LeaguePanel({ model, onNavigate, onRetry }: LeaguePanelProps) {
  const panel = model.panel;
  return (
    <div className="flex max-h-[min(600px,calc(100dvh-6rem))] flex-col text-foreground">
      <header className="flex items-baseline justify-between gap-3 px-4 pb-2 pt-3.5">
        {/* Rozmiar na samym nagłówku — globalny styl `h2`/`h3` nie dziedziczy go z rodzica. */}
        <h2 className="text-sm font-semibold">{panel.title}</h2>
        {panel.aside ? <span className="shrink-0 text-xs text-muted-foreground">{panel.aside}</span> : null}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="flex flex-col gap-1.5 px-4 pb-3">
          <div className="flex items-center gap-2.5">
            <LeagueMedalBadge medal={panel.medal} size="lg" />
            <div className="min-w-0">
              <p className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="text-lg font-semibold leading-6">{panel.headline}</span>
                {panel.headlineValue ? (
                  <span className="text-sm font-semibold tabular-nums">· {panel.headlineValue}</span>
                ) : null}
              </p>
              {panel.sub ? <p className="text-xs leading-4 text-muted-foreground">{panel.sub}</p> : null}
            </div>
          </div>
          {panel.sentences.map((sentence) => (
            <p key={sentence.text} className={cn("text-[13px] leading-[18px]", SENTENCE_CLASS[sentence.tone])}>
              {sentence.text}
            </p>
          ))}
          {panel.failed && onRetry ? (
            <Button size="sm" variant="outline" className="self-start" onClick={onRetry}>
              Ponów
            </Button>
          ) : null}
        </section>

        {panel.breakdown ? (
          <section aria-label="Skąd Twoje punkty" className="border-t border-border px-4 py-2.5">
            <h3 className="mb-1 text-xs font-semibold text-muted-foreground">Skąd Twoje punkty</h3>
            <dl className="grid grid-cols-[1fr_auto_auto] gap-x-3.5 gap-y-0.5 text-[13px] tabular-nums">
              {panel.breakdown.rows.map((row) => (
                <div key={row.label} className="contents">
                  <dt>{row.label}</dt>
                  <dd className="text-right text-muted-foreground">{row.detail}</dd>
                  <dd className="text-right font-semibold">{row.points}</dd>
                </div>
              ))}
              {/* Jedna kreska przez całą szerokość — na komórkach rwała się na odstępach kolumn. */}
              <div aria-hidden className="col-span-3 my-0.5 border-t border-border" />
              <div className="contents">
                <dt>Razem</dt>
                <dd />
                <dd className="text-right font-semibold">{panel.breakdown.total}</dd>
              </div>
            </dl>
          </section>
        ) : null}

        {panel.condition ? (
          <section className="border-t border-border px-4 py-2.5">
            <p className="flex items-start gap-2 text-[13px] leading-[18px]">
              {panel.condition.met ? (
                <span
                  aria-hidden
                  className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-success-muted text-success-muted-foreground"
                >
                  <Check className="h-2.5 w-2.5" strokeWidth={3.5} />
                </span>
              ) : (
                <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
              )}
              <span>{panel.condition.text}</span>
            </p>
          </section>
        ) : null}

        {panel.rows.length > 0 ? (
          <section aria-label={panel.rowsTitle ?? undefined} className="border-t border-border px-2 py-2.5">
            <div className="flex items-baseline justify-between px-2 pb-1">
              <h3 className="text-xs font-semibold text-muted-foreground">{panel.rowsTitle}</h3>
              {panel.rowsUnit ? <span className="text-xs text-muted-foreground">{panel.rowsUnit}</span> : null}
            </div>
            <ol className="flex flex-col text-[13px] tabular-nums">
              {panel.rows.map((row) => (
                <li
                  key={row.key}
                  aria-current={row.me ? "true" : undefined}
                  className={cn(
                    "grid h-7 grid-cols-[24px_1fr_auto_44px] items-center gap-2 rounded-md px-2",
                    row.me && "bg-primary/10 font-semibold",
                  )}
                >
                  <span className={cn("font-semibold", RANK_CLASS[row.rankTone])}>{row.rank}</span>
                  <span className="truncate">{row.name}</span>
                  <span className="text-right text-[11px] font-medium text-muted-foreground">{row.prize}</span>
                  <span className="text-right font-semibold">{row.value}</span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </div>
      {panel.footnote || panel.link ? (
        <footer className="flex items-center justify-between gap-3 border-t border-border px-4 pb-3 pt-2.5 text-xs leading-4">
          <span className="text-muted-foreground">{panel.footnote}</span>
          {panel.link ? (
            <Link
              href={panel.link.href}
              onClick={onNavigate}
              className="shrink-0 whitespace-nowrap font-medium text-primary hover:underline"
            >
              {panel.link.label} →
            </Link>
          ) : null}
        </footer>
      ) : null}
    </div>
  );
}
