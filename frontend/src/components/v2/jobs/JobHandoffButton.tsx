"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Send, AlertTriangle, CheckCircle2 } from "lucide-react";

import { api, jobsApi } from "@/lib/api";

interface RecruiterOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

interface JobHandoffButtonProps {
  jobId: number;
}

interface JobReadiness {
  job_id: number;
  ready: boolean;
  blockers: string[];
  closed: boolean;
  already_handed_off: boolean;
}

/**
 * DL "Przekaż do searchu" — assign a recruiter and start the (Champion-aware)
 * ranking. Replaces the create-time auto-ranking (P0-A): the recruiter never
 * lands on a stale pre-Champion snapshot. A 422 lists readiness blockers
 * (Champion required) instead of firing the ranking.
 */
export function JobHandoffButton({ jobId }: JobHandoffButtonProps) {
  const [open, setOpen] = useState(false);
  const [recruiterId, setRecruiterId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [blockers, setBlockers] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // Braki pokazujemy ZANIM ktoś kliknie. Na próbce 100 rekrutacji z produkcji
  // bramkę przechodzą 23, więc trzy na cztery kliknięcia kończyły się 422
  // z listą, którą dało się pokazać od razu. Odczyt, nic nie mutuje.
  const readinessQuery = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () =>
      api
        .get(`/api/jobs/${jobId}/readiness`)
        .then((r) => r.data as JobReadiness),
    staleTime: 30_000,
  });
  const readiness = readinessQuery.data;
  // `isSuccess`, nie `!isLoading`: w przerwie między ponowieniami react-query
  // ma `isLoading === false` i puste `data`, a wtedy „brak braków" znaczyłoby
  // „gotowa", zanim cokolwiek jest wiadomo.
  const knownBlockers =
    readinessQuery.isSuccess && readiness ? readiness.blockers : [];

  const recruitersQuery = useQuery({
    queryKey: ["handoff-recruiters"],
    enabled: open,
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["recruiter", "tac", "sourcer"] },
          // FastAPI binds repeated `roles=`; axios 1.x defaults to `roles[]=`,
          // which the backend ignores → it falls back to ALL roles (incl.
          // admin/DL). `indexes: null` emits the repeated form (P1-05a).
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as RecruiterOption[]),
  });

  const submit = async () => {
    if (!recruiterId) return;
    setSubmitting(true);
    setBlockers([]);
    setError(null);
    try {
      await jobsApi.handoff(jobId, recruiterId);
      setDone(true);
    } catch (e: unknown) {
      const resp = (
        e as { response?: { status?: number; data?: { detail?: unknown } } }
      ).response;
      const detail = resp?.data?.detail;
      if (
        resp?.status === 422 &&
        detail &&
        typeof detail === "object" &&
        "blockers" in detail
      ) {
        setBlockers((detail as { blockers?: string[] }).blockers ?? []);
      } else {
        setError(
          typeof detail === "string"
            ? detail
            : "Nie udało się przekazać do searchu.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div
        data-testid="handoff-done"
        className="mt-4 flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground"
      >
        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        Przekazano do searchu — ranking się generuje. Rekruter dostał dostęp do
        rekrutacji.
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Przekaż do searchu
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Przypisz rekrutera i uruchom dopasowywanie na podstawie Profilu
            Championa.
          </p>
        </div>
        {!open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            disabled={knownBlockers.length > 0 || readiness?.closed === true}
            data-testid="handoff-open"
            className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Przekaż do searchu
          </button>
        )}
      </div>

      {readiness?.closed && (
        <p
          data-testid="handoff-closed"
          className="mt-3 text-xs text-muted-foreground"
        >
          Rekrutacja jest zamknięta — nie przekazuje się jej do searchu.
        </p>
      )}

      {!readiness?.closed && knownBlockers.length > 0 && (
        <div
          data-testid="handoff-readiness-blockers"
          className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2"
        >
          <div className="flex items-center gap-1.5 text-xs font-medium text-amber-700 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            Zanim przekażesz do searchu, uzupełnij:
          </div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-amber-700 dark:text-amber-300">
            {knownBlockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {open && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={recruiterId ?? ""}
              onChange={(e) =>
                setRecruiterId(e.target.value ? Number(e.target.value) : null)
              }
              data-testid="handoff-recruiter-select"
              className="min-w-56 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
            >
              <option value="">— wybierz rekrutera —</option>
              {recruitersQuery.data?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name?.trim() || r.email || `#${r.id}`}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={submit}
              disabled={!recruiterId || submitting}
              data-testid="handoff-submit"
              className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Przekaż
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted"
            >
              Anuluj
            </button>
          </div>

          {blockers.length > 0 && (
            <div
              data-testid="handoff-blockers"
              className="rounded-md border border-border bg-muted px-3 py-2 text-xs text-foreground"
            >
              <div className="mb-1 flex items-center gap-1 font-medium">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                Rekrutacja nie jest gotowa:
              </div>
              <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
                {blockers.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </div>
          )}

          {error && (
            <div className="text-xs text-destructive" data-testid="handoff-error">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
