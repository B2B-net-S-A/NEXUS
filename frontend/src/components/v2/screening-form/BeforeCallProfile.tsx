"use client";

/**
 * Profil przed telefonem (0424, Ekran 1 „Nowi”, 07.10.2026): lewa kolumna
 * panelu osoby, zanim rekruter zacznie rozmowę. CV stoi obok w podglądzie.
 *
 * Wszystko, co trzeba wiedzieć przed wybraniem numeru: obecne stanowisko
 * i staż, skąd osoba przyszła i jak pasowała przy wejściu, w jakich innych
 * rekrutacjach jest teraz, ostatnia notatka i próby kontaktu (`/quick-view`,
 * ten sam klucz co szybki podgląd na liście kandydatów).
 *
 * 12.10.2026: także to, co już wiemy z wcześniejszych rozmów — ostatnio
 * podana stawka, dostępność i tryb pracy (te same reguły `lib/person-facts`
 * co fakty doku) oraz ostatnia zakończona rekrutacja z wynikiem i liczba
 * wcześniejszych notatek z „Pokaż”. Od 09.10.2026 głowa rozwiniętego panelu
 * nie pokazuje faktów w „Nowych”, więc przed telefonem nie było ich nigdzie.
 * Profil kandydata, notatki i stawki czytają klucze, które dok osoby ma już
 * w cache; każde z tych zapytań jest dodatkiem — jego awaria daje „—”.
 *
 * Akcje: „Biorę — 12 h” (ta sama blokada co karta), „Nie odebrał” (ta sama
 * notatka-próba co dok) i „Zacznij screening” — formularz w miejscu profilu.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, Loader2, PhoneOff, UserPlus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { isRecruitmentEnded } from "@/components/v2/candidate-profile/profile-helpers";
import { candidateNoteItems, useCandidateNotes } from "@/components/v2/pages/candidate-notes-query";
import { useCandidateRecruitmentOutcomes } from "@/components/v2/pages/candidate-outcomes-query";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { notesCountLabel, splitPersonNotes } from "@/components/v2/person/notes-by-recruitment";
import { PersonFacts } from "@/components/v2/person/PersonFacts";
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
import { formatDate } from "@/lib/utils";

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
  recent_notes?: Array<{
    id: number;
    content: string;
    created_at: string;
    author_name: string | null;
    pinned?: boolean;
  }>;
  contact_attempts?: number;
  cv_highlights?: { years_experience?: number | null } | null;
}

/** Wycinek profilu kandydata (`GET /api/candidates/{id}`) — warunki, które już znamy. */
interface CandidateConditions {
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
  /** „Biorę — 12 h” — ta sama blokada co przycisk na karcie. */
  onTake?: () => void;
  onStartScreening: () => void;
  /** „Pokaż” przy wcześniejszych notatkach — otwiera „Historię osoby” w podglądzie obok. */
  onOpenHistory?: () => void;
}

export function BeforeCallProfile({
  item,
  jobId,
  readOnly,
  onTake,
  onStartScreening,
  onOpenHistory,
}: BeforeCallProfileProps) {
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
  // Serwer stawia przypiętą notatkę pierwszą — przypięte są już nad panelem.
  const lastNote = (data?.recent_notes ?? []).find((n) => !n.pinned) ?? null;
  const attempts = data?.contact_attempts ?? item.contact_attempts ?? 0;
  const match = entryMatchText(item);
  const source = entrySourceLabel(item.entry_source);
  const claimedByOther = item.claim_user_id != null && item.can_take === false;
  const canTake = !readOnly && onTake != null && item.can_take === true && item.claim_user_id == null;

  // ── Co już wiemy: warunki z profilu i ostatnio podana stawka ─────────────
  // Ten sam klucz i ta sama trasa co dok osoby — w panelu odpowiedź jest w cache.
  const detailQuery = useQuery<CandidateConditions>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as CandidateConditions),
    enabled: candidateId > 0,
    staleTime: 60_000,
  });
  const detail = detailQuery.data ?? null;
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

  return (
    <section aria-label="Profil przed telefonem" className="space-y-3 text-[13px]" data-testid="before-call-profile">
      <div className="flex flex-wrap items-center gap-1.5">
        {!readOnly ? (
          <Button size="sm" onClick={onStartScreening}>
            <ClipboardCheck className="h-3.5 w-3.5" aria-hidden /> Zacznij screening
          </Button>
        ) : null}
        {canTake ? (
          <Button size="sm" variant="outline" onClick={onTake}>
            <UserPlus className="h-3.5 w-3.5" aria-hidden /> Biorę — 12 h
          </Button>
        ) : null}
        {!readOnly ? (
          <Button size="sm" variant="outline" disabled={noAnswer.isPending} onClick={() => noAnswer.mutate()}>
            <PhoneOff className="h-3.5 w-3.5" aria-hidden /> Nie odebrał
          </Button>
        ) : null}
      </div>
      {claimedByOther ? (
        <p role="note" className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          {item.claim_user_name?.trim() || "Inny rekruter"} ma tę osobę na 12 h
          {item.claim_until ? ` (do ${formatDate(item.claim_until)})` : ""} — zapis formularza odmówi, dopóki blokada
          trwa.
        </p>
      ) : null}

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
            value: latestRate ?? (rateFrom ? `od ${rateFrom}` : null),
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
            value: availabilityText(
              detail
                ? {
                    date: detail.availability_date,
                    status: detail.availability_status,
                    noticePeriod: detail.notice_period,
                    // Profil bez jednostki okresu wypowiedzenia — dni, jak w doku.
                    noticeUnit: detail.notice_period_unit ?? "days",
                  }
                : null,
            ),
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

      <section aria-label="Ostatnia notatka" className="space-y-1.5">
        <h3 className="text-xs font-semibold text-muted-foreground">Ostatnia notatka</h3>
        {lastNote ? (
          <div className="rounded-md border border-border bg-muted/20 px-2.5 py-2 text-xs">
            <p className="line-clamp-4 whitespace-pre-line text-foreground">{lastNote.content}</p>
            <p className="mt-0.5 text-muted-foreground">
              {lastNote.author_name ?? "Nieznany autor"} · {formatDate(lastNote.created_at)}
            </p>
          </div>
        ) : query.isSuccess ? (
          <p className="text-xs text-muted-foreground">Brak notatek o tej osobie.</p>
        ) : null}
      </section>
    </section>
  );
}
