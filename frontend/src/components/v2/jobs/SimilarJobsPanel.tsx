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
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Search, Unlink } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { RecruitmentSheet } from "@/components/v2/recruitment/slideovers/RecruitmentSheet";
import { candidatesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import {
  similarJobsApi,
  similarJobsKey,
  similarPeopleKey,
  similarSearchKey,
  type ReassignResponse,
  type SentPerson,
  type SimilarJobItem,
  useReassignFromSimilar,
  useSimilarJobs,
  useUnlinkSimilarJob,
} from "@/lib/similar-jobs-api";
import {
  personStatusLine,
  planReassign,
  pluralJobs,
  pluralPeople,
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
  const qc = useQueryClient();
  const { showSuccess, showError, showActionToast } = useToast();
  const similar = useSimilarJobs(jobId, open);
  const unlink = useUnlinkSimilarJob(jobId);
  const reassign = useReassignFromSimilar(jobId);
  const [chosen, setChosen] = useState<number[]>([]);
  const [manual, setManual] = useState<SimilarJobItem[]>([]);
  const [excluded, setExcluded] = useState<Set<number>>(() => new Set());
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (open) return;
    setChosen([]);
    setManual([]);
    setExcluded(new Set());
    setQuery("");
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
      queryKey: similarPeopleKey(jobId, otherId),
      queryFn: () =>
        similarJobsApi
          .people(jobId, [otherId])
          .then((data) => data.jobs[0]?.people ?? []),
      staleTime: 30_000,
    })),
  });
  const peopleByJob: Record<number, SentPerson[] | undefined> = {};
  chosen.forEach((otherId, index) => {
    peopleByJob[otherId] = peopleQueries[index]?.data;
  });
  const loadingPeople = peopleQueries.some((query) => query.isLoading);
  const plan = planReassign(chosen, peopleByJob, excluded);
  const count = plan.candidateIds.length;

  const linked = useMemo(() => similar.data?.linked ?? [], [similar.data]);
  const linkedIds = useMemo(() => new Set(linked.map((j) => j.id)), [linked]);
  const suggestions = similar.data?.suggestions ?? [];
  const extra = manual.filter(
    (m) => !linkedIds.has(m.id) && !suggestions.some((s) => s.id === m.id),
  );
  const newLinks = chosen.filter((id) => !linkedIds.has(id));

  const toggleJob = (id: number) =>
    setChosen((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const togglePerson = (candidateId: number) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });

  const pickFromSearch = (item: SimilarJobItem) => {
    if (!manual.some((m) => m.id === item.id)) setManual((prev) => [...prev, item]);
    setChosen((prev) => (prev.includes(item.id) ? prev : [...prev, item.id]));
    setQuery("");
  };

  const undo = async (result: ReassignResponse) => {
    const removed = await Promise.allSettled(
      result.added.map((candidateId) => candidatesApi.removeFromRecruitment(candidateId, jobId)),
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
      const summary = summarizeBulkResult(result);
      const parts: string[] = [];
      parts.push(
        result.total_added > 0
          ? `Przepięto ${result.total_added} ${pluralPeople(result.total_added)} do Nowych.`
          : "Połączono rekrutacje.",
      );
      if (result.linked_now.length > 0 && result.total_added > 0) {
        parts.push(`Połączono ${result.linked_now.length} ${pluralJobs(result.linked_now.length)}.`);
      }
      if (summary.skipped.length > 0) {
        parts.push(`Pominięto: ${formatReasonCounts(summary.skipped)}.`);
      }
      const message = parts.join(" ");
      if (result.total_added > 0 || result.linked_now.length > 0) {
        showActionToast(message, { actionLabel: "Cofnij", onAction: () => undo(result) });
      } else {
        showSuccess(message);
      }
      onOpenChange(false);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przepiąć osób."));
    }
  };

  const summaryText =
    chosen.length === 0
      ? "Kliknij rekrutację — zaznaczymy wszystkich wysłanych w niej do klienta."
      : count > 0
        ? `${count === 1 ? "1 osoba" : `${count} ${pluralPeople(count)}`} z ${chosen.length} rekrutacji. Połączone rekrutacje przepną kolejne wysłane osoby same.`
        : "Nikogo nie zaznaczono — rekrutacje zostaną tylko połączone.";
  const submitLabel =
    count > 0 ? `Przepnij ${count} ${pluralPeople(count)} do Nowych` : "Tylko połącz";
  const submitDisabled =
    readOnly ||
    chosen.length === 0 ||
    loadingPeople ||
    reassign.isPending ||
    (count === 0 && newLinks.length === 0);

  const renderGroup = (item: SimilarJobItem) => (
    <JobGroup
      key={item.id}
      item={item}
      checked={chosen.includes(item.id)}
      onToggle={() => toggleJob(item.id)}
      rows={plan.rows[item.id]}
      loading={chosen.includes(item.id) && peopleByJob[item.id] === undefined}
      error={peopleQueries[chosen.indexOf(item.id)]?.isError ?? false}
      onRetry={() => qc.invalidateQueries({ queryKey: similarPeopleKey(jobId, item.id) })}
      onTogglePerson={togglePerson}
      onUnlink={item.linked && !readOnly ? () => unlink.mutate(item.id) : undefined}
      unlinking={unlink.isPending}
      readOnly={readOnly}
    />
  );

  const results = (search.data ?? []).filter((r) => r.id !== jobId);

  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Podobne rekrutacje"
      description="Kliknij rekrutację — zaznaczymy wszystkich wysłanych w niej do klienta. Jednym przyciskiem przepniesz ich do „Nowych”."
      data-testid="similar-jobs-panel"
      toolbar={
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
      }
      footer={
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground" data-testid="similar-panel-summary">
            {summaryText}
          </p>
          {readOnly ? (
            <p className="text-xs text-muted-foreground">Masz tu tylko podgląd — przepinać może zespół rekrutacji.</p>
          ) : (
            <Button onClick={submit} disabled={submitDisabled} data-testid="similar-panel-submit">
              {reassign.isPending ? "Przepinam…" : submitLabel}
            </Button>
          )}
        </div>
      }
    >
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
          ) : suggestions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              System nie znalazł podobnych rekrutacji. Wpisz rekrutację w polu wyżej.
            </p>
          ) : (
            suggestions.map(renderGroup)
          )}
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
    </RecruitmentSheet>
  );
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
  checked,
  onToggle,
  rows,
  loading,
  error,
  onRetry,
  onTogglePerson,
  onUnlink,
  unlinking,
  readOnly,
}: {
  item: SimilarJobItem;
  checked: boolean;
  onToggle: () => void;
  rows: PlannedPerson[] | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onTogglePerson: (candidateId: number) => void;
  onUnlink?: () => void;
  unlinking: boolean;
  readOnly: boolean;
}) {
  const people = rows?.map((r) => r.person);
  const pickable = selectableCount(people);
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
          <span className="text-xs font-semibold tabular-nums text-primary">{item.similarity}%</span>
        ) : null}
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          <b className="font-semibold text-foreground">{item.sent_count}</b> u klienta
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
            <ul aria-label={`Osoby wysłane do klienta: ${item.title}`}>
              {rows.map((row) => (
                <PersonRow key={row.person.candidate_id} row={row} onToggle={onTogglePerson} readOnly={readOnly} />
              ))}
              {pickable === 0 ? (
                <li className="px-3 py-2 text-xs text-muted-foreground">
                  Nikogo z tej rekrutacji nie da się przepiąć.
                </li>
              ) : null}
            </ul>
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
}: {
  row: PlannedPerson;
  onToggle: (candidateId: number) => void;
  readOnly: boolean;
}) {
  const { person, state } = row;
  const inputId = `similar-person-${person.candidate_id}-${state}`;
  const disabled = readOnly || state === "locked" || state === "duplicate";
  return (
    <li
      className={cn(
        "flex items-center gap-3 border-t border-border px-3 py-1.5 first:border-t-0",
        disabled && "opacity-60",
      )}
    >
      <Checkbox
        id={inputId}
        checked={state === "selected"}
        onCheckedChange={() => onToggle(person.candidate_id)}
        disabled={disabled}
        aria-label={`Przepnij ${person.name}`}
      />
      <label htmlFor={inputId} className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{person.name}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {state === "duplicate" ? "zaznaczona wyżej, w innej rekrutacji" : personStatusLine(person)}
        </span>
      </label>
      <span
        className={cn(
          "whitespace-nowrap rounded px-1.5 text-[11px] font-medium",
          CHIP[person.outcome] ?? "bg-muted text-muted-foreground",
        )}
      >
        {person.outcome === "hired" ? "pracuje u klienta" : person.already_in_job ? "już tutaj" : statusChip(person)}
      </span>
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
