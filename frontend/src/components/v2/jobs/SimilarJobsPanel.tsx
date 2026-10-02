"use client";

/**
 * Panel „Podobne rekrutacje” na stronie rekrutacji (25.09.2026, makieta A:
 * https://claude.ai/artifact/PYZj4Qf2ga2KAYmwFkW3UZ).
 *
 * Zastępuje okno `SimilarJobsDialog` na stronie rekrutacji (lista rekrutacji
 * nadal używa okna). Różnica: pod rekrutacją widać osoby wysłane tam do
 * klienta, a jeden przycisk łączy rekrutacje i od razu dodaje zaznaczonych
 * do „Nowych” — bez „Do przejrzenia” i „Biorę” przy każdej osobie.
 *
 * Reguły zaznaczania żyją w `lib/similar-reassign.ts`: rekrutacja nigdy nie
 * jest zaznaczona sama, kliknięcie zaznacza jej wysłanych (także odrzuconych
 * przez klienta), zatrudnionych i obecnych w tej rekrutacji nie da się wybrać.
 *
 * Podgląd osoby (02.10.2026): klik w nazwisko otwiera kartę obok panelu
 * (`SimilarPersonPreview`), Ctrl/⌘-klik — profil w nowej karcie. Zaznaczenie
 * zmienia wyłącznie pole wyboru. Esc zamyka najpierw kartę, bo zamknięcie
 * panelu kasuje zaznaczenia.
 *
 * Od 02.10.2026 treść żyje w `useSimilarJobsTab` — ta sama lista jest zakładką
 * „Podobne rekrutacje” okna „Kandydaci do dodania”. Pod wysłanymi do klienta
 * stoją „pozostali” z tej samej rekrutacji (od Screeningu wzwyż): nie
 * zaznaczają się sami i wchodzą do „Nowych” zwykłym dodaniem, nie przepięciem.
 */

import { useEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Link2, Search, Unlink } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SimilarPersonPreview } from "@/components/v2/jobs/SimilarPersonPreview";
import { RecruitmentSheet } from "@/components/v2/recruitment/slideovers/RecruitmentSheet";
import { useCapability } from "@/hooks/useCapability";
import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { proposalsBulkApi, type BulkProposalsResponse } from "@/lib/candidate-search-api";
import {
  similarityHint,
  similarityLabel,
  similarJobsApi,
  similarJobsKey,
  similarPeopleWithRestKey,
  similarSearchKey,
  type ReassignResponse,
  type SentPerson,
  type SimilarJobItem,
  useReassignFromSimilar,
  useSimilarJobs,
  useUnlinkSimilarJob,
} from "@/lib/similar-jobs-api";
import {
  MAX_REASSIGN_PEOPLE,
  personStatusLine,
  planReassign,
  pluralJobs,
  pluralPeople,
  previewSequence,
  selectableCount,
  type PlannedPerson,
} from "@/lib/similar-reassign";
import { cn } from "@/lib/utils";

export interface SimilarJobsPanelProps {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  readOnly?: boolean;
}

export function SimilarJobsPanel({
  jobId,
  open,
  onOpenChange,
  readOnly = false,
}: SimilarJobsPanelProps) {
  const tab = useSimilarJobsTab(jobId, {
    enabled: open,
    readOnly,
    onDone: () => onOpenChange(false),
  });
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Podobne rekrutacje"
      description={SIMILAR_TAB_DESCRIPTION}
      data-testid="similar-jobs-panel"
      onEscapeKeyDown={tab.onEscapeKeyDown}
      sidePane={tab.sidePane}
      toolbar={tab.toolbar}
      footer={tab.footer}
    >
      {tab.body}
    </RecruitmentSheet>
  );
}

export const SIMILAR_TAB_DESCRIPTION =
  "Kliknij rekrutację — zaznaczymy wszystkich wysłanych w niej do klienta. Kliknij osobę, żeby ją podejrzeć. Jednym przyciskiem przepniesz zaznaczonych do „Nowych”.";

/** Części okna, które zakładka oddaje powłoce (`RecruitmentSheet`). */
export interface SourceTabSlots {
  toolbar: ReactNode;
  body: ReactNode;
  footer: ReactNode;
  sidePane: ReactElement | undefined;
  onEscapeKeyDown: (event: KeyboardEvent) => void;
}

interface SimilarPeople {
  people: SentPerson[];
  /** Ilu „pozostałych” ma rekrutacja naprawdę (lista jest ucinana). */
  restTotal: number;
}

export function useSimilarJobsTab(
  jobId: number,
  {
    enabled,
    readOnly = false,
    onDone,
  }: { enabled: boolean; readOnly?: boolean; onDone?: () => void },
): SourceTabSlots {
  const open = enabled;
  const qc = useQueryClient();
  const { showSuccess, showError, showActionToast } = useToast();
  const similar = useSimilarJobs(jobId, open);
  const unlink = useUnlinkSimilarJob(jobId);
  const reassign = useReassignFromSimilar(jobId);
  const [chosen, setChosen] = useState<number[]>([]);
  const [manual, setManual] = useState<SimilarJobItem[]>([]);
  const [excluded, setExcluded] = useState<Set<number>>(() => new Set());
  // „Pozostali” (klient ich nie widział) — nikt nie jest zaznaczony sam.
  const [included, setIncluded] = useState<Set<number>>(() => new Set());
  const [addingRest, setAddingRest] = useState(false);
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<{ candidateId: number; jobId: number } | null>(null);
  const previewTrigger = useRef<HTMLElement | null>(null);
  const canOpenProfile = useCapability("nav.candidates");

  useEffect(() => {
    if (open) return;
    setChosen([]);
    setManual([]);
    setExcluded(new Set());
    setIncluded(new Set());
    setQuery("");
    setPreview(null);
  }, [open]);

  const q = query.trim();
  const search = useQuery({
    queryKey: similarSearchKey(jobId, q),
    queryFn: () => similarJobsApi.search(jobId, q),
    enabled: open && q.length >= 2,
    staleTime: 30_000,
  });

  const peopleQueries = useQueries({
    queries: chosen.map((otherId) => ({
      queryKey: similarPeopleWithRestKey(jobId, otherId),
      queryFn: (): Promise<SimilarPeople> =>
        similarJobsApi.people(jobId, [otherId], { includeRest: true }).then((data) => ({
          people: data.jobs[0]?.people ?? [],
          restTotal: data.jobs[0]?.rest_total ?? 0,
        })),
      staleTime: 30_000,
    })),
  });
  const peopleByJob: Record<number, SentPerson[] | undefined> = {};
  const restTotalByJob: Record<number, number> = {};
  chosen.forEach((otherId, index) => {
    peopleByJob[otherId] = peopleQueries[index]?.data?.people;
    restTotalByJob[otherId] = peopleQueries[index]?.data?.restTotal ?? 0;
  });
  // Przepinamy dopiero, gdy znamy ludzi KAŻDEJ zaznaczonej rekrutacji —
  // grupa w błędzie albo w toku wypadłaby z planu po cichu.
  const peopleNotReady = peopleQueries.some((query) => query.data === undefined);
  const peopleFailed = peopleQueries.some(
    (query) => query.isError && query.data === undefined,
  );
  const plan = planReassign(chosen, peopleByJob, excluded, included);
  const count = plan.candidateIds.length + plan.restIds.length;

  const linked = useMemo(() => similar.data?.linked ?? [], [similar.data]);
  const linkedIds = useMemo(() => new Set(linked.map((j) => j.id)), [linked]);
  const suggestions = similar.data?.suggestions ?? [];
  const extra = manual.filter(
    (m) => !linkedIds.has(m.id) && !suggestions.some((s) => s.id === m.id),
  );
  const newLinks = chosen.filter((id) => !linkedIds.has(id));

  const toggleJob = (id: number) => {
    // Odznaczona rekrutacja chowa swoje osoby — karta jednej z nich też znika.
    if (preview?.jobId === id) setPreview(null);
    setChosen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const openPreview = (otherId: number, candidateId: number, trigger: HTMLElement) => {
    previewTrigger.current = trigger;
    setPreview({ candidateId, jobId: otherId });
  };

  const closePreview = () => {
    setPreview(null);
    const trigger = previewTrigger.current;
    if (trigger?.isConnected) trigger.focus();
  };

  const togglePerson = (person: SentPerson) => {
    const flip = (prev: Set<number>) => {
      const next = new Set(prev);
      if (next.has(person.candidate_id)) next.delete(person.candidate_id);
      else next.add(person.candidate_id);
      return next;
    };
    if (person.sent === false) setIncluded(flip);
    else setExcluded(flip);
  };

  const pickFromSearch = (item: SimilarJobItem) => {
    if (!manual.some((m) => m.id === item.id)) setManual((prev) => [...prev, item]);
    setChosen((prev) => (prev.includes(item.id) ? prev : [...prev, item.id]));
    setQuery("");
  };

  const undo = async (result: ReassignResponse, rest: BulkProposalsResponse | null) => {
    const removed = await Promise.allSettled(
      [...result.added, ...(rest?.added ?? [])].map((candidateId) =>
        candidatesApi.removeFromRecruitment(candidateId, jobId),
      ),
    );
    await Promise.allSettled(result.linked_now.map((otherId) => similarJobsApi.unlink(jobId, otherId)));
    qc.invalidateQueries({ queryKey: similarJobsKey(jobId) });
    qc.invalidateQueries({ queryKey: ["similar-people", jobId] });
    qc.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    qc.invalidateQueries({ queryKey: ["kanban", jobId] });
    qc.invalidateQueries({ queryKey: ["job-proposals"] });
    const failed = removed.filter((r) => r.status === "rejected").length;
    if (failed > 0) {
      showError(
        `Nie cofnięto przepięcia dla ${failed === 1 ? "1 osoby" : `${failed} osób`}. Usuń ${failed === 1 ? "ją" : "je"} ręcznie z tablicy.`,
      );
    } else {
      showSuccess("Cofnięto przepięcie.");
    }
  };

  const submit = async () => {
    if (chosen.length === 0) return;
    try {
      const result = await reassign.mutateAsync({
        jobIds: chosen,
        candidateIds: plan.candidateIds,
      });
      // „Pozostali” nie byli u klienta — zwykłe dodanie do „Nowych”, już po
      // połączeniu rekrutacji. Błąd tutaj nie cofa udanego przepięcia.
      let rest: BulkProposalsResponse | null = null;
      let restFailed = false;
      if (plan.restIds.length > 0) {
        setAddingRest(true);
        try {
          rest = await proposalsBulkApi.add(jobId, {
            candidate_ids: plan.restIds,
            initial_stage_legacy: "new",
            source: "historical",
          });
        } catch {
          restFailed = true;
        } finally {
          setAddingRest(false);
        }
      }
      const summary = summarizeBulkResult(result);
      const restSummary = rest ? summarizeBulkResult(rest) : null;
      const restAdded = rest?.total_added ?? 0;
      const parts: string[] = [];
      parts.push(
        result.total_added > 0
          ? `Przepięto ${result.total_added} ${pluralPeople(result.total_added)} do Nowych.`
          : restAdded > 0
            ? `Dodano ${restAdded} ${pluralPeople(restAdded)} do Nowych.`
            : "Połączono rekrutacje.",
      );
      if (result.total_added > 0 && restAdded > 0) {
        parts.push(`Dodano też ${restAdded} ${pluralPeople(restAdded)} spoza wysłanych do klienta.`);
      }
      if (result.linked_now.length > 0 && result.total_added + restAdded > 0) {
        parts.push(`Połączono ${result.linked_now.length} ${pluralJobs(result.linked_now.length)}.`);
      }
      const skipped = [...summary.skipped, ...(restSummary?.skipped ?? [])];
      if (skipped.length > 0) {
        parts.push(`Pominięto: ${formatReasonCounts(skipped)}.`);
      }
      if (restFailed) {
        parts.push("Nie udało się dodać osób spoza wysłanych do klienta — spróbuj ponownie.");
      }
      const message = parts.join(" ");
      if (result.total_added + restAdded > 0 || result.linked_now.length > 0) {
        showActionToast(message, { actionLabel: "Cofnij", onAction: () => undo(result, rest) });
      } else {
        showSuccess(message);
      }
      onDone?.();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przepiąć osób."));
    }
  };

  const tooMany =
    plan.candidateIds.length > MAX_REASSIGN_PEOPLE || plan.restIds.length > MAX_REASSIGN_PEOPLE;
  const summaryText = peopleFailed
    ? "Nie wczytano osób z jednej z zaznaczonych rekrutacji — kliknij „Ponów” przy niej albo ją odznacz."
    : tooMany
      ? `Naraz da się przepiąć najwyżej ${MAX_REASSIGN_PEOPLE} osób — zaznaczonych jest ${count}. Odznacz część albo przepnij rekrutacje po kolei.`
      : chosen.length === 0
      ? "Kliknij rekrutację — zaznaczymy wszystkich wysłanych w niej do klienta."
      : count > 0
        ? `${count === 1 ? "1 osoba" : `${count} ${pluralPeople(count)}`} z ${chosen.length} rekrutacji. Połączone rekrutacje przepną kolejne wysłane osoby same.`
        : "Nikogo nie zaznaczono — rekrutacje zostaną tylko połączone.";
  const submitLabel =
    count === 0
      ? "Tylko połącz"
      : plan.restIds.length > 0
        ? `Dodaj ${count} ${pluralPeople(count)} do Nowych`
        : `Przepnij ${count} ${pluralPeople(count)} do Nowych`;
  const busy = reassign.isPending || addingRest;
  const submitDisabled =
    readOnly ||
    chosen.length === 0 ||
    peopleNotReady ||
    tooMany ||
    busy ||
    (count === 0 && newLinks.length === 0);

  // Kolejność ‹ › w karcie = kolejność grup na ekranie, nie kolejność kliknięć.
  const shownJobs = [...extra, ...suggestions, ...linked];
  const sequence = previewSequence(
    [...new Set(shownJobs.map((j) => j.id))].filter((id) => chosen.includes(id)),
    plan.rows,
  );
  const previewIndex = preview
    ? sequence.findIndex((entry) => entry.person.candidate_id === preview.candidateId)
    : -1;
  const previewEntry = previewIndex >= 0 ? sequence[previewIndex] : null;
  // Osoba kliknięta w drugiej z dwóch rekrutacji pokazuje TĘ rekrutację.
  const previewRow =
    preview && previewEntry
      ? plan.rows[preview.jobId]?.find((r) => r.person.candidate_id === preview.candidateId)
      : undefined;
  const previewPerson = previewRow?.person ?? previewEntry?.person ?? null;
  const previewJobId = previewRow && preview ? preview.jobId : previewEntry?.jobId;
  const stepPreview = (delta: number) => {
    const next = sequence[previewIndex + delta];
    if (next) setPreview({ candidateId: next.person.candidate_id, jobId: next.jobId });
  };

  const renderGroup = (item: SimilarJobItem) => (
    <JobGroup
      key={item.id}
      item={item}
      jobId={jobId}
      previewCandidateId={previewPerson && previewJobId === item.id ? previewPerson.candidate_id : null}
      onPreview={(candidateId, trigger) => openPreview(item.id, candidateId, trigger)}
      onClosePreview={closePreview}
      canOpenProfile={canOpenProfile}
      checked={chosen.includes(item.id)}
      onToggle={() => toggleJob(item.id)}
      rows={plan.rows[item.id]}
      restTotal={restTotalByJob[item.id] ?? 0}
      loading={
        chosen.includes(item.id) &&
        peopleByJob[item.id] === undefined &&
        !peopleQueries[chosen.indexOf(item.id)]?.isError
      }
      error={
        chosen.includes(item.id) &&
        peopleByJob[item.id] === undefined &&
        Boolean(peopleQueries[chosen.indexOf(item.id)]?.isError)
      }
      onRetry={() => qc.refetchQueries({ queryKey: similarPeopleWithRestKey(jobId, item.id) })}
      onTogglePerson={togglePerson}
      onUnlink={item.linked && !readOnly ? () => unlink.mutate(item.id) : undefined}
      unlinking={unlink.isPending}
      readOnly={readOnly}
    />
  );

  const results = (search.data ?? []).filter((r) => r.id !== jobId);

  const sidePane =
    previewPerson ? (
          <SimilarPersonPreview
            key={previewPerson.candidate_id}
            jobId={jobId}
            person={previewPerson}
            sourceJob={shownJobs.find((j) => j.id === previewJobId) ?? null}
            position={{ index: previewIndex, total: sequence.length }}
            onPrev={() => stepPreview(-1)}
            onNext={() => stepPreview(1)}
            onClose={closePreview}
            canOpenProfile={canOpenProfile}
            selection={{
              checked:
                plan.candidateIds.includes(previewPerson.candidate_id) ||
                plan.restIds.includes(previewPerson.candidate_id),
              disabled: readOnly || !previewPerson.selectable,
              onToggle: () => togglePerson(previewPerson),
            }}
          />
        ) : undefined;
  const toolbar = (
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id="similar-jobs-panel-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Wpisz inną rekrutację: tytuł, klient, numer…"
            aria-label="Szukaj rekrutacji do przepięcia"
            className="pl-9"
          />
          {q.length >= 2 ? (
            <ul
              className="mt-1 max-h-64 overflow-y-auto rounded-lg border border-border bg-card shadow-sm"
              aria-label="Wyniki wyszukiwania rekrutacji"
            >
              {search.isLoading ? (
                <li className="px-3 py-2 text-sm text-muted-foreground">Szukam…</li>
              ) : search.isError ? (
                <li className="px-3 py-2 text-sm text-destructive">
                  Nie udało się wyszukać.{" "}
                  <button type="button" className="underline" onClick={() => search.refetch()}>
                    Ponów
                  </button>
                </li>
              ) : results.length === 0 ? (
                <li className="px-3 py-2 text-sm text-muted-foreground">Brak rekrutacji o takiej nazwie.</li>
              ) : (
                results.map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      onClick={() => pickFromSearch(row)}
                      className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted"
                    >
                      <JobLabel item={row} />
                      <span className="ml-auto whitespace-nowrap text-xs text-muted-foreground">
                        {row.sent_count} {row.sent_count === 1 ? "wysłana" : "wysłanych"}
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          ) : null}
        </div>
  );
  const footer = (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground" data-testid="similar-panel-summary">
            {summaryText}
          </p>
          {readOnly ? (
            <p className="text-xs text-muted-foreground">Masz tu tylko podgląd — przepinać może zespół rekrutacji.</p>
          ) : (
            <Button onClick={submit} disabled={submitDisabled} data-testid="similar-panel-submit">
              {busy ? "Przepinam…" : submitLabel}
            </Button>
          )}
        </div>
  );
  const body = (
      <div className="space-y-5">
        {similar.isError ? (
          <p className="text-sm text-destructive">
            Nie udało się wczytać podobnych rekrutacji.{" "}
            <button type="button" className="font-medium underline" onClick={() => similar.refetch()}>
              Ponów
            </button>
          </p>
        ) : null}

        {extra.length > 0 ? (
          <GroupSection title="Dodane z wyszukiwarki">{extra.map(renderGroup)}</GroupSection>
        ) : null}

        <GroupSection title="Podpowiedzi systemu">
          {similar.isLoading ? (
            <p className="text-sm text-muted-foreground">Szukam podobnych rekrutacji…</p>
          ) : suggestions.length > 0 ? (
            suggestions.map(renderGroup)
          ) : similar.isSuccess ? (
            // Runda 8 (R8-N14-4): „nie znalazł” tylko po udanym odczycie —
            // przy awarii komunikat błędu stoi wyżej.
            <p className="text-sm text-muted-foreground">
              System nie znalazł podobnych rekrutacji. Wpisz rekrutację w polu wyżej.
            </p>
          ) : null}
        </GroupSection>

        {linked.length > 0 ? (
          <GroupSection
            title={`Połączone · przepięto ${similar.data?.reassigned_count ?? 0}`}
            hint="Kolejne osoby wysłane w nich do klienta przepinają się same. Kliknij, żeby przepiąć tych, którzy jeszcze czekają."
          >
            {linked.map(renderGroup)}
          </GroupSection>
        ) : null}
      </div>
  );
  return {
    toolbar,
    body,
    footer,
    sidePane,
    onEscapeKeyDown: (event) => {
      if (!previewPerson) return;
      event.preventDefault();
      closePreview();
    },
  };
}

function GroupSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function JobGroup({
  item,
  jobId,
  previewCandidateId,
  onPreview,
  onClosePreview,
  canOpenProfile,
  checked,
  onToggle,
  rows,
  restTotal,
  loading,
  error,
  onRetry,
  onTogglePerson,
  onUnlink,
  unlinking,
  readOnly,
}: {
  item: SimilarJobItem;
  /** Rekrutacja docelowa — do linku profilu (`?from=job&jobId=`). */
  jobId: number;
  previewCandidateId: number | null;
  onPreview: (candidateId: number, trigger: HTMLElement) => void;
  onClosePreview: () => void;
  canOpenProfile: boolean;
  checked: boolean;
  onToggle: () => void;
  rows: PlannedPerson[] | undefined;
  /** Ilu „pozostałych” ma ta rekrutacja (serwer oddaje najwyżej 50). */
  restTotal: number;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onTogglePerson: (person: SentPerson) => void;
  onUnlink?: () => void;
  unlinking: boolean;
  readOnly: boolean;
}) {
  const sentRows = rows?.filter((r) => r.person.sent !== false) ?? [];
  const restRows = rows?.filter((r) => r.person.sent === false) ?? [];
  const pickable = selectableCount(sentRows.map((r) => r.person));
  const personRow = (row: PlannedPerson) => (
    <PersonRow
      key={row.person.candidate_id}
      row={row}
      onToggle={onTogglePerson}
      readOnly={readOnly}
      profileHref={
        canOpenProfile ? `/candidates/${row.person.candidate_id}?from=job&jobId=${jobId}` : null
      }
      active={previewCandidateId === row.person.candidate_id}
      onPreview={onPreview}
      onClosePreview={onClosePreview}
    />
  );
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border",
        checked ? "border-primary/50" : "border-border",
      )}
      data-testid={`similar-group-${item.id}`}
    >
      <div className={cn("flex items-center gap-3 px-3 py-2", checked ? "bg-primary/5" : "bg-muted/40")}>
        <Checkbox
          id={`similar-job-${item.id}`}
          checked={checked}
          onCheckedChange={onToggle}
          disabled={readOnly}
          aria-label={`Przepnij z: ${item.title}`}
        />
        <label htmlFor={`similar-job-${item.id}`} className="min-w-0 flex-1 cursor-pointer">
          <JobLabel item={item} />
        </label>
        {item.linked ? <Link2 className="h-4 w-4 shrink-0 text-primary" aria-label="połączona" /> : null}
        {item.similarity != null ? (
          <span
            className="whitespace-nowrap text-xs font-semibold tabular-nums text-primary"
            title={similarityHint(item)}
          >
            {similarityLabel(item)}
          </span>
        ) : null}
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          <b className="font-semibold text-foreground">{item.sent_count}</b> u klienta
          {item.other_count ? ` · +${item.other_count}` : null}
        </span>
        {onUnlink ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onUnlink}
            disabled={unlinking}
            aria-label={`Rozłącz: ${item.title}`}
          >
            <Unlink className="h-3.5 w-3.5" />
          </Button>
        ) : null}
      </div>
      {checked ? (
        <div className="border-t border-border">
          {loading ? (
            <p className="px-3 py-2 text-xs text-muted-foreground" role="status">
              Wczytuję osoby wysłane do klienta…
            </p>
          ) : error ? (
            <p className="px-3 py-2 text-xs text-destructive">
              Nie wczytano osób.{" "}
              <button type="button" className="underline" onClick={onRetry}>
                Ponów
              </button>
            </p>
          ) : !rows || rows.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Nikt nie został tu wysłany do klienta — nie ma kogo przepiąć.
            </p>
          ) : (
            <>
              {sentRows.length > 0 ? (
                <ul aria-label={`Osoby wysłane do klienta: ${item.title}`}>
                  {sentRows.map(personRow)}
                  {pickable === 0 ? (
                    <li className="px-3 py-2 text-xs text-muted-foreground">
                      Nikogo z tej rekrutacji nie da się przepiąć.
                    </li>
                  ) : null}
                </ul>
              ) : (
                <p className="px-3 py-2 text-xs text-muted-foreground">
                  Nikt nie został tu wysłany do klienta.
                </p>
              )}
              {restRows.length > 0 ? (
                <>
                  <p className="border-t border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
                    <b className="font-semibold text-foreground">Pozostali z tej rekrutacji</b> —
                    klient ich nie widział. Zaznacz, kogo chcesz dodać.
                    {restTotal > restRows.length
                      ? ` Pokazano ${restRows.length} z ${restTotal}.`
                      : null}
                  </p>
                  <ul aria-label={`Pozostali z rekrutacji: ${item.title}`}>
                    {restRows.map(personRow)}
                  </ul>
                </>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

const CHIP: Record<string, string> = {
  in_progress: "bg-success/10 text-success",
  rejected_by_client: "bg-destructive/10 text-destructive",
  rejected: "bg-muted text-muted-foreground",
  withdrawn: "bg-muted text-muted-foreground",
  hired: "bg-muted text-muted-foreground",
};

function PersonRow({
  row,
  onToggle,
  readOnly,
  profileHref,
  active,
  onPreview,
  onClosePreview,
}: {
  row: PlannedPerson;
  onToggle: (person: SentPerson) => void;
  readOnly: boolean;
  /** `null` = rola bez dostępu do profili kandydatów. */
  profileHref: string | null;
  active: boolean;
  onPreview: (candidateId: number, trigger: HTMLElement) => void;
  onClosePreview: () => void;
}) {
  const { person, state } = row;
  const inputId = `similar-person-${person.candidate_id}-${state}`;
  const disabled = readOnly || state === "locked" || state === "duplicate";
  const nameClass = cn(
    "block max-w-full truncate text-left text-sm font-medium hover:text-primary hover:underline",
    active && "text-primary",
  );
  return (
    <li
      className={cn(
        "flex items-center gap-3 border-t border-border px-3 py-1.5 first:border-t-0",
        active && "bg-primary/10",
      )}
    >
      <Checkbox
        id={inputId}
        checked={state === "selected"}
        onCheckedChange={() => onToggle(person)}
        disabled={disabled}
        aria-label={`${person.sent === false ? "Dodaj" : "Przepnij"} ${person.name}`}
      />
      <div className={cn("min-w-0 flex-1", disabled && !active && "opacity-60")}>
        {profileHref ? (
          // Zwykły klik = podgląd obok; Ctrl/⌘/Shift-klik i środkowy przycisk
          // zostają przy linku (profil w nowej karcie) — jak nazwisko na Tablicy.
          <a
            href={profileHref}
            target="_blank"
            rel="noopener"
            className={nameClass}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              onPreview(person.candidate_id, event.currentTarget);
            }}
          >
            {person.name}
          </a>
        ) : (
          <button
            type="button"
            className={nameClass}
            onClick={(event) => onPreview(person.candidate_id, event.currentTarget)}
          >
            {person.name}
          </button>
        )}
        <span className="block truncate text-xs text-muted-foreground">
          {state === "duplicate" ? "zaznaczona wyżej, w innej rekrutacji" : personStatusLine(person)}
        </span>
      </div>
      <span
        className={cn(
          "whitespace-nowrap rounded px-1.5 text-[11px] font-medium",
          CHIP[person.outcome] ?? "bg-muted text-muted-foreground",
        )}
      >
        {person.outcome === "hired"
          ? "pracuje u klienta"
          : person.already_in_job
            ? "już tutaj"
            : person.sent === false
              ? "nie u klienta"
              : statusChip(person)}
      </span>
      <button
        type="button"
        aria-label={`Podgląd: ${person.name}`}
        aria-pressed={active}
        onClick={(event) =>
          active ? onClosePreview() : onPreview(person.candidate_id, event.currentTarget)
        }
        className={cn(
          "hit-area rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground",
          active && "text-primary",
        )}
      >
        {active ? (
          <ChevronLeft className="h-4 w-4" aria-hidden />
        ) : (
          <ChevronRight className="h-4 w-4" aria-hidden />
        )}
      </button>
    </li>
  );
}

function statusChip(person: SentPerson): string {
  switch (person.outcome) {
    case "in_progress":
      return "u klienta";
    case "rejected_by_client":
      return "klient odrzucił";
    case "withdrawn":
      return "zrezygnował";
    default:
      return "zakończony";
  }
}

function JobLabel({ item }: { item: SimilarJobItem }) {
  return (
    <span className="block min-w-0">
      <span className="block truncate text-sm font-medium">{item.title}</span>
      <span className="block truncate text-xs text-muted-foreground">
        {[item.client_name, item.reference_number, item.status === "closed" ? "zamknięta" : null]
          .filter(Boolean)
          .join(" · ")}
      </span>
    </span>
  );
}
