"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowUpRight, Check, Trash2, UserCheck } from "lucide-react";

import {
  shortlistApi,
  type EvaluationStatus,
  type OutreachStatus,
  type ShortlistEntry,
} from "@/lib/candidate-search-api";
import { useToast } from "@/components/Toast";

/** Klucz zapytania współdzielony z licznikiem w pasku przełącznika — react-query
 *  deduplikuje, więc tablica i licznik czytają jeden fetch. */
export const jobShortlistQueryKey = (jobId: number) =>
  ["job-shortlist", jobId] as const;

// Etykiety PL — model nie ma jeszcze mapy w FE, więc definiujemy ją tu
// (te same wartości enum co w schemas/job_shortlist.py).
const EVALUATION_LABEL: Record<EvaluationStatus, string> = {
  do_oceny: "Do oceny",
  potencjalny: "Potencjalny",
  zatwierdzony: "Zatwierdzony",
  odrzucony: "Odrzucony",
};
const EVALUATION_ORDER: EvaluationStatus[] = [
  "do_oceny",
  "potencjalny",
  "zatwierdzony",
  "odrzucony",
];
const OUTREACH_LABEL: Record<OutreachStatus, string> = {
  nie_kontaktowano: "Nie kontaktowano",
  do_kontaktu: "Do kontaktu",
  kontakt_w_toku: "Kontakt w toku",
  zainteresowany: "Zainteresowany",
  brak_zainteresowania: "Brak zainteresowania",
};

// Ton segmentu oceny — kolor niesie znaczenie (zatwierdzony/odrzucony), reszta
// neutralna. Tokeny, nie hardcode.
function evalActiveClass(status: EvaluationStatus): string {
  if (status === "zatwierdzony") return "bg-success text-success-foreground";
  if (status === "odrzucony") return "bg-destructive text-destructive-foreground";
  if (status === "potencjalny") return "bg-info text-info-foreground";
  return "bg-primary text-primary-foreground";
}

function formatDatePl(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
}

function isPast(iso: string | null | undefined): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  return !Number.isNaN(d.getTime()) && d.getTime() < Date.now();
}

interface JobShortlistProps {
  jobId: number;
  readOnly?: boolean;
}

/**
 * Tablica shortlisty oferty — powierzchnia zarządzania wpisami z
 * `job_shortlist_entries` (ocena → kontakt → promocja do pipeline'u).
 *
 * Zapisy chroni blokada optymistyczna (`version`): równoległy zapis kończy się
 * 409, wtedy odświeżamy listę i prosimy o ponowienie, zamiast po cichu nadpisać
 * cudzą decyzję. Promocja przechodzi przez tę samą bramkę dopuszczalności co
 * ranking — jej 409 pokazujemy z powodem po polsku.
 */
export function JobShortlist({ jobId, readOnly = false }: JobShortlistProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: jobShortlistQueryKey(jobId),
    queryFn: () => shortlistApi.list(jobId),
    staleTime: 30_000,
  });

  const entries = data ?? [];

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: jobShortlistQueryKey(jobId) });

  const patchMutation = useMutation({
    mutationFn: (args: {
      entry: ShortlistEntry;
      patch: Partial<
        Pick<ShortlistEntry, "evaluation_status" | "outreach_status">
      >;
    }) =>
      shortlistApi.update(args.entry.id, {
        version: args.entry.version,
        ...args.patch,
      }),
    onSuccess: () => invalidate(),
    onError: (e: unknown) => {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        showError("Ktoś zapisał ten wpis równolegle — odświeżam, spróbuj ponownie.");
        void refetch();
      } else {
        showError("Nie udało się zapisać zmiany.");
      }
    },
  });

  const promoteMutation = useMutation({
    mutationFn: (entry: ShortlistEntry) => shortlistApi.promote(entry.id),
    onSuccess: (res, entry) => {
      const name = `${entry.candidate_name ?? ""} ${entry.candidate_lastname ?? ""}`.trim();
      showSuccess(
        res.already_in_pipeline || res.already_promoted
          ? `${name} jest już w pipeline`
          : `${name} — przeniesiono do pipeline`,
      );
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      invalidate();
    },
    onError: (e: unknown) => {
      // Bramka dopuszczalności zwraca 409 z powodem po polsku (detail).
      const detail = (e as { response?: { data?: { detail?: string } } })?.response
        ?.data?.detail;
      showError(detail || "Nie udało się przenieść do pipeline.");
    },
  });

  const removeMutation = useMutation({
    mutationFn: (entry: ShortlistEntry) => shortlistApi.remove(entry.id),
    onSuccess: () => invalidate(),
    onError: () => showError("Nie udało się usunąć wpisu."),
  });

  if (isLoading) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-3">
        <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <p className="text-sm">Wczytywanie shortlisty…</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
        <AlertCircle className="w-10 h-10 text-destructive" />
        <p className="text-sm">Nie udało się wczytać shortlisty</p>
        <button
          onClick={() => refetch()}
          className="text-sm text-primary hover:underline mt-1"
        >
          Spróbuj ponownie
        </button>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
        <UserCheck className="w-12 h-12 opacity-30" />
        <p className="text-sm">Shortlista jest pusta</p>
        <p className="text-xs text-muted-foreground">
          Dodaj kandydatów z zakładki „Ranking" przyciskiem „Na shortlistę".
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => {
        const fullName =
          `${entry.candidate_name ?? ""} ${entry.candidate_lastname ?? ""}`.trim() ||
          `Kandydat #${entry.candidate_id}`;
        // Zajętość PER WIERSZ, nie globalna: mutacje są współdzielone między
        // wpisami, więc zakres po `variables` — inaczej promocja wpisu A
        // zamrażałaby cały stół. (PR #1369 review.)
        const busy =
          (patchMutation.isPending &&
            patchMutation.variables?.entry.id === entry.id) ||
          (promoteMutation.isPending &&
            promoteMutation.variables?.id === entry.id) ||
          (removeMutation.isPending && removeMutation.variables?.id === entry.id);
        const due = formatDatePl(entry.next_action_at);
        const promoted = Boolean(entry.promoted_to_pipeline_at);

        return (
          <div
            key={entry.id}
            className="flex flex-col gap-3 rounded-xl border border-border bg-card dark:bg-muted p-3 sm:flex-row sm:items-center"
          >
            {/* Kandydat + snapshot */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-semibold text-foreground">
                  {fullName}
                </span>
                {entry.score_snapshot != null && (
                  <span
                    className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground"
                    title="Wynik dopasowania z chwili dodania"
                  >
                    {entry.score_snapshot}
                  </span>
                )}
              </div>
              {due && (
                <p
                  className={
                    "mt-0.5 text-[11px] " +
                    (isPast(entry.next_action_at)
                      ? "text-destructive font-medium"
                      : "text-warning-muted-foreground")
                  }
                >
                  {isPast(entry.next_action_at) ? "po terminie · " : "termin · "}
                  {due}
                </p>
              )}
            </div>

            {/* Ocena — segment 4 */}
            <div className="flex rounded-lg border border-border bg-muted/40 p-0.5">
              {EVALUATION_ORDER.map((status) => {
                const active = entry.evaluation_status === status;
                return (
                  <button
                    key={status}
                    type="button"
                    disabled={readOnly || busy || active}
                    onClick={() =>
                      patchMutation.mutate({ entry, patch: { evaluation_status: status } })
                    }
                    className={
                      "px-2 py-1 text-[11px] rounded-md whitespace-nowrap transition-colors disabled:cursor-default " +
                      (active
                        ? evalActiveClass(status)
                        : "text-muted-foreground hover:bg-accent")
                    }
                  >
                    {EVALUATION_LABEL[status]}
                  </button>
                );
              })}
            </div>

            {/* Kontakt — select 5 */}
            <select
              value={entry.outreach_status}
              disabled={readOnly || busy}
              onChange={(e) =>
                patchMutation.mutate({
                  entry,
                  patch: { outreach_status: e.target.value as OutreachStatus },
                })
              }
              className="h-8 rounded-lg border border-border bg-card px-2 text-xs text-foreground focus:outline-hidden focus:ring-2 focus:ring-primary disabled:opacity-50"
              aria-label={`Status kontaktu: ${fullName}`}
            >
              {(Object.keys(OUTREACH_LABEL) as OutreachStatus[]).map((s) => (
                <option key={s} value={s}>
                  {OUTREACH_LABEL[s]}
                </option>
              ))}
            </select>

            {/* Akcje */}
            {!readOnly && (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={busy || promoted}
                  onClick={() => promoteMutation.mutate(entry)}
                  title={promoted ? "Już w pipeline" : "Przenieś do pipeline"}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1.5 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-default transition-colors"
                >
                  {promoted ? (
                    <>
                      <Check className="w-3 h-3" /> W pipeline
                    </>
                  ) : (
                    <>
                      <ArrowUpRight className="w-3 h-3" /> Promuj
                    </>
                  )}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => removeMutation.mutate(entry)}
                  title="Usuń ze shortlisty"
                  className="inline-flex items-center justify-center rounded-lg border border-border p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
