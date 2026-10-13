"use client";

/**
 * „Co już wiemy” nad formularzem screeningu (P2, 14.10.2026) — dawniej
 * profil przed telefonem (0424, Ekran 1 „Nowi”, 07.10.2026).
 *
 * Do 14.10.2026 osoba w „Nowych” dostawała najpierw sam profil, a formularz
 * dopiero po osobnym przycisku startu rozmowy; obok stała blokada na 12 h.
 * Teraz formularz stoi od razu (pierwszy zapis bierze osobę na 12 h,
 * `screening_form._claim_on_save`), a profil to zwijany blok nad nim:
 * rozwinięty, dopóki formularz jest pusty, po pierwszym zapisie zwinięty do
 * jednej linii skrótu.
 *
 * W środku to, co trzeba wiedzieć przed wybraniem numeru: obecne stanowisko
 * i staż, „W bazie od”, skąd osoba przyszła i jak pasowała przy wejściu,
 * „Warunki — co już wiemy” (ostatnio podana stawka, dostępność i tryb pracy —
 * te same reguły `lib/person-facts` co fakty doku), „Wcześniej u nas”
 * (ostatnia zakończona rekrutacja z wynikiem i wcześniejsze notatki z „Pokaż”)
 * i inne rekrutacje (`/quick-view`, ten sam klucz co szybki podgląd na liście
 * kandydatów). Profil kandydata, notatki i stawki czytają klucze, które dok
 * osoby ma już w cache; każde z tych zapytań jest dodatkiem — jego awaria
 * daje „—” albo komunikat z „Ponów”, nigdy pustkę udającą brak danych.
 *
 * W głowie bloku „Nie odebrał” (ta sama notatka-próba co dok). Ostatnia
 * notatka nie ma tu osobnej sekcji — notatki są w panelu osoby.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Loader2, PhoneOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { isRecruitmentEnded } from "@/components/v2/candidate-profile/profile-helpers";
import { candidateNoteItems, useCandidateNotes } from "@/components/v2/pages/candidate-notes-query";
import { useCandidateRecruitmentOutcomes } from "@/components/v2/pages/candidate-outcomes-query";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { notesCountLabel, splitPersonNotes } from "@/components/v2/person/notes-by-recruitment";
import { PersonFacts } from "@/components/v2/person/PersonFacts";
import { inBaseSourceText, inBaseView, type CandidateInBase } from "@/components/v2/person/PersonInBase";
import { useNoAnswerNote } from "@/hooks/useNoAnswerNote";
import api, { candidatesApi } from "@/lib/api";
import { useRateOverview } from "@/lib/api/candidateRates";
import { aiScreeningBadge } from "@/lib/board-card-badges";
import { autoMatchBadgeLabel, autoMatchBadgeTitle } from "@/lib/candidate-notes-view";
import { hourlyText, monthYear } from "@/lib/candidate-rate";
import { notesAvailabilityOrigin } from "@/lib/notes-facts";
import { availabilityText, onsiteText } from "@/lib/person-facts";
import { contactAttemptsLabel } from "@/lib/recommendation-card";
import { entrySourceLabel, recruitmentOutcome } from "@/lib/recruitment-stage-label";
import { countPl } from "@/lib/plural-pl";
import { cn, formatDate } from "@/lib/utils";

/** Wycinek odpowiedzi `/api/candidates/{id}/quick-view`, którego używa profil. */
export interface BeforeCallQuickView {
  candidate: { city?: string | null; location?: string | null };
  current_position?: { title: string | null; started_at: string | null } | null;
  current_recruitments?: Array<{
    job_id: number;
    job_title: string;
    client_name: string | null;
    stage_name: string;
    moved_at: string;
  }>;
  contact_attempts?: number;
  cv_highlights?: { years_experience?: number | null } | null;
}

/** Wycinek profilu kandydata (`GET /api/candidates/{id}`) — warunki, które już znamy. */
interface CandidateConditions extends CandidateInBase {
  availability_date?: string | null;
  availability_status?: string | null;
  notice_period?: number | null;
  notice_period_unit?: string | null;
  max_onsite_days_per_week?: number | null;
  cv_extracted_data?: unknown;
}

/** Po tylu miesiącach od ostatniej notatki warunki trzeba potwierdzić w rozmowie. */
const STALE_AFTER_MONTHS = 6;
const MONTH_MS = 30.44 * 24 * 60 * 60 * 1000;

function monthsSince(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  return Math.floor((now - at) / MONTH_MS);
}

function yearsText(years: number | null | undefined): string | null {
  if (years == null || !Number.isFinite(years)) return null;
  const n = Math.round(years);
  if (n === 1) return "1 rok";
  const last = n % 10;
  const lastTwo = n % 100;
  const form = last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "lata" : "lat";
  return `${n} ${form}`;
}

function entryMatchText(item: KanbanItem): { text: string; title?: string } | null {
  const auto = autoMatchBadgeLabel(item.entry_auto_match);
  if (auto) return { text: auto, title: autoMatchBadgeTitle(item.entry_auto_match) };
  const ai = aiScreeningBadge(item.entry_ai_screening);
  if (ai) return { text: ai.label, title: ai.title };
  return null;
}

export interface BeforeCallProfileProps {
  item: KanbanItem;
  jobId: number;
  readOnly: boolean;
  /**
   * Rozwinięty na start — formularz jest jeszcze pusty. Zmiana na `false`
   * (pierwszy zapis) zwija blok, chyba że rekruter sam go potem rozwinie.
   */
  defaultOpen?: boolean;
  /** „Pokaż” przy wcześniejszych notatkach — otwiera „Historię osoby” w podglądzie obok. */
  onOpenHistory?: () => void;
}

export function BeforeCallProfile({
  item,
  jobId,
  readOnly,
  defaultOpen = true,
  onOpenHistory,
}: BeforeCallProfileProps) {
  const [explicitOpen, setExplicitOpen] = useState<boolean | null>(null);
  const open = explicitOpen ?? defaultOpen;
  const wasDefaultOpen = useRef(defaultOpen);
  useEffect(() => {
    // Pierwszy zapis formularza: blok wraca do domyślnego (zwiniętego) stanu.
    if (wasDefaultOpen.current && !defaultOpen) setExplicitOpen(null);
    wasDefaultOpen.current = defaultOpen;
  }, [defaultOpen]);
  const bodyId = useId();

  const candidateId = item.candidate_id;
  const query = useQuery<BeforeCallQuickView>({
    queryKey: candidateQueryKeys.quickView(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${candidateId}/quick-view`, { signal }).then((r) => r.data),
    enabled: candidateId > 0,
    staleTime: 30_000,
  });
  const noAnswer = useNoAnswerNote({ candidateId, jobId });
  const data = query.data;
  const position = data?.current_position?.title?.trim() || null;
  const since = data?.current_position?.started_at ? formatDate(data.current_position.started_at) : null;
  const others = (data?.current_recruitments ?? []).filter((r) => r.job_id !== jobId);
  const attempts = data?.contact_attempts ?? item.contact_attempts ?? 0;
  const match = entryMatchText(item);
  const source = entrySourceLabel(item.entry_source);

  // ── Co już wiemy: warunki z profilu i ostatnio podana stawka ─────────────
  // Ten sam klucz i ta sama trasa co dok osoby — w panelu odpowiedź jest w cache.
  const detailQuery = useQuery<CandidateConditions>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as CandidateConditions),
    enabled: candidateId > 0,
    staleTime: 60_000,
  });
  const detail = detailQuery.data ?? null;
  const inBase = inBaseView(detail);
  const inBaseText = inBase
    ? [inBase.dateLabel, inBase.ageLabel, inBaseSourceText(detail)].filter(Boolean).join(" · ")
    : null;
  const rateQuery = useRateOverview(candidateId, candidateId > 0);
  const latestRate = hourlyText(rateQuery.data?.latest_amount);
  const latestRateWhen = monthYear(rateQuery.data?.latest_at ?? null);
  const rateFrom = hourlyText(item.candidate_rate_from_hourly);
  const availabilityOrigin = detail ? notesAvailabilityOrigin(detail) : undefined;

  // ── Wcześniej u nas: ostatnia zakończona rekrutacja i notatki spoza tej ──
  const notesQuery = useCandidateNotes(candidateId);
  const outcomesQuery = useCandidateRecruitmentOutcomes(candidateId);
  const earlier = useMemo(() => {
    const split = splitPersonNotes(candidateNoteItems(notesQuery.data), jobId);
    const newestAt = split.earlier
      .filter((note) => !note.is_system && note.created_at)
      .map((note) => String(note.created_at))
      .sort()
      .pop();
    return { count: split.earlierHuman, newestAt: newestAt ?? null };
  }, [notesQuery.data, jobId]);
  const lastEnded = useMemo(
    () =>
      (outcomesQuery.data ?? [])
        .filter(
          (row) =>
            row.job_id !== jobId &&
            isRecruitmentEnded({ job_status: row.job_status, latest_stage: row.latest_stage }),
        )
        .sort((a, b) => Date.parse(b.last_seen ?? "") - Date.parse(a.last_seen ?? ""))[0] ?? null,
    [outcomesQuery.data, jobId],
  );
  const lastEndedOutcome = lastEnded ? recruitmentOutcome(lastEnded) : null;
  const staleMonths = monthsSince(earlier.newestAt, Date.now());

  const rateValue = latestRate ?? (rateFrom ? `od ${rateFrom}` : null);
  const availabilityValue = availabilityText(
    detail
      ? {
          date: detail.availability_date,
          status: detail.availability_status,
          noticePeriod: detail.notice_period,
          // Profil bez jednostki okresu wypowiedzenia — dni, jak w doku.
          noticeUnit: detail.notice_period_unit ?? "days",
        }
      : null,
  );
  const failed = query.isError || detailQuery.isError || notesQuery.isError;
  // Zwinięty blok: jedna linia skrótu zamiast faktów.
  const summary = [
    position,
    rateValue,
    availabilityValue,
    others.length > 0
      ? `w ${countPl(others.length, "innej rekrutacji", "innych rekrutacjach", "innych rekrutacjach")}`
      : null,
    lastEndedOutcome ? `wcześniej: ${lastEndedOutcome.label}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      aria-label="Co już wiemy"
      className="rounded-lg border border-border bg-muted/20 text-[13px]"
      data-testid="before-call-profile"
      data-open={open ? "" : undefined}
    >
      <div className="flex items-start gap-2 px-3 py-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setExplicitOpen(!open)}
          className="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <ChevronRight
              className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")}
              aria-hidden
            />
            Co już wiemy
          </span>
          {!open && summary ? (
            <span
              className="w-full truncate pl-5 text-xs text-muted-foreground"
              title={summary}
              data-testid="before-call-summary"
            >
              {summary}
            </span>
          ) : null}
          {!open && failed ? (
            // Zwinięty blok nie może udawać kompletu, gdy część odczytu padła.
            <span className="pl-5 text-[11px] text-destructive-muted-foreground" role="alert">
              Część danych się nie wczytała — rozwiń, żeby ponowić.
            </span>
          ) : null}
        </button>
        {!readOnly ? (
          <Button
            size="sm"
            variant="outline"
            className="shrink-0"
            disabled={noAnswer.isPending}
            onClick={() => noAnswer.mutate()}
          >
            <PhoneOff className="h-3.5 w-3.5" aria-hidden /> Nie odebrał
          </Button>
        ) : null}
      </div>

      <div id={bodyId} hidden={!open} className="space-y-3 border-t border-border px-3 pb-3 pt-2.5">
        {query.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Wczytywanie profilu…
          </p>
        ) : query.isError ? (
          <p role="alert" className="text-xs text-destructive">
            Nie udało się wczytać profilu kandydata.{" "}
            <button type="button" className="font-medium underline underline-offset-2" onClick={() => void query.refetch()}>
              Ponów
            </button>
          </p>
        ) : null}

        <PersonFacts
          testId="before-call-facts"
          title="Kandydat"
          pairs
          rows={[
            {
              label: "Stanowisko",
              wide: true,
              value: position ? `${position}${since ? ` · od ${since}` : ""}` : null,
            },
            // „W bazie od” (13.10.2026): przed telefonem widać, czy to świeża osoba.
            { label: "W bazie od", wide: true, value: inBaseText },
            { label: "Doświadczenie", value: yearsText(data?.cv_highlights?.years_experience) },
            { label: "Lokalizacja", value: data?.candidate.city?.trim() || data?.candidate.location?.trim() || null },
            { label: "Źródło", value: source },
            {
              label: "Kontakt",
              value: attempts > 0 ? contactAttemptsLabel(attempts) : "bez prób",
            },
            ...(match
              ? [
                  {
                    label: "Przy wejściu",
                    wide: true,
                    value: <span title={match.title}>{match.text}</span>,
                  },
                ]
              : []),
          ]}
        />

        <PersonFacts
          testId="before-call-conditions"
          title="Warunki — co już wiemy"
          pairs
          rows={[
            {
              label: "Stawka",
              wide: true,
              value: rateValue,
              hint: latestRate
                ? [
                    latestRateWhen ? `ostatnio podana ${latestRateWhen}` : "ostatnio podana",
                    rateFrom && rateFrom !== latestRate ? `najniższa ${rateFrom}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : null,
            },
            {
              label: "Dostępność",
              wide: true,
              value: availabilityValue,
              hint: availabilityOrigin?.text,
            },
            { label: "Tryb pracy", wide: true, value: onsiteText(detail?.max_onsite_days_per_week) },
          ]}
        />
        {detailQuery.isError ? (
          // Kreska przy dostępności i trybie nie może znaczyć „nie wiemy”, gdy padł odczyt.
          <p role="alert" className="text-xs text-destructive-muted-foreground">
            Nie udało się wczytać warunków z profilu.{" "}
            <button
              type="button"
              className="font-medium underline underline-offset-2"
              onClick={() => void detailQuery.refetch()}
            >
              Ponów
            </button>
          </p>
        ) : null}

        {lastEnded || earlier.count > 0 || notesQuery.isError ? (
          <section aria-label="Wcześniej u nas" className="space-y-1.5">
            <h3 className="text-xs font-semibold text-muted-foreground">Wcześniej u nas</h3>
            {notesQuery.isError ? (
              // Awaria odczytu nie może wyglądać jak osoba bez historii.
              <p role="alert" className="text-xs text-destructive-muted-foreground">
                Nie udało się sprawdzić wcześniejszych notatek.{" "}
                <button
                  type="button"
                  className="font-medium underline underline-offset-2"
                  onClick={() => void notesQuery.refetch()}
                >
                  Ponów
                </button>
              </p>
            ) : null}
            {lastEnded && lastEndedOutcome ? (
              <div className="rounded-md border border-border bg-muted/20 px-2.5 py-1.5 text-xs">
                <span className="font-medium text-foreground">
                  {lastEnded.job_title ?? `Rekrutacja #${lastEnded.job_id}`}
                </span>
                {lastEnded.client_name ? (
                  <span className="text-muted-foreground"> · {lastEnded.client_name}</span>
                ) : null}{" "}
                <Badge size="sm" variant={lastEndedOutcome.tone}>
                  {lastEndedOutcome.label}
                </Badge>
                <span className="block text-muted-foreground">
                  {[lastEnded.rejection_reason, monthYear(lastEnded.last_seen)].filter(Boolean).join(" · ") ||
                    "bez zapisanego powodu"}
                </span>
              </div>
            ) : null}
            {earlier.count > 0 ? (
              <p className="text-xs text-muted-foreground">
                {notesCountLabel(earlier.count)} z wcześniejszych rozmów
                {earlier.newestAt ? ` · ostatnia ${formatDate(earlier.newestAt)}` : ""}.{" "}
                {onOpenHistory ? (
                  <button type="button" className="font-medium text-primary hover:underline" onClick={onOpenHistory}>
                    Pokaż
                  </button>
                ) : null}
              </p>
            ) : null}
            {staleMonths != null && staleMonths >= STALE_AFTER_MONTHS ? (
              <p role="note" className="text-[11px] text-warning-muted-foreground">
                Ostatnia wcześniejsza notatka sprzed {staleMonths} mies. — potwierdź warunki w rozmowie.
              </p>
            ) : null}
          </section>
        ) : null}

        <section aria-label="Historia z nami" className="space-y-1.5">
          <h3 className="text-xs font-semibold text-muted-foreground">W innych rekrutacjach</h3>
          {query.isSuccess && others.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nie jest teraz w innych rekrutacjach.</p>
          ) : (
            <ul className="space-y-1">
              {others.slice(0, 4).map((r) => (
                <li key={r.job_id} className="rounded-md border border-border bg-muted/20 px-2.5 py-1.5 text-xs">
                  <span className="font-medium text-foreground">{r.job_title}</span>
                  {r.client_name ? <span className="text-muted-foreground"> · {r.client_name}</span> : null}
                  <span className="block text-muted-foreground">
                    {r.stage_name} · od {formatDate(r.moved_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {others.length > 4 ? (
            <p className="text-[11px] text-muted-foreground">…i {others.length - 4} więcej — pełna lista w profilu.</p>
          ) : null}
        </section>
      </div>
    </section>
  );
}
