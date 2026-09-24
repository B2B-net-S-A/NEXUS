"use client";

/**
 * Panel „Moi ludzie" — lista rekrutera zawsze pod ręką.
 *
 * NIEMODALNY `<aside>` (wzór doku kanbanu, `KanbanBoardV2`): pod spodem da się
 * dalej pracować, bez scrimu i blokady przewijania. Kontekst bierze z adresu:
 * na `/jobs/{id}` dochodzi zakładka „Do tej rekrutacji", na `/candidates/{id}`
 * — „Gdzie przepiąć". Otwierają go: przycisk w topbarze, awatar, skrót `m`
 * i link z dzwonka (`?people=1`).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Users, X } from "lucide-react";

import {
  MY_PEOPLE_QUERY_PREFIX,
  myPeopleApi,
  myPeopleSummaryQueryKey,
  useMyPeople,
  useMyPeopleForJob,
  useMyPeopleSummary,
  type SnoozeReason,
} from "@/lib/api/myPeople";
import { recommendationsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { matchesQuery, splitPeople, summarySentences } from "@/lib/my-people-summary";
import { isForbiddenError } from "@/lib/view-state";
import { useMyPeoplePanel } from "@/store/my-people";
import { useUiStore } from "@/store/ui";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";
import { useCompetenceCategories } from "@/components/v2/CompetenceCategoryBadge";
import { AddToRecruitmentDialog, addToRecruitmentSummary } from "@/components/v2/recruitment/AddToRecruitmentDialog";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { MatchScoreBadge } from "@/components/ds/MatchScoreBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/Toast";
import {
  EmptyListView,
  ErrorView,
  ForJobView,
  PeopleListView,
  type RowActions,
} from "./MyPeopleViews";

type PanelTab = "all" | "job" | "move";

const JOB_PATH = /^\/jobs\/(\d+)/;
const CANDIDATE_PATH = /^\/candidates\/(\d+)/;

export function contextFromPath(pathname: string | null): {
  jobId: number | null;
  candidateId: number | null;
} {
  const job = pathname?.match(JOB_PATH);
  const cand = pathname?.match(CANDIDATE_PATH);
  return {
    jobId: job ? Number(job[1]) : null,
    candidateId: cand ? Number(cand[1]) : null,
  };
}

/** Escape zamyka panel — chyba że klawisz należy do otwartego okna albo menu. */
export function shouldCloseOnEscape(e: KeyboardEvent): boolean {
  if (e.key !== "Escape" || e.defaultPrevented) return false;
  if (typeof document === "undefined") return true;
  return !document.querySelector('[role="dialog"],[role="alertdialog"],[role="menu"]');
}

function WhereToMove({ candidateId }: { candidateId: number }) {
  const query = useQuery({
    queryKey: ["my-people", "move", candidateId],
    queryFn: () =>
      recommendationsApi
        .forCandidate(candidateId, { top_k: 3, include_breakdown: false })
        .then((r) => r.data),
    staleTime: 60_000,
  });
  if (query.isError) {
    return (
      <ErrorView
        message={apiErrorMessage(query.error, "Nie udało się wczytać propozycji rekrutacji.")}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!query.isSuccess) {
    return <p className="px-2 py-6 text-center text-sm text-muted-foreground">Szukam rekrutacji…</p>;
  }
  const matches = query.data.matches.filter((m) => m.job.status === "published");
  if (!matches.length) {
    return (
      <p className="px-2 py-6 text-center text-sm text-muted-foreground">
        Żadna opublikowana rekrutacja nie pasuje teraz do tej osoby.
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {matches.map((m) => (
        <li key={m.job.id} className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-muted/60">
          <MatchScoreBadge score={m.total_score} emptyLabel="Ocena niepełna" className="shrink-0" />
          <Link
            href={`/jobs/${m.job.id}`}
            className="min-w-0 flex-1 truncate text-sm font-medium text-foreground hover:underline"
          >
            {m.job.title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function MyPeoplePanel() {
  const open = useMyPeoplePanel((s) => s.open);
  const close = useMyPeoplePanel((s) => s.close);
  const pathname = usePathname();
  // Pasek „Podgląd jako” (h-9) przesuwa topbar w dół — panel startuje pod nim.
  const impersonating = useAuthStore((s) => !!s.realUser);
  const { jobId, candidateId } = contextFromPath(pathname);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const [tab, setTab] = useState<PanelTab>("all");
  const [query, setQuery] = useState("");
  const [addFor, setAddFor] = useState<{ candidate_id: number; full_name: string } | null>(null);
  const [busy, setBusy] = useState<Set<number>>(new Set());
  const buddyHidden = useUiStore((s) => s.hideMyPeopleBuddy);
  const setBuddyHidden = useUiStore((s) => s.setHideMyPeopleBuddy);

  // Otwarcie na stronie rekrutacji zaczyna od „Do tej rekrutacji" — po to
  // rekruter tam przyszedł (często z dzwonka `my_people_match`).
  useEffect(() => {
    if (!open) return;
    setTab(jobId != null ? "job" : "all");
  }, [open, jobId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (shouldCloseOnEscape(e)) close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  const people = useMyPeople(open);
  const summary = useMyPeopleSummary(open);
  const categories = useCompetenceCategories();
  const forJob = useMyPeopleForJob(jobId, open && tab === "job");

  // Obejrzenie zakładki rekrutacji zeruje jej dopasowania w liczniku awatara.
  const seenFor = useRef<number | null>(null);
  useEffect(() => {
    if (!open || tab !== "job" || jobId == null || !forJob.isSuccess) return;
    if (seenFor.current === jobId) return;
    seenFor.current = jobId;
    void myPeopleApi
      .markSeen(jobId)
      .then(() => queryClient.invalidateQueries({ queryKey: myPeopleSummaryQueryKey }))
      .catch(() => {
        seenFor.current = null;
      });
  }, [open, tab, jobId, forJob.isSuccess, queryClient]);

  const withBusy = async (id: number, fn: () => Promise<void>) => {
    setBusy((s) => new Set(s).add(id));
    try {
      await fn();
    } finally {
      setBusy((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  };

  const snooze = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: SnoozeReason }) =>
      withBusy(id, () => myPeopleApi.snooze(id, reason)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MY_PEOPLE_QUERY_PREFIX }),
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się uśpić osoby.")),
  });
  const unsnooze = useMutation({
    mutationFn: (id: number) => withBusy(id, () => myPeopleApi.unsnooze(id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MY_PEOPLE_QUERY_PREFIX }),
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się przywrócić osoby.")),
  });

  const addToThisJob = async (row: { candidate_id: number; full_name: string }) => {
    if (jobId == null || !forJob.data) return;
    const title = forJob.data.job_title;
    await withBusy(row.candidate_id, async () => {
      try {
        const response = await proposalsBulkApi.add(jobId, {
          candidate_ids: [row.candidate_id],
          source: "my_people",
        });
        showSuccess(addToRecruitmentSummary({ job: { id: jobId, title }, response }));
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
        void queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
        void queryClient.invalidateQueries({ queryKey: MY_PEOPLE_QUERY_PREFIX });
      } catch (err) {
        showError(
          isForbiddenError(err)
            ? "Nie należysz do zespołu tej rekrutacji."
            : apiErrorMessage(err, "Nie udało się dodać do rekrutacji."),
        );
      }
    });
  };

  const listActions: RowActions = {
    onAdd: (row) => setAddFor(row),
    onSnooze: (id, reason) => snooze.mutate({ id, reason }),
    onUnsnooze: (id) => unsnooze.mutate(id),
    busyIds: busy,
  };
  const jobActions: RowActions = { onAdd: (row) => void addToThisJob(row), busyIds: busy };

  const split = useMemo(() => {
    const rows = (people.data?.rows ?? []).filter((r) => matchesQuery(r, query));
    return splitPeople(rows);
  }, [people.data, query]);

  const isMine =
    candidateId != null &&
    (people.data?.rows ?? []).some((r) => r.candidate_id === candidateId && !r.snoozed);

  const tabs = [
    { value: "all", label: "Wszyscy", count: people.data?.active_count },
    ...(jobId != null ? [{ value: "job", label: "Do tej rekrutacji" }] : []),
    ...(isMine ? [{ value: "move", label: "Gdzie przepiąć" }] : []),
  ];
  const sentences = summarySentences(summary.data);

  if (!open) return null;

  return (
    <aside
      aria-label="Moi ludzie"
      className={cn(
        "fixed bottom-0 right-0 z-40 flex w-full max-w-[420px] flex-col border-l border-border bg-background shadow-xl pb-[env(safe-area-inset-bottom)]",
        impersonating ? "top-21" : "top-12",
      )}
    >
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Users className="h-4 w-4 text-primary" aria-hidden />
        <h2 className="flex-1 text-sm font-semibold text-foreground">Moi ludzie</h2>
        <Button variant="ghost" size="icon-sm" aria-label="Zamknij panel „Moi ludzie”" onClick={close}>
          <X className="h-4 w-4" aria-hidden />
        </Button>
      </header>

      {sentences.length ? (
        <div className="border-b border-border bg-primary/5 px-4 py-2 text-xs text-foreground">
          {sentences.map((s) => (
            <p key={s}>{s}</p>
          ))}
        </div>
      ) : null}

      <div className="px-3 pt-2">
        <TabbedNav
          tabs={tabs}
          value={tab}
          onValueChange={(v) => setTab(v as PanelTab)}
          ariaLabel="Widok listy"
          dense
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {tab === "all" ? (
          <>
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Szukaj po nazwisku, kliencie, mieście"
                aria-label="Szukaj na liście"
                className="pl-8"
              />
            </div>
            {people.isError ? (
              <ErrorView
                message={apiErrorMessage(people.error, "Nie udało się wczytać Twojej listy.")}
                onRetry={() => void people.refetch()}
              />
            ) : !people.isSuccess ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">Wczytuję listę…</p>
            ) : people.data.rows.length === 0 ? (
              <EmptyListView />
            ) : (
              <PeopleListView
                active={split.active}
                working={split.working}
                snoozed={split.snoozed}
                categories={categories.data ?? []}
                actions={listActions}
                truncated={people.data.truncated}
              />
            )}
          </>
        ) : null}

        {tab === "job" ? (
          forJob.isError ? (
            <ErrorView
              message={
                isForbiddenError(forJob.error)
                  ? "Brak dostępu do tej rekrutacji."
                  : apiErrorMessage(forJob.error, "Nie udało się policzyć dopasowania.")
              }
              onRetry={() => void forJob.refetch()}
            />
          ) : !forJob.isSuccess ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              Liczę, kto z Twoich ludzi tu pasuje…
            </p>
          ) : (
            <ForJobView data={forJob.data} actions={jobActions} />
          )
        ) : null}

        {tab === "move" && candidateId != null ? <WhereToMove candidateId={candidateId} /> : null}
      </div>

      <footer className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={!buddyHidden}
            onChange={(e) => setBuddyHidden(!e.target.checked)}
            className="h-3.5 w-3.5 accent-primary"
          />
          Pokazuj postać w rogu ekranu
        </label>
      </footer>

      {addFor ? (
        <AddToRecruitmentDialog
          open
          onOpenChange={(next) => {
            if (!next) setAddFor(null);
          }}
          candidateIds={[addFor.candidate_id]}
          source="my_people"
          subject={addFor.full_name}
          onAdded={(result) => {
            showSuccess(addToRecruitmentSummary(result));
            setAddFor(null);
            void queryClient.invalidateQueries({ queryKey: MY_PEOPLE_QUERY_PREFIX });
          }}
        />
      ) : null}
    </aside>
  );
}
