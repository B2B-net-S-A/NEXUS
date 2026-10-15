"use client";

/**
 * Komórki wiersza listy rekrutacji: zwarte liczby per kolumna Tablicy,
 * termin, status requestu, podobne rekrutacje (ikona w wierszu, plakietka
 * w Podglądzie), pigułka „Wymaga ruchu", link „+N propozycji", kolumna
 * „Rekruter” i krótka plakietka kategorii.
 *
 * Osobny plik, bo `JobsListV2.tsx` jest już długi, a te elementy mają
 * własną logikę tonu i odmiany — testowalną bez montowania całej listy.
 */
import { countPl } from "@/lib/plural-pl";
import { ArrowLeftRight, History, Trophy } from "lucide-react";
import Link from "next/link";
import type { MouseEvent } from "react";

import { Badge } from "@/components/ui/badge";
import {
  competenceShortLabel,
  competenceTone,
  useCompetenceCategories,
} from "@/components/v2/CompetenceCategoryBadge";
import { RecruiterCellEditor } from "@/components/v2/jobs/JobRecruiterEditor";
import { RecruiterChips } from "@/components/v2/jobs/RecruiterChips";
import { AD_PORTALS, portalAdHref, type JobAdPublicationBrief } from "@/lib/api/jobAd";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import {
  pinRecruiters,
  previousRecruitersOf,
  recruitersOf,
  workingRecruiters,
  type JobRecruiter,
  type JobTeamSource,
  type PreviousRecruiter,
} from "@/lib/job-team";
import type { PriorityLevel } from "@/lib/request-priority";
import {
  REQUEST_STATUS_META,
  requestStatusOf,
  type RequestStatusTone,
} from "@/lib/request-status";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import { championsTitle } from "@/lib/job-champions";
import {
  REQUEST_STAGE_META,
  requestStageOf,
  type RequestStage,
} from "@/lib/request-stage";
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
  formatDeadlineTime,
  formatDateOnly,
  type DeadlineUrgency,
} from "@/lib/job-deadline";

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

/** „1 gotowa do wysłania — czeka na Ciebie” · 2 gotowe · 5 gotowych. */
export function dlReadyLabel(count: number): string {
  return `${countPl(count, "gotowa", "gotowe", "gotowych")} do wysłania — czeka na Ciebie`;
}

/**
 * Osiem liczb w kolejności kolumn Tablicy (te same co tablica: `placeStage`).
 * Zero jest wyszarzone (kolumna istnieje, nikt w niej nie stoi), zatrudnieni
 * mają ton sukcesu — to wynik, nie etap. Nazwy kolumn stoją w nagłówku.
 *
 * `dlReady` (pole wiersza `dl_send_ready_count`, tylko u Delivery Leada): ile
 * osób z „QC CV” czeka na JEGO wysyłkę do klienta. Powyżej zera komórka „QC
 * CV” jest wypełniona kolorem akcji — Delivery Lead widzi swoje rekrutacje
 * bez nowej kolumny (tabela ledwo mieści się przy 1280 px).
 */
export function JobStageCounts({
  summary,
  dlReady,
}: {
  summary: PipelineStageSummary;
  dlReady?: number | null;
}) {
  const groups = buildStageFunnel(summary);
  const stages = funnelGroupStages(summary);
  const waiting = dlReady != null && dlReady > 0 ? dlReadyLabel(dlReady) : null;
  const spoken = groups
    .map((g) =>
      waiting && g.key === "cv_qc"
        ? `${g.label} ${g.count} (${waiting})`
        : `${g.label} ${g.count}`,
    )
    .join(", ");
  return (
    <div
      role="group"
      aria-label={`Etapy: ${spoken}`}
      className="flex items-center gap-1"
      data-testid="job-stage-counts"
    >
      {groups.map((g) => {
        const highlighted = waiting != null && g.key === "cv_qc";
        const title = funnelGroupTitle(g, stages[g.key]);
        return (
          <span
            key={g.key}
            data-group={g.key}
            data-dl-ready={highlighted ? "true" : undefined}
            title={highlighted ? `${waiting}\n${title}` : title}
            className={cn(
              STAGE_CELL,
              "rounded-md py-0.5 text-xs font-semibold tabular-nums leading-none",
              highlighted
                ? "bg-primary text-primary-foreground"
                : g.count === 0
                  ? "text-muted-foreground/50"
                  : g.key === "hired"
                    ? "bg-success/10 text-success"
                    : "bg-muted/60 text-foreground",
            )}
          >
            {g.count}
          </span>
        );
      })}
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
  deadlineTime,
  now,
}: {
  deadline: string | null | undefined;
  /** Godzina terminu (0406) — banki podają termin z godziną. */
  deadlineTime?: string | null;
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
        {formatDeadlineTime(deadlineTime) ? `, ${formatDeadlineTime(deadlineTime)}` : null}
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

export const REQUEST_TONE_CLASS: Record<RequestStatusTone, string> = {
  search: "bg-primary/10 text-primary",
  client: "bg-success-muted text-success-muted-foreground",
  need: "bg-warning-muted text-warning-muted-foreground",
  done: "bg-muted text-muted-foreground",
};

/**
 * Championi (D3, 15.10.2026): złota plakietka z pucharem — w nagłówku, na
 * liście i na karcie Tablicy ten sam kolor.
 */
export const CHAMPION_TONE_CLASS = "bg-medal-gold text-medal-gold-foreground";

/** Kropka statusu albo puchar przy championie. */
export function RequestStatusMark({ champion }: { champion: boolean }) {
  return champion ? (
    <Trophy className="h-3 w-3 shrink-0" aria-hidden="true" />
  ) : (
    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
  );
}

/** Status requestu liczony przez serwer; nieznana wartość = kreska, nie zgadywanie. */
export function RequestStatusBadge({ status }: { status: unknown }) {
  const value = requestStatusOf(status);
  if (!value) return <span className="text-xs text-muted-foreground">—</span>;
  const meta = REQUEST_STATUS_META[value];
  const champion = value === "champion";
  return (
    <span
      title={meta.hint}
      className={cn(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-xs font-semibold",
        champion ? CHAMPION_TONE_CLASS : REQUEST_TONE_CLASS[meta.tone],
      )}
    >
      <RequestStatusMark champion={champion} />
      {meta.label}
    </span>
  );
}

const STAGE_TONE_CLASS: Record<(typeof REQUEST_STAGE_META)[RequestStage]["tone"], string> = {
  ...REQUEST_TONE_CLASS,
  quiet: "bg-muted text-foreground",
};

/**
 * Stan requestu w wierszu listy (25.09.2026) — ta sama wartość co pigułka nad
 * listą (`request_stage`). Brak pola (starszy backend) = status requestu.
 * Przy championach (D3, 15.10.2026) złota plakietka, a imiona w dymku —
 * szerokość kolumny bez zmian.
 */
export function RequestStageBadge({
  stage,
  fallbackStatus,
  champions,
}: {
  stage: unknown;
  fallbackStatus?: unknown;
  champions?: readonly { name: string }[] | null;
}) {
  const value = requestStageOf(stage);
  if (!value) return <RequestStatusBadge status={fallbackStatus} />;
  const meta = REQUEST_STAGE_META[value];
  const champion = value === "champion";
  const named = champion && champions && champions.length > 0 ? championsTitle(champions) : null;
  return (
    <span
      title={named ?? meta.hint}
      className={cn(
        "inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-xs font-semibold",
        champion ? CHAMPION_TONE_CLASS : STAGE_TONE_CLASS[meta.tone],
      )}
    >
      <RequestStatusMark champion={champion} />
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
    /** `vector` — wektor rekrutacji ponad próg plakietki; `lexical` — dawny wzór. */
    kind?: "vector" | "lexical";
    first: { id: number; title: string; reference_number: string | null };
  } | null;
}

/** Jest co pokazać: rekrutacje połączone albo podpowiedź z osobami u klienta. */
export function hasSimilarJobs(
  similar: JobSimilarSummary | null | undefined,
): similar is JobSimilarSummary {
  return !!similar && (similar.linked_count > 0 || !!similar.suggested);
}

/** Zdanie dla ikony w wierszu — to samo, co plakietka mówi tekstem. */
export function similarJobsSummary(similar: JobSimilarSummary): string {
  if (similar.linked_count > 0) {
    const first = similar.linked_first;
    const more = similar.linked_count > 1 ? ` +${similar.linked_count - 1}` : "";
    return `Połączone rekrutacje: ${first?.reference_number ?? first?.title ?? "połączone"}${more} · przepięto ${similar.reassigned_count}`;
  }
  const suggested = similar.suggested!;
  return `Podobne rekrutacje: ${countPl(suggested.count, "podobna", "podobne", "podobnych")} · ${suggested.sent_count} u klienta — przepnij`;
}

/**
 * Ikona „Podobne rekrutacje” w kolumnie akcji wiersza (02.10.2026). Tekstowa
 * plakietka zeszła z wiersza do Podglądu; ikona zostawia przepięcie pod jednym
 * kliknięciem i otwiera to samo okno. Bez połączeń i podpowiedzi — nic.
 */
export function SimilarJobsIconButton({
  similar,
  disabled,
  onOpen,
}: {
  similar: JobSimilarSummary | null | undefined;
  disabled?: boolean;
  onOpen: () => void;
}) {
  if (!hasSimilarJobs(similar)) return null;
  const label = similarJobsSummary(similar);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onOpen();
      }}
      disabled={disabled}
      data-testid="job-similar-icon"
      title={label}
      aria-label={label}
      className="rounded-md p-1 text-primary transition-colors hover:bg-primary/10 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 pointer-coarse:p-2.5"
    >
      <ArrowLeftRight className="h-3.5 w-3.5" />
    </button>
  );
}

/**
 * Plakietka „Podobne rekrutacje" — od 02.10.2026 w Podglądzie rekrutacji
 * (`JobPreviewDetails`), nie pod tytułem w wierszu. „↻" = rekrutacje połączone
 * (osoby przepinają się same), „≈" = system sugeruje podobne z osobami
 * wysłanymi do klienta. Brak obu = nic.
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
  if (!hasSimilarJobs(similar)) return null;
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
      title={
        suggested.kind === "vector"
          ? "Rekrutacje o podobnej treści (wektor) z osobami wysłanymi do klienta"
          : "System znalazł podobne rekrutacje z osobami wysłanymi do klienta"
      }
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

// ── Rekruter, priorytet, data otwarcia (02.10.2026) ──────────────────────────

/**
 * Pola wiersza `GET /api/jobs`, które czytają kolumna „Rekruter”, plakietka
 * priorytetu, krótka plakietka kategorii i kolumna „Otwarta”.
 */
export interface JobListRowFields extends JobTeamSource {
  /** Osoby w roli „Rekruter”: pracujący w kolejności z serwera, na końcu propozycje. */
  recruiters?: JobRecruiter[] | null;
  /** Aktywne ogłoszenia wklejone ręcznie na portalach (kolumna „Ogłoszenia”). */
  ad_publications?: JobAdPublicationBrief[] | null;
  status?: string | null;
  /** Poziom priorytetu liczony przez serwer; bez niego `priorityLevelOf` czyta `priority`. */
  priority_level?: PriorityLevel;
  priority?: string | null;
  /** `opened_at`, a bez niej `created_at` — ta sama data, po której filtruje „Data otwarcia”. */
  opened_effective_at?: string | null;
  opened_at?: string | null;
  created_at?: string | null;
  delivery_lead_user?: { name?: string | null } | null;
  competence_category_id?: number | null;
  /**
   * Ilu kandydatów patrzący prowadzi w tej rekrutacji (otwarte procesy, których
   * jest właścicielem — dodał albo zweryfikował). Liczy serwer.
   */
  priority_carry_over_count?: number | null;
}

/**
 * „Twoi kandydaci: N” — rekrutacja, w której patrzący prowadzi swoich
 * kandydatów, choć nie jest jej Rekruterem (decyzja Artura 07.10.2026: rekruter
 * przepina swoich ludzi także do cudzych rekrutacji i wraca do nich z „Moje”).
 * Rekruterowi rekrutacji plakietka nic nie mówi, więc jej nie dostaje.
 */
export function myCandidatesOutsideTeam(
  job: JobListRowFields,
  viewerId: number | null | undefined,
): number | null {
  const count = job.priority_carry_over_count ?? 0;
  if (count <= 0 || viewerId == null) return null;
  const isRecruiter = workingRecruiters(recruitersOf(job)).some(
    (person) => person.user_id === viewerId,
  );
  return isRecruiter ? null : count;
}

/** Data w kolumnie „Otwarta” — pole serwera, a na starszym backendzie dotychczasowa reguła. */
export function jobOpenedDate(job: JobListRowFields): string | null {
  return job.opened_effective_at ?? job.opened_at ?? job.created_at ?? null;
}

/**
 * „Bez rekrutera” — nikt nie pracuje nad rekrutacją. Tło i tekst z pary
 * `warning-muted`: sam `text-warning` na białym nie ma kontrastu.
 */
/**
 * Komórka „Rekruter”, gdy cały zespół jest wśród „Poprzednich rekruterów”
 * (14.10.2026 — zejście z P1 albo zamknięcie): szare nazwisko i „poprzedni”
 * zamiast bursztynowego „Bez rekrutera” — to stan zamierzony, nie brak.
 * Dwie linie jak propozycja automatu, żeby nie poszerzać kolumny przy 1280 px.
 */
export function PreviousRecruitersPill({
  people,
}: {
  people: readonly PreviousRecruiter[];
}) {
  const first = shortenPersonName(people[0].name) ?? people[0].name;
  const more = people.length - 1;
  const tooltip = `${
    people.length === 1 ? "Poprzedni rekruter" : "Poprzedni rekruterzy"
  }: ${people.map((person) => person.name).join(", ")} — wrócą przy P1`;
  return (
    <span
      title={tooltip}
      data-testid="job-previous-recruiter"
      className="inline-flex min-w-0 max-w-full flex-col leading-tight text-muted-foreground"
    >
      <span aria-hidden="true" className="flex min-w-0 items-center gap-1 text-xs">
        <History className="h-3 w-3 shrink-0" />
        <span className="min-w-0 truncate">{first}</span>
        {more > 0 ? (
          <span className="shrink-0 rounded-full bg-muted px-1.5 text-[10px] font-medium">
            +{more}
          </span>
        ) : null}
      </span>
      <span aria-hidden="true" className="text-[11px]">
        poprzedni
      </span>
      <span className="sr-only">{tooltip}</span>
    </span>
  );
}

export function NoRecruiterPill({ className }: { className?: string }) {
  return (
    <span
      data-testid="job-no-recruiter"
      title="Rekrutacja nie ma Rekrutera — nikt jeszcze nad nią nie pracuje"
      className={cn(
        "inline-flex h-5 w-fit items-center whitespace-nowrap rounded-full bg-warning-muted px-2 text-[11px] font-medium text-warning-muted-foreground",
        className,
      )}
    >
      Bez rekrutera
    </span>
  );
}

const shortName = (name: string) => shortenPersonName(name) ?? name;

/**
 * Kolumna „Rekruter”: osoby, które pracują nad rekrutacją, a pod nimi
 * Delivery Lead drobnym drukiem (bez osobnej kolumny).
 *
 * Dwie osoby z nazwiska (jedna pod drugą) i „+N”, reszta w podpowiedzi —
 * jeden układ dla każdej szerokości. Osoby z filtra „Rekruter”
 * (`highlightIds`) i zalogowana osoba stoją pierwsze: do 12.10.2026 komórka
 * pokazywała tylko pierwszą osobę, więc po filtrze po drugiej osobie w wierszu
 * było widać nazwisko tej głównej. Propozycja automatu ma przerywaną ramkę
 * i dopisek „propozycja” — to jeszcze nie praca, więc sama propozycja nie gasi
 * filtra „Bez rekrutera”.
 *
 * Z `edit` osoby (albo „Bez rekrutera”) otwierają okienko edycji
 * (`RecruiterCellEditor`, 14.10.2026); „DL: …” zostaje poza nim.
 */
export function JobRecruiterCell({
  job,
  highlightIds = [],
  edit,
}: {
  job: JobListRowFields;
  /** Osoby z filtra „Rekruter” listy (`worked_by`). */
  highlightIds?: readonly number[];
  /** Rola przydzielająca przy niezamkniętej rekrutacji — o tym decyduje lista. */
  edit?: { jobId: number; jobTitle: string; canDecide: boolean };
}) {
  const dlName = job.delivery_lead_user?.name?.trim() || null;
  const viewerId = useAuthStore((s) => s.user?.id);
  const people = pinRecruiters(recruitersOf(job), [...highlightIds, viewerId]);
  const mine = myCandidatesOutsideTeam(job, viewerId);
  const previous = previousRecruitersOf(job);
  const content =
    people.length === 0 ? (
      previous.length > 0 ? (
        <PreviousRecruitersPill people={previous} />
      ) : (
        <NoRecruiterPill />
      )
    ) : (
      <span className="flex min-w-0">
        <RecruiterChips compact maxNames={2} size="sm" people={people} />
      </span>
    );
  return (
    <div
      className="flex min-w-0 max-w-[176px] flex-col gap-0.5"
      data-testid="job-recruiter-cell"
    >
      {edit ? (
        <RecruiterCellEditor
          jobId={edit.jobId}
          jobTitle={edit.jobTitle}
          job={job}
          canDecide={edit.canDecide}
        >
          {content}
        </RecruiterCellEditor>
      ) : (
        content
      )}
      {dlName && (
        <span
          className="min-w-0 truncate text-[11px] text-muted-foreground"
          title={`Delivery Lead: ${dlName}`}
          data-testid="job-delivery-lead"
        >
          DL: {shortName(dlName)}
        </span>
      )}
      {mine != null && (
        <span
          className="inline-flex h-5 w-fit items-center whitespace-nowrap rounded-full bg-info-muted px-2 text-[11px] font-medium text-info-muted-foreground"
          title={`Prowadzisz tu ${countPl(mine, "osobę", "osoby", "osób")}, choć nie jesteś Rekruterem tej rekrutacji`}
          data-testid="job-my-candidates"
        >
          Twoi kandydaci: {mine}
        </span>
      )}
    </div>
  );
}

/**
 * Krótka plakietka kategorii („Dev”, „QA”) w linii pod tytułem. Pełna nazwa
 * stoi w podpowiedzi. Bez kategorii albo zanim katalog się wczyta — nic
 * (nigdy surowy klucz).
 */
export function JobCategoryShortBadge({
  categoryId,
  className,
}: {
  categoryId?: number | null;
  className?: string;
}) {
  const { data } = useCompetenceCategories();
  const category =
    categoryId != null ? data?.find((c) => c.id === categoryId) : undefined;
  if (!category) return null;
  return (
    <Badge
      size="sm"
      variant={competenceTone(category.slug)}
      title={`Kategoria: ${category.name_pl}`}
      data-testid="job-category-short"
      className={cn("max-w-[140px] shrink-0", className)}
    >
      <span className="truncate">{competenceShortLabel(category.slug) ?? category.name_pl}</span>
    </Badge>
  );
}

// ── Ogłoszenia na portalach (13.10.2026) ─────────────────────────────────────

/**
 * Kolumna „Ogłoszenia”: gdzie rekrutacja ma wklejone ogłoszenie. Plakietka
 * z linkiem otwiera je na portalu; żółta znaczy „treść zmieniła się po
 * publikacji” albo „rekrutacja zamknięta, a ogłoszenie nadal wisi”.
 */
export function JobAdPublicationsCell({ job }: { job: JobListRowFields }) {
  const items = job.ad_publications ?? [];
  if (items.length === 0) {
    return <span className="text-[13px] text-muted-foreground">—</span>;
  }
  const closed = job.status === "closed";
  return (
    <div className="flex flex-col items-start gap-0.5" data-testid="job-ad-publications-cell">
      {AD_PORTALS.map(({ key, label, short }) => {
        const item = items.find((entry) => entry.portal === key);
        if (!item) return null;
        const href = portalAdHref(key, item.url);
        const note = closed
          ? "rekrutacja zamknięta — zdejmij ogłoszenie z portalu"
          : item.outdated
            ? "treść zmieniła się po publikacji — do aktualizacji"
            : null;
        const className = cn(
          "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full px-2 text-[11px] font-medium",
          note
            ? "bg-warning-muted text-warning-muted-foreground"
            : "bg-muted text-foreground",
        );
        // `title` na samym odnośniku zastąpiłby jego nazwę dostępną — stoi na opakowaniu.
        return (
          <span key={key} title={note ? `${label}: ${note}` : label}>
            {href ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${label} — otwórz ogłoszenie${note ? ` (${note})` : ""}`}
                className={cn(className, "hover:underline")}
                // Klik w wiersz otwiera rekrutację; odnośnik prowadzi na portal.
                onClick={(event) => event.stopPropagation()}
              >
                {short}
              </a>
            ) : (
              <span className={className} aria-label={`${label}${note ? ` (${note})` : ""}`}>
                {short}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}
