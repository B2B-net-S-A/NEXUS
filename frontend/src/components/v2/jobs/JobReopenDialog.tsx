"use client";

/**
 * „Otwórz ponownie” zamkniętą rekrutację albo „Dokończ i opublikuj” stary
 * szkic (04.10.2026, „Rekrutacja bez szkiców”).
 *
 * Rekrutacja w pracy jest zawsze kompletna i przekazana do searchu, więc
 * ponowne otwarcie przechodzi tę samą bramkę co przekazanie: okno pokazuje
 * braki z `GET /readiness` (`blocker_items`) i woła
 * `POST /api/jobs/{id}/publish`. Odmowa 422 `job_not_ready` pokazuje braki
 * z odpowiedzi w tym samym oknie. Zmiana statusu w oknie edycji już tego nie
 * robi (409 `reopen_required`).
 *
 * Rekruter (09.10.2026): „Otwórz ponownie” o niego NIE pyta — zamknięcie nie
 * czyści rekrutera, więc zostaje dotychczasowy (`assignment_mode: "keep"`),
 * a gdy go nie ma, przydziela automat albo wskazuje Head of Recruitment.
 * „Dokończ i opublikuj” (stary szkic nigdy nie miał rekrutera) pyta jak
 * „Przekaż do searchu”: automat albo osoba (`RecruiterAssignmentChoice`).
 *
 * Braki z działaniem (08.10.2026): hiring managera i termin (albo „Klient nie
 * podał”) ustawia się w tym oknie — archiwum z Traffita nie ma ich nigdy, więc
 * pyta o nie każde ponowne otwarcie. Kategoria i liczba osób prowadzą do
 * zakładki „Zespół i ogłoszenie”, reszta do Profilu Championa. Do tej daty
 * każdy brak odsyłał do Championa, w którym tych czterech pól nie ma.
 */

import { useId, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import { AppModal } from "@/components/ds";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import { DeadlineEditor } from "@/components/v2/jobs/JobSettingsPanel";
import { RecruiterAssignmentChoice } from "@/components/v2/jobs/RecruiterAssignmentChoice";
import {
  api,
  jobsApi,
  type JobHandoffChannel,
  type JobPublishPayload,
} from "@/lib/api";
import { useCachedJob } from "@/lib/cached-job";
import {
  blockerItemsFrom,
  jobGateErrorText,
  jobGateRefusal,
  type JobBlockerItem,
} from "@/lib/job-gate-errors";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { READINESS_ACTION, readinessKeyFor, type ReadinessKey } from "@/lib/order-readiness";
import {
  AUTOMATIC_DISABLED_TEXT,
  automaticAssignmentAvailable,
  automaticTakenText,
  resolveRecruiterAssignment,
  type AllocationMode,
  type RecruiterAssignment,
} from "@/lib/recruiter-assignment";
import { httpStatusFromError } from "@/lib/view-state";

export type JobReopenMode = "reopen" | "finish";

export interface JobReopenDialogProps {
  jobId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `reopen` — zamknięta rekrutacja; `finish` — stary szkic albo bez przekazania. */
  mode: JobReopenMode;
  /** Pierwszy rekruter rekrutacji. Brak = z rekrutacji w cache'u (`primary_owner`). */
  recruiter?: { id: number; name?: string | null; is_active?: boolean } | null;
  /** „Uzupełnij” przy brakach — strona otwiera edytor Profilu Championa. */
  onOpenChampion?: () => void;
  /** Braki z zakładki „Zespół i ogłoszenie” (kategoria, liczba osób). */
  onOpenTeam?: () => void;
}

/** Pola rekrutacji z cache'u (`["job", id]`), których okno potrzebuje. */
interface ReopenCachedJob {
  primary_owner?: { id: number; name?: string | null; is_active?: boolean } | null;
  client_id?: number | null;
  hiring_manager_contact_id?: number | null;
  hiring_manager_name?: string | null;
  hiring_manager_not_provided?: boolean | null;
  deadline?: string | null;
  deadline_time?: string | null;
  deadline_not_provided?: boolean | null;
}

interface ReadinessResponse {
  blockers?: unknown;
  blocker_items?: unknown;
  allocation_enabled?: boolean;
  allocation_mode?: AllocationMode;
}

interface RecruiterOption {
  id: number;
  name?: string | null;
  email?: string | null;
}

export const JOB_REOPEN_LABELS: Record<
  JobReopenMode,
  { title: string; submit: string; success: string; description: string }
> = {
  reopen: {
    title: "Otwórz ponownie",
    submit: "Otwórz i opublikuj",
    success: "Rekrutacja otwarta ponownie i opublikowana.",
    description:
      "Rekrutacja wróci do pracy i od razu trafi do searchu — dlatego musi być kompletna. O rekrutera nie pytamy.",
  },
  finish: {
    title: "Dokończ i opublikuj",
    submit: "Opublikuj",
    success: "Rekrutacja opublikowana i przekazana do searchu.",
    description:
      "Rekrutacja nie jest jeszcze w pracy. Uzupełnij braki i wskaż rekrutera — publikacja od razu przekazuje ją do searchu.",
  },
};

/** Braki z odpowiedzi `/readiness`: `blocker_items`, a bez nich zdania `blockers`. */
function readinessBlockers(data: ReadinessResponse | undefined): JobBlockerItem[] {
  if (!data) return [];
  const items = blockerItemsFrom(data.blocker_items);
  return items.length > 0 ? items : blockerItemsFrom(data.blockers);
}

const READINESS_KEYS = new Set<string>(Object.keys(READINESS_ACTION));

/** Klucz braku: kod z serwera, a dla starszej odpowiedzi — rozpoznane zdanie. */
function blockerKey(blocker: JobBlockerItem): ReadinessKey | null {
  return READINESS_KEYS.has(blocker.code)
    ? (blocker.code as ReadinessKey)
    : readinessKeyFor(blocker.message);
}

export function JobReopenDialog({
  jobId,
  open,
  onOpenChange,
  mode,
  recruiter,
  onOpenChampion,
  onOpenTeam,
}: JobReopenDialogProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const labels = JOB_REOPEN_LABELS[mode];
  // Ponowne otwarcie zostawia rekrutera; o osobę pyta tylko „Dokończ i opublikuj”.
  const keepTeam = mode === "reopen";
  const recruiterLabelId = useId();
  const reasonId = useId();
  const channelId = useId();
  const cachedJob = useCachedJob<ReopenCachedJob>(jobId);
  const clientId = cachedJob?.client_id ?? null;
  const knownRecruiter =
    recruiter !== undefined ? recruiter : (cachedJob?.primary_owner ?? null);
  // Nieaktywne konto = brak rekrutera: serwer otwiera wtedy rekrutację bez
  // nikogo, więc okno nie może obiecywać „zostaje bez zmian”.
  const currentRecruiter = knownRecruiter?.is_active === false ? null : knownRecruiter;

  const [assignmentChoice, setAssignmentChoice] = useState<RecruiterAssignment | null>(null);
  const [pickedRecruiterId, setPickedRecruiterId] = useState<number | null | undefined>(
    undefined,
  );
  const [channel, setChannel] = useState<JobHandoffChannel>("linkedin");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Braki z odmowy 422 `job_not_ready` — świeższe niż odczyt gotowości.
  const [refusedBlockers, setRefusedBlockers] = useState<JobBlockerItem[] | null>(null);
  const [refusalMessage, setRefusalMessage] = useState<string | null>(null);
  const [deadlineSaving, setDeadlineSaving] = useState(false);
  const [deadlineError, setDeadlineError] = useState<string | null>(null);

  // Ten sam klucz co dok, przycisk handoffu i okno „Zlecenie”.
  const readinessQuery = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () =>
      api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data as ReadinessResponse),
    enabled: open,
    staleTime: 30_000,
    retry: false,
  });
  const readiness = readinessQuery.data;
  const knownBlockers = readinessQuery.isSuccess ? readinessBlockers(readiness) : [];
  const blockers = refusedBlockers ?? knownBlockers;

  const recruitersQuery = useQuery({
    queryKey: ["handoff-recruiters"],
    enabled: open && !keepTeam,
    queryFn: () =>
      api
        .get("/api/users", {
          params: { roles: ["recruiter"] },
          // FastAPI wiąże powtórzone `roles=` — jak w `JobHandoffButton`.
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data as RecruiterOption[]),
  });

  const automatOn = automaticAssignmentAvailable(
    readiness?.allocation_enabled,
    readiness?.allocation_mode,
  );
  const automaticAvailable = automatOn && currentRecruiter == null;
  const unavailableReason = !readinessQuery.isSuccess
    ? null
    : !automatOn
      ? AUTOMATIC_DISABLED_TEXT
      : currentRecruiter != null
        ? automaticTakenText(currentRecruiter.name)
        : null;
  const assignment = resolveRecruiterAssignment(assignmentChoice, automaticAvailable);
  const automatic = assignment === "automatic";
  const currentListed =
    currentRecruiter != null &&
    (recruitersQuery.data ?? []).some((option) => option.id === currentRecruiter.id);
  const recruiterId =
    pickedRecruiterId !== undefined
      ? pickedRecruiterId
      : currentListed && currentRecruiter
        ? currentRecruiter.id
        : null;

  const reset = () => {
    setAssignmentChoice(null);
    setPickedRecruiterId(undefined);
    setChannel("linkedin");
    setReason("");
    setRefusedBlockers(null);
    setRefusalMessage(null);
    setDeadlineError(null);
  };
  // Decyzja zapisana w oknie: braki z odmowy są już nieaktualne. Ten sam
  // komplet unieważnień co zapis w zakładce „Zespół” (`JobSettingsPanel`).
  const afterDecisionSaved = () => {
    setRefusedBlockers(null);
    setRefusalMessage(null);
    invalidateChampionDependents(queryClient, jobId);
    invalidateJobTeam(queryClient, jobId);
  };
  const saveDeadline = async (body: {
    deadline: string | null;
    deadline_time: string | null;
    deadline_not_provided: boolean;
  }) => {
    if (!body.deadline && !body.deadline_not_provided) {
      setDeadlineError("Wybierz datę albo zaznacz „Klient nie podał”.");
      return;
    }
    setDeadlineSaving(true);
    setDeadlineError(null);
    try {
      await api.patch(`/api/jobs/${jobId}`, body);
      afterDecisionSaved();
    } catch (error) {
      setDeadlineError(jobGateErrorText(error, "Nie udało się zapisać terminu."));
    } finally {
      setDeadlineSaving(false);
    }
  };
  const changeOpen = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const submit = async () => {
    if (!keepTeam && !automatic && !recruiterId) return;
    const trimmedReason = reason.trim();
    const payload: JobPublishPayload = keepTeam
      ? { assignment_mode: "keep", ...(trimmedReason ? { reason: trimmedReason } : {}) }
      : automatic
        ? { assignment_mode: "automatic", channel }
        : { recruiter_id: recruiterId as number, channel };
    setSubmitting(true);
    setRefusedBlockers(null);
    setRefusalMessage(null);
    try {
      await jobsApi.publish(jobId, payload);
      invalidateJobTeam(queryClient, jobId);
      void queryClient.invalidateQueries({ queryKey: ["job-readiness", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      showSuccess(labels.success);
      changeOpen(false);
    } catch (error) {
      const refusal = jobGateRefusal(error);
      if (refusal?.code === "job_not_ready") {
        setRefusedBlockers(refusal.blockers);
        setRefusalMessage(refusal.message);
        void queryClient.invalidateQueries({ queryKey: ["job-readiness", jobId] });
      } else {
        showError(jobGateErrorText(error, "Nie udało się opublikować rekrutacji."));
        // 409 przy automacie = tryb przydziału zmienił się w międzyczasie.
        if (httpStatusFromError(error) === 409) {
          void queryClient.invalidateQueries({ queryKey: ["job-readiness", jobId] });
        }
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Brak, który da się zamknąć w tym oknie — kontrolka zamiast odsyłania.
  // Hiring manager jest kontaktem klienta, więc bez klienta zostaje link.
  const fixableHere = (key: ReadinessKey | null): boolean =>
    key === "deadline" || (key === "hiring_manager" && clientId != null);
  const inlineFix = (key: ReadinessKey | null): ReactNode => {
    if (!fixableHere(key)) return null;
    if (key === "hiring_manager" && clientId != null) {
      return (
        <HiringManagerPicker
          jobId={jobId}
          clientId={clientId}
          value={cachedJob?.hiring_manager_contact_id ?? null}
          valueName={cachedJob?.hiring_manager_name ?? null}
          notProvided={cachedJob?.hiring_manager_not_provided === true}
          canEdit
          onSaved={afterDecisionSaved}
        />
      );
    }
    return (
      <div className="space-y-1">
        <div className="flex">
          <DeadlineEditor
            autoFocus={false}
            deadline={cachedJob?.deadline ?? null}
            deadlineTime={cachedJob?.deadline_time ?? null}
            notProvided={cachedJob?.deadline_not_provided === true}
            saving={deadlineSaving}
            onSave={(date, time) =>
              void saveDeadline({
                deadline: date,
                deadline_time: date ? time : null,
                deadline_not_provided: false,
              })
            }
            onSaveNotProvided={() =>
              void saveDeadline({
                deadline: null,
                deadline_time: null,
                deadline_not_provided: true,
              })
            }
          />
        </div>
        {deadlineError ? (
          <p role="alert" className="text-xs text-destructive">
            {deadlineError}
          </p>
        ) : null}
      </div>
    );
  };
  // Pozostałe braki: decyzje o rekrutacji żyją w zakładce „Zespół
  // i ogłoszenie”, reszta w Profilu Championa.
  const linkedKeys = blockers.map(blockerKey).filter((key) => !fixableHere(key));
  const needsTeam = linkedKeys.some((key) => key != null && READINESS_ACTION[key] === "team");
  const needsChampion = linkedKeys.some((key) => key == null || READINESS_ACTION[key] !== "team");

  const readinessForbidden =
    readinessQuery.isError && httpStatusFromError(readinessQuery.error) === 403;
  const submitDisabled =
    submitting ||
    readinessForbidden ||
    blockers.length > 0 ||
    (!keepTeam && !automatic && !recruiterId);
  const recruiterName = currentRecruiter?.name?.trim() || null;
  // Jedno zdanie o rekruterze przy ponownym otwarciu — bez pola wyboru.
  const keepTeamNote = currentRecruiter
    ? `Rekruter: ${recruiterName ?? "przypisana osoba"} — zostaje bez zmian.`
    : !readinessQuery.isSuccess
      ? "Rekruter zostaje bez zmian."
      : automatOn
        ? readiness?.allocation_mode === "auto"
          ? "Rekrutacja nie ma rekrutera — po otwarciu przydzieli go automat."
          : "Rekrutacja nie ma rekrutera — po otwarciu zaproponuje go automat (zatwierdza Head of Recruitment)."
        : "Rekrutacja nie ma rekrutera — po otwarciu wskaże go Head of Recruitment.";

  return (
    <AppModal
      open={open}
      onOpenChange={changeOpen}
      title={labels.title}
      description={labels.description}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => changeOpen(false)}>
            Anuluj
          </Button>
          <Button
            type="button"
            onClick={() => void submit()}
            loading={submitting}
            disabled={submitDisabled}
            data-testid="job-reopen-submit"
          >
            {labels.submit}
          </Button>
        </>
      }
    >
      <div className="space-y-4" data-testid="job-reopen-dialog">
        {readinessQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Sprawdzam, czy rekrutacja jest kompletna…</p>
        ) : null}
        {readinessQuery.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-hidden="true" />
            {readinessForbidden ? (
              <span>
                Otworzyć rekrutację może osoba z uprawnieniem do prowadzenia rekrutacji
                (zwykle admin albo Delivery Lead).
              </span>
            ) : (
              <>
                <span>Nie udało się sprawdzić, czego brakuje w rekrutacji.</span>
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
        ) : null}

        {blockers.length > 0 ? (
          <section
            data-testid="job-reopen-blockers"
            className="rounded-md border border-warning/30 bg-warning-muted px-3 py-2"
          >
            <p className="flex items-center gap-1.5 text-xs font-medium text-warning-muted-foreground">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              {refusalMessage ?? "Zanim opublikujesz, uzupełnij:"}
            </p>
            <ul className="mt-1 list-disc space-y-1.5 pl-5 text-xs text-warning-muted-foreground">
              {blockers.map((b, index) => {
                const fix = inlineFix(blockerKey(b));
                return (
                  <li key={`${b.code}-${index}`}>
                    {b.message}
                    {fix ? (
                      <div className="mt-1 rounded-md border border-border bg-card px-2 py-1.5 text-foreground">
                        {fix}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            {needsTeam || needsChampion ? (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                {needsTeam ? (
                  onOpenTeam ? (
                    <button
                      type="button"
                      onClick={() => {
                        changeOpen(false);
                        onOpenTeam();
                      }}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Ustaw w zakładce „Zespół i ogłoszenie”
                    </button>
                  ) : (
                    <Link
                      href={`/jobs/${jobId}?tab=champion&ptab=team`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Ustaw w zakładce „Zespół i ogłoszenie”
                    </Link>
                  )
                ) : null}
                {needsChampion ? (
                  onOpenChampion ? (
                    <button
                      type="button"
                      onClick={() => {
                        changeOpen(false);
                        onOpenChampion();
                      }}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Uzupełnij w Profilu Championa
                    </button>
                  ) : (
                    <Link
                      href={`/jobs/${jobId}?tab=champion&mode=edit`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Uzupełnij w Profilu Championa
                    </Link>
                  )
                ) : null}
              </div>
            ) : null}
          </section>
        ) : readinessQuery.isSuccess ? (
          <p className="text-sm text-success">Niczego nie brakuje — rekrutację można opublikować.</p>
        ) : null}

        {keepTeam ? (
          <p className="text-sm text-muted-foreground" data-testid="job-reopen-recruiter-note">
            {keepTeamNote} Zmienisz go w zakładce „Zespół i ogłoszenie”.
          </p>
        ) : (
          <>
            <div className="space-y-1.5">
              <span id={recruiterLabelId} className="block text-xs font-medium text-foreground">
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
                disabled={submitting}
              />
              {!automatic ? (
                <select
                  aria-label="Wybierz rekrutera"
                  value={recruiterId ?? ""}
                  onChange={(e) => {
                    setPickedRecruiterId(e.target.value ? Number(e.target.value) : null);
                    setAssignmentChoice("person");
                  }}
                  data-testid="job-reopen-recruiter"
                  className="w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
                >
                  <option value="">— wybierz rekrutera —</option>
                  {recruitersQuery.data?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name?.trim() || r.email || `#${r.id}`}
                    </option>
                  ))}
                </select>
              ) : null}
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

            <div className="space-y-1">
              <label htmlFor={channelId} className="block text-xs font-medium text-foreground">
                Kanał pracy
              </label>
              <select
                id={channelId}
                value={channel}
                onChange={(e) => setChannel(e.target.value as JobHandoffChannel)}
                className="w-full min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
              >
                <option value="linkedin">LinkedIn</option>
                <option value="database">Baza</option>
                <option value="mixed">Baza i LinkedIn</option>
              </select>
            </div>
          </>
        )}

        {mode === "reopen" ? (
          <div className="space-y-1">
            <label htmlFor={reasonId} className="block text-xs font-medium text-foreground">
              Powód otwarcia (opcjonalnie)
            </label>
            <textarea
              id={reasonId}
              rows={3}
              // Serwer przyjmuje 500 znaków (`JobPublishRequest.reason`).
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="np. klient wrócił z tym samym zapytaniem"
              className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}

export default JobReopenDialog;
