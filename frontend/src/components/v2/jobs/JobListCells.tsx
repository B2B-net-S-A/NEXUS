"use client";

/**
 * Komórki wiersza listy rekrutacji (rekrutacja v3): zwarte liczby per grupa
 * etapów, pigułka „Wymaga ruchu" i link „+N propozycji".
 *
 * Osobny plik, bo `JobsListV2.tsx` jest już długi, a te trzy elementy mają
 * własną logikę tonu i odmiany — testowalną bez montowania całej listy.
 */
import { countPl } from "@/lib/plural-pl";
import Link from "next/link";
import type { MouseEvent } from "react";

import {
  REQUEST_STATUS_META,
  requestStatusOf,
  type RequestStatusTone,
} from "@/lib/request-status";
import { cn } from "@/lib/utils";
import {
  buildStageFunnel,
  funnelGroupStages,
  funnelGroupTitle,
  FUNNEL_GROUP_LABELS,
  FUNNEL_GROUP_ORDER,
  type FunnelGroupKey,
  type PipelineStageSummary,
} from "@/lib/job-pipeline-funnel";

/** Skrót grupy pod liczbą — pełna nazwa i etapy szablonu są w tooltipie. */
const GROUP_SHORT: Record<FunnelGroupKey, string> = {
  new: "Now",
  screening: "Scr",
  verified: "Zwer",
  with_client: "Kl",
  contract: "Um",
  hired: "Zatr",
};

/** Legenda nagłówka kolumny — te same nazwy co tooltipy komórek. */
export const STAGE_COUNTS_LEGEND = FUNNEL_GROUP_ORDER.map(
  (key) => `${GROUP_SHORT[key]} = ${FUNNEL_GROUP_LABELS[key]}`,
).join(" · ");

/**
 * Sześć liczb w stałej kolejności lejka. Zero jest wyszarzone (grupa istnieje,
 * nikt w niej nie stoi), zatrudnieni mają ton sukcesu — to wynik, nie etap.
 */
export function JobStageCounts({ summary }: { summary: PipelineStageSummary }) {
  const groups = buildStageFunnel(summary);
  const stages = funnelGroupStages(summary);
  const spoken = groups.map((g) => `${g.label} ${g.count}`).join(", ");
  return (
    <div
      role="group"
      aria-label={`Etapy: ${spoken}`}
      className="flex items-stretch gap-1"
      data-testid="job-stage-counts"
    >
      {groups.map((g) => (
        <span
          key={g.key}
          data-group={g.key}
          title={funnelGroupTitle(g, stages[g.key])}
          className={cn(
            "flex min-w-[26px] flex-col items-center rounded-md border px-1 py-0.5 leading-none",
            g.count === 0
              ? "border-transparent text-muted-foreground/60"
              : g.key === "hired"
                ? "border-success/30 bg-success/10 text-success"
                : "border-border bg-muted/50 text-foreground",
          )}
        >
          <span className="text-xs font-semibold tabular-nums">{g.count}</span>
          <span
            aria-hidden="true"
            className="mt-0.5 text-[10px] text-muted-foreground"
          >
            {GROUP_SHORT[g.key]}
          </span>
        </span>
      ))}
    </div>
  );
}

export type NeedsActionTone = "muted" | "warning" | "danger";

/** 0 = na bieżąco; 1–4 = do zrobienia; 5+ = zaległość. */
export function needsActionTone(count: number): NeedsActionTone {
  if (count <= 0) return "muted";
  return count >= 5 ? "danger" : "warning";
}

const NEEDS_ACTION_CLASS: Record<NeedsActionTone, string> = {
  muted: "border-transparent text-muted-foreground",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-destructive/30 bg-destructive/10 text-destructive",
};

/**
 * `count == null` = odpowiedź bez pola (np. stary backend) → kreska, NIE
 * „na bieżąco": brak wiedzy to nie to samo co zero.
 */
export function JobNeedsActionPill({
  count,
}: {
  count: number | null | undefined;
}) {
  if (count == null) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const tone = needsActionTone(count);
  return (
    <span
      data-testid="job-needs-action"
      data-tone={tone}
      title={
        count > 0
          ? `Kandydaci, u których następny ruch należy do rekrutera: ${count}`
          : "Żaden kandydat nie czeka na ruch rekrutera"
      }
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium tabular-nums",
        NEEDS_ACTION_CLASS[tone],
      )}
    >
      {count > 0 ? `${count} do ruchu` : "na bieżąco"}
    </span>
  );
}

/**
 * Stos wejściowy (Ogłoszenia, Nowi) — zgłoszenia, których nikt nie ruszył.
 * Osobno od „do ruchu" (decyzja 21.09.2026): na produkcji jedna rekrutacja
 * miała 14 651 takich osób i zamieniała licznik ruchu w szum. Zero = nic.
 */
export function JobReviewCount({ count }: { count: number | null | undefined }) {
  if (!count) return null;
  return (
    <span
      data-testid="job-review-count"
      title={`Zgłoszenia na etapach „Ogłoszenia” i „Nowi”, których nikt jeszcze nie przejrzał: ${count}`}
      className="whitespace-nowrap text-[11px] tabular-nums text-muted-foreground"
    >
      {`${count.toLocaleString("pl-PL")} do przejrzenia`}
    </span>
  );
}

/** 1 propozycja · 2–4 propozycje · 5+ propozycji (12–14 też „propozycji"). */
export function proposalsLabel(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (count === 1) return "+1 propozycja";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `+${count} propozycje`;
  }
  return `+${count} propozycji`;
}

export function jobProposalsHref(jobId: number): string {
  return `/jobs/${jobId}?tab=people&seg=proposals`;
}

/** Ukryte przy zerze; przy wierszu bez dostępu — tekst, nie link (detal = 403). */
export function JobProposalsLink({
  jobId,
  count,
  disabled,
}: {
  jobId: number;
  count: number | null | undefined;
  disabled?: boolean;
}) {
  if (!count || count <= 0) return null;
  const label = proposalsLabel(count);
  if (disabled) {
    return <span className="text-[11px] text-muted-foreground">{label}</span>;
  }
  return (
    <Link
      href={jobProposalsHref(jobId)}
      onClick={(e) => e.stopPropagation()}
      title="Otwórz propozycje kandydatów do tej rekrutacji"
      className="whitespace-nowrap text-[11px] font-medium text-primary hover:underline"
    >
      {label}
    </Link>
  );
}

// ── Lista v4 (0341): status requestu i podobne rekrutacje ────────────────────

const REQUEST_TONE_CLASS: Record<RequestStatusTone, string> = {
  search: "bg-primary/10 text-primary",
  client: "bg-success-muted text-success-muted-foreground",
  need: "bg-warning-muted text-warning-muted-foreground",
  done: "bg-muted text-muted-foreground",
};

/** Status requestu liczony przez serwer; nieznana wartość = kreska, nie zgadywanie. */
export function RequestStatusBadge({ status }: { status: unknown }) {
  const value = requestStatusOf(status);
  if (!value) return <span className="text-xs text-muted-foreground">—</span>;
  const meta = REQUEST_STATUS_META[value];
  return (
    <span
      title={meta.hint}
      className={cn(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-xs font-semibold",
        REQUEST_TONE_CLASS[meta.tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {meta.label}
    </span>
  );
}

export interface JobSimilarSummary {
  linked_count: number;
  linked_first: { id: number; title: string; reference_number: string | null } | null;
  reassigned_count: number;
  suggested: {
    count: number;
    sent_count: number;
    first: { id: number; title: string; reference_number: string | null };
  } | null;
}

/**
 * „↻" = rekrutacje połączone (osoby przepinają się same), „≈" = system
 * sugeruje podobne z osobami wysłanymi do klienta. Brak obu = kreska.
 */
export function SimilarJobsCell({
  similar,
  disabled,
  onOpen,
}: {
  similar: JobSimilarSummary | null | undefined;
  disabled?: boolean;
  onOpen: () => void;
}) {
  if (!similar || (similar.linked_count === 0 && !similar.suggested)) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const open = (e: MouseEvent) => {
    e.stopPropagation();
    if (!disabled) onOpen();
  };
  if (similar.linked_count > 0) {
    const first = similar.linked_first;
    const more = similar.linked_count > 1 ? ` +${similar.linked_count - 1}` : "";
    return (
      <button
        type="button"
        onClick={open}
        disabled={disabled}
        className="block max-w-full text-left"
        title="Połączone rekrutacje — otwórz, żeby zmienić"
      >
        <span className="inline-flex max-w-full items-center gap-1 truncate rounded-md border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-[11px] font-semibold text-primary">
          ↻ {first?.reference_number ?? first?.title ?? "Połączone"}
          {more}
        </span>
        <span className="mt-0.5 block text-[11px] text-muted-foreground">
          przepięto {similar.reassigned_count}
        </span>
      </button>
    );
  }
  const suggested = similar.suggested!;
  return (
    <button
      type="button"
      onClick={open}
      disabled={disabled}
      className="block max-w-full text-left"
      title="System znalazł podobne rekrutacje z osobami wysłanymi do klienta"
    >
      <span className="inline-flex items-center gap-1 rounded-md border border-dashed border-primary/40 px-1.5 py-0.5 text-[11px] font-semibold text-primary">
        ≈ {countPl(suggested.count, "podobna", "podobne", "podobnych")}
      </span>
      <span className="mt-0.5 block text-[11px] text-muted-foreground">
        {suggested.sent_count} u klienta ·{" "}
        <span className="font-semibold text-primary">Przepnij →</span>
      </span>
    </button>
  );
}
