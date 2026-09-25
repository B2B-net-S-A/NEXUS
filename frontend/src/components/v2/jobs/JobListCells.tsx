"use client";

/**
 * Komórki wiersza listy rekrutacji: zwarte liczby per kolumna Tablicy,
 * termin, status requestu, plakietka podobnych rekrutacji, pigułka „Wymaga
 * ruchu" i link „+N propozycji".
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
  FUNNEL_GROUP_SHORT,
  type PipelineStageSummary,
} from "@/lib/job-pipeline-funnel";
import {
  classifyJobDeadline,
  deadlineRelativeLabel,
  formatDateOnly,
  type DeadlineUrgency,
} from "@/lib/job-deadline";
import { jobClientTitle, type JobNames } from "@/lib/job-names";

/**
 * Nazwa od klienta i numer u klienta pod tytułem dla rekrutera (0379).
 * Nazwa tylko wtedy, gdy różni się od tytułu w pierwszej linii.
 */
export function JobClientNames({ job }: { job: JobNames }) {
  const clientTitle = jobClientTitle(job);
  const reference = job.client_reference?.trim();
  if (!clientTitle && !reference) return null;
  return (
    <>
      {clientTitle && (
        <span className="min-w-0 max-w-[260px] truncate" title={`Nazwa od klienta: ${clientTitle}`}>
          „{clientTitle}”
        </span>
      )}
      {reference && (
        <span
          className="font-mono text-[10px] font-medium text-foreground/80"
          title="Numer u klienta"
          data-testid="client-reference"
        >
          {reference}
        </span>
      )}
    </>
  );
}

/** Legenda nagłówka kolumny — te same nazwy co tooltipy komórek. */
export const STAGE_COUNTS_LEGEND = FUNNEL_GROUP_ORDER.map(
  (key) => `${FUNNEL_GROUP_SHORT[key]} = ${FUNNEL_GROUP_LABELS[key]}`,
).join(" · ");

/** Szerokość jednej liczby — ta sama w nagłówku i w wierszu (kolumny się pokrywają). */
const STAGE_CELL = "w-[26px] shrink-0 text-center";

/**
 * Nagłówek kolumny „Etapy": skróty ośmiu kolumn Tablicy RAZ, nad liczbami
 * (lista v5 — do 24.09.2026 skrót stał pod każdą liczbą w każdym wierszu).
 * Pełna nazwa w `title` i w nazwie dostępnej.
 */
export function JobStageCountsHeader() {
  return (
    <div className="flex items-end gap-1" data-testid="job-stage-counts-header">
      {FUNNEL_GROUP_ORDER.map((key) => (
        <abbr
          key={key}
          title={FUNNEL_GROUP_LABELS[key]}
          aria-label={FUNNEL_GROUP_LABELS[key]}
          className={cn(STAGE_CELL, "text-[10px] font-medium no-underline")}
        >
          {FUNNEL_GROUP_SHORT[key]}
        </abbr>
      ))}
    </div>
  );
}

/**
 * Osiem liczb w kolejności kolumn Tablicy (te same co tablica: `placeStage`).
 * Zero jest wyszarzone (kolumna istnieje, nikt w niej nie stoi), zatrudnieni
 * mają ton sukcesu — to wynik, nie etap. Nazwy kolumn stoją w nagłówku.
 */
export function JobStageCounts({ summary }: { summary: PipelineStageSummary }) {
  const groups = buildStageFunnel(summary);
  const stages = funnelGroupStages(summary);
  const spoken = groups.map((g) => `${g.label} ${g.count}`).join(", ");
  return (
    <div
      role="group"
      aria-label={`Etapy: ${spoken}`}
      className="flex items-center gap-1"
      data-testid="job-stage-counts"
    >
      {groups.map((g) => (
        <span
          key={g.key}
          data-group={g.key}
          title={funnelGroupTitle(g, stages[g.key])}
          className={cn(
            STAGE_CELL,
            "rounded-md py-0.5 text-xs font-semibold tabular-nums leading-none",
            g.count === 0
              ? "text-muted-foreground/50"
              : g.key === "hired"
                ? "bg-success/10 text-success"
                : "bg-muted/60 text-foreground",
          )}
        >
          {g.count}
        </span>
      ))}
    </div>
  );
}

const DEADLINE_TONE_CLASS: Record<DeadlineUrgency, string> = {
  overdue: "text-destructive",
  soon: "text-warning",
  normal: "text-muted-foreground",
  none: "text-muted-foreground",
};

/**
 * Termin w wierszu: data i „za N dni" / „po terminie N dni". Po terminie —
 * ton destrukcyjny, ≤ 7 dni — ostrzegawczy, brak terminu — kreska.
 * `now` jest parametrem dla testów.
 */
export function JobDeadlineCell({
  deadline,
  now,
}: {
  deadline: string | null | undefined;
  now?: Date;
}) {
  const info = classifyJobDeadline(deadline, now);
  const relative = deadlineRelativeLabel(info);
  if (info.urgency === "none" || !relative) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  return (
    <span
      data-testid="job-deadline"
      data-urgency={info.urgency}
      className="flex flex-col leading-tight"
    >
      <span className="whitespace-nowrap text-xs tabular-nums text-foreground">
        {formatDateOnly(deadline)}
      </span>
      <span
        className={cn(
          "whitespace-nowrap text-[11px]",
          info.urgency !== "normal" && "font-medium",
          DEADLINE_TONE_CLASS[info.urgency],
        )}
      >
        {relative}
      </span>
    </span>
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
 * Plakietka „Podobne rekrutacje" w linii pod tytułem (lista v5 — do
 * 24.09.2026 osobna kolumna). „↻" = rekrutacje połączone (osoby przepinają się
 * same), „≈" = system sugeruje podobne z osobami wysłanymi do klienta. Brak
 * obu = nic (w linii metadanych kreska byłaby szumem).
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
    return null;
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
        data-testid="job-similar-badge"
        className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-md border border-primary/30 bg-primary/5 px-1.5 py-px text-[11px] text-primary hover:bg-primary/10"
        title="Połączone rekrutacje — otwórz, żeby zmienić"
      >
        <span className="truncate font-semibold">
          ↻ {first?.reference_number ?? first?.title ?? "Połączone"}
          {more}
        </span>
        <span className="shrink-0 text-muted-foreground">·</span>
        <span className="shrink-0 text-muted-foreground">
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
      data-testid="job-similar-badge"
      className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-md border border-dashed border-primary/40 px-1.5 py-px text-[11px] text-primary hover:bg-primary/5"
      title="System znalazł podobne rekrutacje z osobami wysłanymi do klienta"
    >
      <span className="shrink-0 font-semibold">
        ≈ {countPl(suggested.count, "podobna", "podobne", "podobnych")}
      </span>
      <span className="shrink-0 text-muted-foreground">
        · {suggested.sent_count} u klienta ·
      </span>
      <span className="shrink-0 font-semibold">Przepnij →</span>
    </button>
  );
}
