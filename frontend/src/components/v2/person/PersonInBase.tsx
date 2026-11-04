"use client";

/**
 * „W bazie od” w panelu osoby (13.10.2026, wariant A z makiet).
 *
 * Prośba rekrutera: świeże osoby są najlepsze, więc kiedy osoba trafiła do
 * bazy, ma być widać od razu. Trzy miejsca w panelu biorą to samo pole
 * z `GET /api/candidates/{id}` (ten sam klucz co dok — odpowiedź jest już
 * w cache):
 * - blok „Osoba w bazie” na górze „Notatek i historii” (od kiedy, skąd, kto
 *   dodał, od kiedy w tej rekrutacji),
 * - ostatni wiersz historii „Dodany do bazy”, jak w Traffit,
 * - pigułka „Nowy w bazie · N dni” w głowie panelu — tylko do 14 dni.
 *
 * Data i jej dokładność pochodzą z serwera (`candidate_added_date.py`):
 * osoba z Traffita bez daty u źródła dostaje „przed DD.MM.RRRR” i nigdy
 * pigułki. Zapytanie jest dodatkiem — awaria daje „—”, nie błąd w panelu.
 */

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { PersonFacts } from "@/components/v2/person/PersonFacts";
import { candidatesApi } from "@/lib/api";
import {
  addedToBaseTitle,
  addedToBaseView,
  formatWarsawDay,
  newInBaseDaysText,
  type AddedToBaseView,
} from "@/lib/added-to-base";
import { candidateOrigin, originSummary, type InviteSourceBrief } from "@/lib/candidate-origin";
import { entrySourceLabel } from "@/lib/recruitment-stage-label";

/** Wycinek `CandidateResponse` z polami „W bazie od”. */
export interface CandidateInBase {
  added_to_base_at?: string | null;
  added_to_base_exact?: boolean | null;
  added_via?: string | null;
  created_by_user?: { id: number; name?: string | null } | null;
  /** Tylko w szczegółach osoby: zgłoszenie przez link (rodzaj, właściciel, utm). */
  invite_source?: InviteSourceBrief | null;
}

export function useCandidateInBase(candidateId: number) {
  return useQuery<CandidateInBase>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as CandidateInBase),
    enabled: candidateId > 0,
    staleTime: 60_000,
  });
}

export function inBaseView(candidate: CandidateInBase | null | undefined): AddedToBaseView | null {
  if (!candidate) return null;
  return addedToBaseView({ at: candidate.added_to_base_at, exact: candidate.added_to_base_exact });
}

function addedByName(candidate: CandidateInBase | null | undefined): string | null {
  return candidate?.created_by_user?.name?.trim() || null;
}

/**
 * „CV upload · dodał(a) Anna K.”, „Link rekrutera · Jan K.” — człony, których
 * nie znamy, nie wchodzą. Ta sama reguła co „Skąd” w profilu osoby.
 */
export function inBaseSourceText(candidate: CandidateInBase | null | undefined): string | null {
  return originSummary(candidateOrigin(candidate));
}

export function PersonInBase({
  candidateId,
  item,
}: {
  candidateId: number;
  item: Pick<KanbanItem, "added_to_job_at" | "added_to_job_by_name" | "entry_source">;
}) {
  const { data } = useCandidateInBase(candidateId);
  const view = inBaseView(data);
  const sinceInJob = formatWarsawDay(item.added_to_job_at);
  const inJobHow =
    entrySourceLabel(item.entry_source) ??
    (item.added_to_job_by_name?.trim() ? `dodał(a) ${item.added_to_job_by_name.trim()}` : null);
  return (
    <PersonFacts
      testId="person-in-base"
      title="Osoba w bazie"
      rows={[
        {
          label: "W bazie od",
          value: view ? (
            <>
              <span className="font-medium">{view.dateLabel}</span>{" "}
              <span className="text-muted-foreground">· {view.ageLabel}</span>
            </>
          ) : null,
        },
        { label: "Skąd", value: inBaseSourceText(data) },
        {
          label: "W tej rekrutacji",
          value: [sinceInJob ? `od ${sinceInJob}` : null, inJobHow].filter(Boolean).join(" · ") || null,
        },
      ]}
    />
  );
}

/** Ostatni wiersz historii w „Notatkach i historii”: „Dodany do bazy”. */
export function AddedToBaseHistoryRow({ candidateId }: { candidateId: number }) {
  const { data } = useCandidateInBase(candidateId);
  const view = inBaseView(data);
  if (!view) return null;
  const who = inBaseSourceText(data);
  return (
    <div className="space-y-2" data-testid="history-added-to-base">
      <p className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
        <span>przed tą rekrutacją</span>
        <span className="h-px flex-1 bg-border" aria-hidden="true" />
      </p>
      <p className="flex gap-3">
        <span className="w-[92px] shrink-0 text-xs text-muted-foreground">{view.dateLabel}</span>
        <span className="mt-1 h-2.5 w-2.5 shrink-0 rotate-45 rounded-[2px] bg-info" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-foreground">Dodany do bazy</span>
          {who ? <span className="block text-xs text-muted-foreground">{who}</span> : null}
        </span>
      </p>
    </div>
  );
}

/** Pigułka w głowie panelu — tylko osoba dodana do bazy w ostatnich 14 dniach. */
export function NewInBasePill({ candidate }: { candidate: CandidateInBase | null | undefined }) {
  const view = inBaseView(candidate);
  if (!view?.isNew || view.days == null) return null;
  return (
    <Badge
      variant="info"
      size="sm"
      data-testid="new-in-base-pill"
      title={addedToBaseTitle(view, addedByName(candidate), candidate?.added_via)}
    >
      Nowy w bazie · {newInBaseDaysText(view.days)}
    </Badge>
  );
}
