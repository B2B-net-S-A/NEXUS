"use client";

import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send, AlertTriangle, CheckCircle2 } from "lucide-react";

import { api, jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import {
  AUTOMATIC_DISABLED_TEXT,
  automaticAssignmentAvailable,
  automaticHandoffOutcome,
  automaticTakenText,
  resolveRecruiterAssignment,
  type AllocationMode,
  type RecruiterAssignment,
} from "@/lib/recruiter-assignment";
import type { PriorityLevel } from "@/lib/request-priority";
import { RecruiterAssignmentChoice } from "@/components/v2/jobs/RecruiterAssignmentChoice";

interface RecruiterOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

interface JobHandoffButtonProps {
  jobId: number;
  /**
   * Priorytet rekrutacji. Przy „Przyjmujemy kandydatów” automat nikogo nie
   * proponuje — pole mówi to zamiast obiecywać propozycję.
   */
  priorityLevel?: PriorityLevel;
  /**
   * Pierwszy rekruter rekrutacji (`primary_owner`), jeśli już jest — także
   * z nieaktywnym kontem. Serwer odmawia wtedy przekazania „automatowi” (409),
   * więc opcja jest nieaktywna, a osoba z listy zaznaczona z góry.
   */
  recruiter?: { id: number; name?: string | null } | null;
}

interface JobReadiness {
  job_id: number;
  ready: boolean;
  blockers: string[];
  closed: boolean;
  already_handed_off: boolean;
  allocation_enabled?: boolean;
  /** Tryb automatu przydziału; `off` = „Zaproponuje automat” jest niedostępne. */
  allocation_mode?: AllocationMode;
}

/**
 * DL "Przekaż do searchu" — assign a recruiter and start the (Champion-aware)
 * ranking. Replaces the create-time auto-ranking (P0-A): the recruiter never
 * lands on a stale pre-Champion snapshot. A 422 lists readiness blockers
 * (Champion required) instead of firing the ranking.
 *
 * Rekruter (02.10.2026): „Zaproponuje automat” jest wyborem domyślnym, gdy
 * automat jest włączony — propozycję zatwierdza Head of Recruitment i do tego
 * czasu nikt nie jest przypisany. „Wybieram sam” przypisuje osobę od razu.
 */
export function JobHandoffButton({
  jobId,
  priorityLevel,
  recruiter = null,
}: JobHandoffButtonProps) {
  const queryClient = useQueryClient();
  const recruiterLabelId = useId();
  const passive = priorityLevel === "accepting";
  const [open, setOpen] = useState(false);
  // `undefined` = nikt jeszcze nie dotknął listy — wtedy podpowiadamy obecnego
  // rekrutera rekrutacji, o ile jest na liście.
  const [pickedRecruiterId, setPickedRecruiterId] = useState<
    number | null | undefined
  >(undefined);
  const [submitting, setSubmitting] = useState(false);
  const [blockers, setBlockers] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  // `null` = nikt nie wybrał — wtedy automat, o ile jest dostępny.
  const [assignmentChoice, setAssignmentChoice] =
    useState<RecruiterAssignment | null>(null);
  const [channel, setChannel] = useState<"linkedin" | "database" | "mixed">("linkedin");
  // Wynik przekazania — zapamiętany, bo po odświeżeniu gotowości tryb automatu
  // mógłby się już różnić od tego, z którym poszło żądanie.
  const [done, setDone] = useState<{
    automatic: boolean;
    mode?: AllocationMode;
    passive: boolean;
  } | null>(null);

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
    // Lustro pozostałych konsumentów klucza (nagłówek, okno „Zlecenie”, dok):
    // 403 nie zmieni się od ponowienia, a ponowienia opóźniały komunikat.
    retry: false,
  });
  // Braki i przycisk mają sens WYŁĄCZNIE po udanym odczycie. Odmowa (403 —
  // rola albo DL spoza portfela) i awaria wyglądały dotąd jak „brak braków”,
  // czyli aktywny przycisk, który kończył się kolejnym błędem.
  const readinessStatus = (
    readinessQuery.error as { response?: { status?: number } } | null
  )?.response?.status;
  const readiness = readinessQuery.data;
  // `isSuccess`, nie `!isLoading`: w przerwie między ponowieniami react-query
  // ma `isLoading === false` i puste `data`, a wtedy „brak braków" znaczyłoby
  // „gotowa", zanim cokolwiek jest wiadomo.
  // `?? []` nie jest kosmetyką: gdy endpoint jest starszy, za proxy albo
  // zamockowany innym kształtem, `blockers` bywa `undefined` — a `.length`
  // na nim wywala CAŁY komponent, czyli zabiera przycisk „Przekaż do searchu"
  // zamiast tylko listy braków.
  const knownBlockers =
    readinessQuery.isSuccess && Array.isArray(readiness?.blockers)
      ? readiness.blockers
      : [];

  const automatOn = automaticAssignmentAvailable(
    readiness?.allocation_enabled,
    readiness?.allocation_mode,
  );
  // Rekrutacja z pierwszym rekruterem nie dostaje propozycji automatu, a serwer
  // odmawia przekazania „automatowi” — nie proponujemy wyboru, który skończy
  // się 409.
  const automaticAvailable = automatOn && recruiter == null;
  // Gotowość jest już wczytana (inaczej okno by się nie otworzyło), więc
  // niedostępny automat ma zawsze znany powód.
  const unavailableReason = !automatOn
    ? AUTOMATIC_DISABLED_TEXT
    : recruiter != null
      ? automaticTakenText(recruiter.name)
      : null;
  const assignment = resolveRecruiterAssignment(assignmentChoice, automaticAvailable);
  const automatic = assignment === "automatic";

  const recruitersQuery = useQuery({
    queryKey: ["handoff-recruiters"],
    enabled: open,
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["recruiter"] },
          // FastAPI binds repeated `roles=`; axios 1.x defaults to `roles[]=`,
          // which the backend ignores → it falls back to ALL roles (incl.
          // admin/DL). `indexes: null` emits the repeated form (P1-05a).
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as RecruiterOption[]),
  });
  const currentRecruiterListed =
    recruiter != null &&
    (recruitersQuery.data ?? []).some((option) => option.id === recruiter.id);
  const recruiterId =
    pickedRecruiterId !== undefined
      ? pickedRecruiterId
      : currentRecruiterListed
        ? recruiter.id
        : null;

  const submit = async () => {
    if (!automatic && !recruiterId) return;
    setSubmitting(true);
    setBlockers([]);
    setError(null);
    try {
      if (automatic) {
        await api.post(`/api/jobs/${jobId}/handoff`, { assignment_mode: "automatic", channel });
      } else if (recruiterId) {
        await jobsApi.handoff(jobId, recruiterId, undefined, channel);
      }
      setDone({ automatic, mode: readiness?.allocation_mode, passive });
      // Przekazanie zmienia obsadę (osoba albo propozycja automatu) i stan
      // bramki — odświeżamy oba, zamiast czekać na ponowne wejście.
      invalidateJobTeam(queryClient, jobId);
      void queryClient.invalidateQueries({ queryKey: ["job-readiness", jobId] });
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
        setError(apiErrorMessage(e, "Nie udało się przekazać do searchu."));
        // 409 przy automacie = wyłączono go w międzyczasie; pokaż stan aktualny.
        if (resp?.status === 409) {
          void queryClient.invalidateQueries({ queryKey: ["job-readiness", jobId] });
        }
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div
        data-testid="handoff-done"
        className="mt-4 flex items-start gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground"
      >
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
        <span>
          {done.automatic
            ? `Przekazano do searchu. ${automaticHandoffOutcome(done.mode, done.passive)}${
                done.mode === "auto" || done.passive
                  ? ""
                  : " Do tego czasu rekrutacja jest bez rekrutera."
              }`
            : "Przekazano do searchu — ranking się generuje. Rekruter dostał dostęp do rekrutacji."}
        </span>
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
            Wskaż, kto dostanie rekrutację, i uruchom dopasowywanie na podstawie
            Profilu Championa.
          </p>
        </div>
        {!open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            disabled={
              !readinessQuery.isSuccess ||
              knownBlockers.length > 0 ||
              readiness?.closed === true
            }
            data-testid="handoff-open"
            className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Przekaż do searchu
          </button>
        )}
      </div>

      {readinessQuery.isError && (
        <div
          data-testid="handoff-readiness-error"
          role="alert"
          className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
        >
          <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
          {readinessStatus === 403 ? (
            <span>
              Przekazać do searchu może admin albo Delivery Lead tej rekrutacji.
            </span>
          ) : (
            <>
              <span>Nie udało się sprawdzić, czy rekrutacja jest gotowa.</span>
              <button
                type="button"
                onClick={() => void readinessQuery.refetch()}
                className="font-medium text-foreground underline underline-offset-2"
              >
                Ponów
              </button>
            </>
          )}
        </div>
      )}

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
          <div className="space-y-1.5">
            <span
              id={recruiterLabelId}
              className="block text-xs font-medium text-foreground"
            >
              Rekruter
            </span>
            <RecruiterAssignmentChoice
              size="sm"
              labelledBy={recruiterLabelId}
              value={assignment}
              onChange={setAssignmentChoice}
              automaticAvailable={automaticAvailable}
              unavailableReason={unavailableReason}
              mode={readiness?.allocation_mode}
              passive={passive}
              disabled={submitting}
            />
            {!automatic && (
              <select
                aria-label="Wybierz rekrutera"
                value={recruiterId ?? ""}
                onChange={(e) => {
                  setPickedRecruiterId(e.target.value ? Number(e.target.value) : null);
                  // Wskazanie osoby to jawny wybór „Wybieram sam”.
                  setAssignmentChoice("person");
                }}
                data-testid="handoff-recruiter-select"
                className="w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              >
                <option value="">— wybierz rekrutera —</option>
                {recruitersQuery.data?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name?.trim() || r.email || `#${r.id}`}
                  </option>
                ))}
              </select>
            )}
            {/* Awaria listy to nie „nie ma kogo wybrać” — osobny komunikat. */}
            {!automatic && recruitersQuery.isError && !recruitersQuery.data ? (
              <p role="alert" className="text-xs text-destructive">
                Nie udało się wczytać listy rekruterów.{" "}
                <button
                  type="button"
                  className="font-medium underline"
                  onClick={() => void recruitersQuery.refetch()}
                >
                  Ponów
                </button>
              </p>
            ) : null}
          </div>
          <label className="flex items-center gap-2 text-sm">Kanał pracy
            <select aria-label="Kanał pracy" className="rounded border border-border bg-background p-2" value={channel}
              onChange={event => setChannel(event.target.value as typeof channel)}>
              <option value="linkedin">LinkedIn</option><option value="database">Baza</option><option value="mixed">Baza i LinkedIn</option>
            </select>
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={(!automatic && !recruiterId) || submitting}
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
