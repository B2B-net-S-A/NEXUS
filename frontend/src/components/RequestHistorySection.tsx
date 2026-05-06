"use client";

/**
 * RequestHistorySection — zakładka "Historia" w widoku joba.
 *
 * Pokazuje siostrzane requesty tego samego klienta (i opcjonalnie cross-client)
 * w dwóch sekcjach: "W toku" + "Zamknięte". Każdy wiersz: tytuł + train +
 * seniority + similarity badge, meta-row z outcome / champion / TTH / fee /
 * owners / liczbą kandydatów. CTA: Otwórz, Skopiuj jako template, Dodaj
 * championa.
 *
 * Designed to be source-agnostic — działa zarówno gdy backend zwraca SQL
 * fast-path matches (similarity=1.0, źródło "sql_same_client") jak i Voyage
 * fallback z cosine.
 */

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  History,
  Clock3,
  CheckCircle2,
  XCircle,
  ArrowUpRight,
  Copy,
  UserPlus,
  Loader2,
  Train,
  AlertCircle,
} from "lucide-react";
import { requestHistoryApi } from "@/lib/api";
import type {
  RequestHistoryEntry,
  RequestHistoryResponse,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { AddJobModal } from "@/components/AppShell";

interface Props {
  jobId: number;
  clientId?: number | null;
}

const STATUS_LABEL_PL: Record<string, string> = {
  draft: "Szkic",
  published: "W toku",
  closed: "Zamknięty",
};

function statusLabel(s: string): string {
  return STATUS_LABEL_PL[s] ?? s;
}

function formatDateShort(iso: string | null): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString("pl-PL", {
      year: "numeric",
      month: "short",
    });
  } catch {
    return null;
  }
}

function formatFee(
  fee: number | null,
  currency: string | null,
  unit: string | null,
): string | null {
  if (fee === null) return null;
  const cur = currency ?? "PLN";
  const unitLabel =
    unit === "monthly"
      ? "/mc"
      : unit === "daily"
        ? "/dz"
        : unit === "hourly"
          ? "/h"
          : "";
  return `+${fee.toLocaleString("pl-PL")} ${cur}${unitLabel}`;
}

function similarityTone(pct: number): string {
  if (pct >= 95)
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
  if (pct >= 85)
    return "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300";
  if (pct >= 70)
    return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300";
  return "bg-muted text-foreground dark:bg-muted dark:text-muted-foreground";
}

export function RequestHistorySection({ jobId, clientId }: Props) {
  const [crossClient, setCrossClient] = useState(false);
  const [activeBucket, setActiveBucket] = useState<"in_progress" | "closed">(
    "closed",
  );
  const [templateJobId, setTemplateJobId] = useState<number | null>(null);
  const router = useRouter();
  const qc = useQueryClient();
  const { showToast } = useToast();

  const query = useQuery<RequestHistoryResponse>({
    queryKey: ["request-history", jobId, crossClient],
    queryFn: async () => {
      const r = await requestHistoryApi.forJob(jobId, {
        cross_client: crossClient,
        top_k: 15,
        include_open: true,
      });
      return r.data;
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    enabled: !!jobId,
  });

  const addCandidateMutation = useMutation({
    mutationFn: async (vars: {
      candidateId: number;
      sourceJobId: number;
    }) => {
      const r = await requestHistoryApi.addCandidate(jobId, {
        candidate_id: vars.candidateId,
        source_job_id: vars.sourceJobId,
      });
      return r.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kanban", jobId] });
      qc.invalidateQueries({ queryKey: ["job", jobId] });
      showToast("Dodano championa do pipeline", "success");
    },
    onError: (err: unknown) => {
      // Axios-style error narrowing
      const status =
        typeof err === "object" && err !== null && "response" in err
          ? (err as { response?: { status?: number } }).response?.status
          : undefined;
      if (status === 409) {
        showToast("Kandydat już jest w tym pipeline", "error");
      } else {
        showToast("Nie udało się dodać championa", "error");
      }
    },
  });

  const closed = query.data?.closed ?? [];
  const inProgress = query.data?.in_progress ?? [];
  const total = closed.length + inProgress.length;
  const meta = query.data?.meta;

  const visible = useMemo(
    () => (activeBucket === "closed" ? closed : inProgress),
    [activeBucket, closed, inProgress],
  );

  return (
    <section className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-semibold inline-flex items-center gap-2">
            <History className="w-5 h-5 text-amber-600" />
            Historia requestu
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Bliźniacze requesty tego klienta — outcome, champion, TTH, fee,
            owner.
            {meta && meta.voyage_count > 0 ? (
              <>
                {" "}
                <span className="text-amber-600">
                  +{meta.voyage_count} z innych ról
                </span>
              </>
            ) : null}
          </p>
        </div>
        <label className="text-xs text-muted-foreground dark:text-muted-foreground inline-flex items-center gap-1.5 cursor-pointer select-none whitespace-nowrap">
          <input
            type="checkbox"
            checked={crossClient}
            onChange={(e) => setCrossClient(e.target.checked)}
            className="accent-amber-600"
            data-testid="request-history-cross-client"
          />
          Wszyscy klienci
        </label>
      </div>

      {/* Bucket tabs */}
      <div className="flex gap-2 mb-4 border-b border-border dark:border-border">
        <button
          type="button"
          onClick={() => setActiveBucket("closed")}
          className={
            "px-3 py-1.5 text-sm font-medium border-b-2 transition-colors " +
            (activeBucket === "closed"
              ? "border-amber-600 text-amber-600"
              : "border-transparent text-muted-foreground hover:text-foreground")
          }
        >
          Zamknięte ({closed.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveBucket("in_progress")}
          className={
            "px-3 py-1.5 text-sm font-medium border-b-2 transition-colors " +
            (activeBucket === "in_progress"
              ? "border-amber-600 text-amber-600"
              : "border-transparent text-muted-foreground hover:text-foreground")
          }
        >
          W toku ({inProgress.length})
        </button>
      </div>

      {/* Content */}
      {query.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Szukam siostrzanych requestów…
        </div>
      )}
      {query.isError && (
        <div className="text-sm text-destructive dark:text-destructive inline-flex items-center gap-1.5">
          <AlertCircle className="w-4 h-4" />
          Nie udało się pobrać historii. Spróbuj ponownie.
        </div>
      )}
      {!query.isLoading && !query.isError && total === 0 && (
        <EmptyState
          crossClient={crossClient}
          onTryCrossClient={() => setCrossClient(true)}
        />
      )}
      {!query.isLoading && !query.isError && total > 0 && visible.length === 0 && (
        <p className="text-sm text-muted-foreground italic">
          {activeBucket === "closed"
            ? "Brak zamkniętych siostrzanych requestów."
            : "Brak siostrzanych requestów w toku."}
        </p>
      )}

      <ul className="space-y-2">
        {visible.map((entry) => (
          <RequestHistoryRow
            key={entry.job_id}
            entry={entry}
            onOpen={() =>
              window.open(`/jobs/${entry.job_id}`, "_blank", "noopener,noreferrer")
            }
            onCopyAsTemplate={() => setTemplateJobId(entry.job_id)}
            onAddChampion={
              entry.champion_candidate_id != null
                ? () =>
                    addCandidateMutation.mutate({
                      candidateId: entry.champion_candidate_id as number,
                      sourceJobId: entry.job_id,
                    })
                : undefined
            }
            isAddingChampion={addCandidateMutation.isPending}
          />
        ))}
      </ul>

      {/* Skopiuj jako template — modal rendered locally */}
      {templateJobId !== null && (
        <AddJobModal
          fromJobId={templateJobId}
          onClose={() => setTemplateJobId(null)}
          onSuccess={(msg) => {
            setTemplateJobId(null);
            showToast(msg, "success");
            qc.invalidateQueries({ queryKey: ["jobs"] });
          }}
        />
      )}
    </section>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

interface RowProps {
  entry: RequestHistoryEntry;
  onOpen: () => void;
  onCopyAsTemplate: () => void;
  onAddChampion?: () => void;
  isAddingChampion: boolean;
}

function RequestHistoryRow({
  entry,
  onOpen,
  onCopyAsTemplate,
  onAddChampion,
  isAddingChampion,
}: RowProps) {
  const simPct = Math.round(entry.similarity * 100);
  const simSourceLabel =
    entry.similarity_source === "sql_same_client"
      ? "Ten sam klient"
      : "Podobieństwo semantyczne";
  const fee = formatFee(entry.fee_rate, entry.fee_currency, entry.rate_unit);

  return (
    <li className="border border-border dark:border-border rounded-lg p-3 bg-card dark:bg-card space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-foreground dark:text-foreground truncate">
              {entry.title}
            </span>
            {entry.train_name && (
              <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
                <Train className="w-3 h-3" />
                {entry.train_name}
                {entry.same_train ? " ✓" : ""}
              </span>
            )}
            {entry.seniority && (
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {entry.seniority}
              </span>
            )}
            <span
              className={`text-xs font-semibold px-1.5 py-0.5 rounded ${similarityTone(simPct)}`}
              title={simSourceLabel}
            >
              {simPct}%
            </span>
          </div>
          <MetaRow entry={entry} fee={fee} />
        </div>
        <div className="flex flex-col gap-1.5 flex-shrink-0">
          <button
            type="button"
            onClick={onOpen}
            className="text-xs px-2 py-1 rounded bg-card dark:bg-muted border border-border dark:border-border hover:bg-muted inline-flex items-center gap-1"
          >
            <ArrowUpRight className="w-3 h-3" />
            Otwórz
          </button>
          <button
            type="button"
            onClick={onCopyAsTemplate}
            className="text-xs px-2 py-1 rounded bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 inline-flex items-center gap-1"
            title="Otwórz formularz nowego requestu z prefilled polami"
          >
            <Copy className="w-3 h-3" />
            Skopiuj jako template
          </button>
          <button
            type="button"
            onClick={onAddChampion}
            disabled={!onAddChampion || isAddingChampion}
            className="text-xs px-2 py-1 rounded bg-purple-50 hover:bg-purple-100 disabled:opacity-50 disabled:cursor-not-allowed text-purple-800 border border-purple-200 inline-flex items-center gap-1"
            title={
              onAddChampion
                ? "Dodaj championa tej roli do bieżącego pipeline'u"
                : "Brak championa w tej roli"
            }
          >
            {isAddingChampion ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <UserPlus className="w-3 h-3" />
            )}
            Dodaj championa
          </button>
        </div>
      </div>
    </li>
  );
}

function MetaRow({
  entry,
  fee,
}: {
  entry: RequestHistoryEntry;
  fee: string | null;
}) {
  const closedAt = formatDateShort(entry.closed_at);
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground dark:text-muted-foreground mt-1">
      <span
        className={
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded " +
          (entry.is_in_progress
            ? "bg-primary/10 text-primary dark:bg-primary/30 dark:text-primary"
            : "bg-muted text-foreground dark:bg-muted dark:text-muted-foreground")
        }
      >
        {statusLabel(entry.status)}
      </span>
      {entry.outcome === "filled" && (
        <span className="inline-flex items-center gap-1 text-green-700">
          <CheckCircle2 className="w-3 h-3" />
          Filled
        </span>
      )}
      {entry.outcome === "cancelled" && (
        <span className="inline-flex items-center gap-1 text-rose-700">
          <XCircle className="w-3 h-3" />
          {entry.close_reason ?? "Cancelled"}
        </span>
      )}
      {entry.champion_name && (
        <span title="Champion (kandydat zatrudniony)">
          🏆 {entry.champion_name}
          {entry.champions_count > 1 ? ` (+${entry.champions_count - 1})` : ""}
        </span>
      )}
      {entry.tth_days != null && (
        <span
          className="inline-flex items-center gap-1"
          title="Time-to-Hire (dni od otwarcia do zamknięcia)"
        >
          <Clock3 className="w-3 h-3" />
          {entry.tth_days}d
        </span>
      )}
      {fee && (
        <span title="Marża miesięczna z kontraktu" className="text-emerald-700">
          {fee}
        </span>
      )}
      {(entry.tac_name || entry.delivery_lead_name) && (
        <span className="text-muted-foreground" title="Owner roli">
          {entry.tac_name ? `TAC: ${entry.tac_name}` : ""}
          {entry.tac_name && entry.delivery_lead_name ? " · " : ""}
          {entry.delivery_lead_name ? `DL: ${entry.delivery_lead_name}` : ""}
        </span>
      )}
      {entry.candidates_count > 0 && (
        <span title="Liczba kandydatów w pipeline (wszystkie etapy)">
          {entry.candidates_count} kand.
        </span>
      )}
      {closedAt && !entry.is_in_progress && (
        <span title="Data zamknięcia" className="text-muted-foreground">
          zamknięty {closedAt}
        </span>
      )}
    </div>
  );
}

function EmptyState({
  crossClient,
  onTryCrossClient,
}: {
  crossClient: boolean;
  onTryCrossClient: () => void;
}) {
  return (
    <div className="text-sm text-muted-foreground dark:text-muted-foreground italic">
      {crossClient
        ? "Brak siostrzanych requestów w bazie."
        : "Brak historycznych requestów u tego klienta."}
      {!crossClient && (
        <>
          {" "}
          <button
            type="button"
            onClick={onTryCrossClient}
            className="underline text-amber-600 not-italic"
          >
            Spróbuj cross-client
          </button>
          .
        </>
      )}
    </div>
  );
}
