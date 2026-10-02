"use client";

import { useState, type ReactElement, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { decideProposal } from "@/lib/api/requestAllocation";
import { COLLABORATOR_ROLES } from "@/lib/job-collaborators";
import {
  addRecruiter,
  assignedByCaption,
  canRemoveRecruiter,
  claimJob,
  hasWorkingOwner,
  joinJob,
  recruitersOf,
  removeRecruiter,
  workingRecruiters,
  type JobRecruiter,
  type JobTeamSource,
  type RecruiterAccess,
} from "@/lib/job-team";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { priorityLevelOf, type PrioritySource } from "@/lib/request-priority";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, ROLE_LABELS, useAuthStore, type UserRole } from "@/store/auth";
import { useCapability } from "@/hooks/useCapability";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { ReassignOwnerV2 } from "@/components/v2/modals/ReassignOwnerV2";
import { RecruiterChips } from "./RecruiterChips";
import {
  CLAIM_ELIGIBLE_ROLES,
  hasActiveOwner,
  type UserBrief,
} from "./ownership-types";

/** Pola rekrutacji (`GET /api/jobs/{id}`), z których panel czyta obsadę. */
export interface JobOwnershipJob extends JobTeamSource, PrioritySource {
  primary_owner?: UserBrief | null;
  /**
   * Czy bieżąca osoba przydziela i zdejmuje rekruterów TEJ rekrutacji (rola
   * + zakres Delivery Leada). Brak pola = starszy serwer, wtedy capability.
   */
  can_staff?: boolean | null;
  status?: string | null;
}

interface JobOwnershipPanelProps {
  jobId: number;
  jobTitle: string;
  job: JobOwnershipJob;
  /**
   * Czy bieżąca osoba redaguje rekrutację (`can_edit` z `GET /api/jobs/{id}`).
   * Kolejne osoby dopisuje i zdejmuje każdy, kto redaguje (decyzja 29.09.2026,
   * lustro `ensure_job_editor`).
   */
  canEdit: boolean;
}

/**
 * Kogo można wskazać zamiast propozycji automatu — lustro `_assignable_person`
 * w `backend/app/api/request_board.py` (inna rola = 422).
 */
const PROPOSAL_REPLACEMENT_ROLES = ["recruiter"] as const;

const LINK_BUTTON_CLASS =
  "hit-area inline-flex items-center gap-0.5 text-[11px] font-medium text-primary hover:underline disabled:pointer-events-none disabled:opacity-50";

const NO_RECRUITER_LABEL = (
  <span className="inline-flex h-6 items-center rounded-full bg-warning-muted px-2.5 text-xs font-medium text-warning-muted-foreground">
    Bez rekrutera
  </span>
);

/**
 * Wiersz „Rekruter” panelu zespołu (decyzja Artura 02.10.2026).
 *
 * Rekruterem jest osoba, która nad rekrutacją PRACUJE: przydzielona przez
 * Delivery Leada albo Head of Recruitment, taka, która wzięła ją sama, albo
 * zaakceptowana propozycja automatu. Propozycja (przerywana ramka) to jeszcze
 * nie praca — do decyzji Head of Recruitment nikt nie jest przypisany.
 *
 * Komponent tylko chowa akcje, do których osoba nie ma prawa; ostatecznie
 * rozstrzyga serwer. Po KAŻDYM zapisie odświeża obsadę wszędzie, gdzie ją
 * widać (`invalidateJobTeam`).
 */
export function JobOwnershipPanel({
  jobId,
  jobTitle,
  job,
  canEdit,
}: JobOwnershipPanelProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const currentUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const staffCapability = useCapability("job.recruiter.assign");
  const canDecide = useCapability("request.proposal.decide");
  const [reassignOpen, setReassignOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  const canWritePipeline =
    !impersonating && hasSectionAccess(currentUser, "pipeline", "write");
  // `can_staff` z serwera zna zakres Delivery Leada; capability to tylko rola.
  const canStaff =
    canWritePipeline &&
    (typeof job.can_staff === "boolean" ? job.can_staff : staffCapability);
  const access: RecruiterAccess = {
    canStaff,
    canDecide,
    canEdit: canWritePipeline && canEdit,
  };

  const people = recruitersOf(job);
  const working = workingRecruiters(people);
  const ownerWorking = hasWorkingOwner(people);
  const meId = currentUser?.id ?? null;
  const onList = meId != null && working.some((p) => p.user_id === meId);
  // Head of Recruitment przydziela innych, ale sam rekruterem nie zostaje.
  const eligible = hasRole(currentUser, ...CLAIM_ELIGIBLE_ROLES);
  const ownerSeatTaken = hasActiveOwner(job.primary_owner);
  // „Biorę” przy wolnej rekrutacji; zamkniętej nikt już nie bierze (serwer: 409).
  const canClaim =
    canWritePipeline && eligible && !ownerSeatTaken && job.status !== "closed";
  // „Dołącz” przy zajętej — dopisuje zalogowaną osobę jako kolejną.
  const canJoin =
    access.canEdit &&
    eligible &&
    meId != null &&
    !onList &&
    !canClaim &&
    (working.length > 0 || ownerSeatTaken);
  // Zamkniętej rekrutacji nikt nie dostaje do prowadzenia (serwer: 409) —
  // zostaje samo zdjęcie osoby.
  const canAssign = canStaff && job.status !== "closed";
  // Rola przydzielająca bez pracującego pierwszego rekrutera ma „Przypisz…”;
  // „+ Dodaj osobę” zrobiłoby wtedy to samo (`addRecruiter` ustawia pierwszego).
  const canAdd = canStaff ? ownerWorking : access.canEdit;

  /**
   * Każdy zapis kończy się odświeżeniem obsady — także nieudany: 409 znaczy,
   * że ktoś zmienił ją w międzyczasie i ekran pokazuje nieaktualny stan.
   */
  const run = async (
    key: string,
    action: () => Promise<unknown>,
    messages: { done: string; failed: string },
  ) => {
    if (pending != null) return;
    setPending(key);
    try {
      await action();
      toast.showSuccess(messages.done);
    } catch (err) {
      toast.showError(apiErrorMessage(err, messages.failed));
    } finally {
      invalidateJobTeam(queryClient, jobId);
      setPending(null);
    }
  };

  const remove = async (person: JobRecruiter) => {
    if (pending != null) return;
    const self = person.user_id === meId;
    const confirmed = await askConfirm({
      title: self
        ? "Zdjąć siebie z tej rekrutacji?"
        : `Zdjąć ${person.name} z tej rekrutacji?`,
      description: self
        ? "Przestaniesz być rekruterem tej rekrutacji."
        : `${person.name} przestanie być rekruterem tej rekrutacji.`,
      confirmLabel: "Zdejmij",
    });
    if (!confirmed) return;
    await run(
      `remove:${person.user_id}`,
      () => removeRecruiter(jobId, person, { canStaff }),
      {
        done: self
          ? "Nie jesteś już rekruterem tej rekrutacji."
          : `${person.name}: zdjęto z rekrutacji.`,
        failed: "Nie udało się zdjąć osoby z rekrutacji.",
      },
    );
  };

  const decide = (
    person: JobRecruiter,
    decision: "accept" | "reject",
  ) =>
    run(
      `${decision}:${person.user_id}`,
      () => decideProposal(jobId, person.user_id, { decision }),
      decision === "accept"
        ? {
            done: `${person.name} pracuje nad tą rekrutacją.`,
            failed: "Nie udało się zaakceptować propozycji.",
          }
        : {
            done: "Propozycja automatu odrzucona.",
            failed: "Nie udało się odrzucić propozycji.",
          },
    );

  const workingIds = working.map((p) => p.user_id);

  const proposalActions = canDecide
    ? (person: JobRecruiter) => (
        <>
          <Button
            type="button"
            size="sm"
            variant="primary"
            loading={pending === `accept:${person.user_id}`}
            disabled={pending != null}
            onClick={() => void decide(person, "accept")}
          >
            Akceptuj
          </Button>
          <PersonPicker
            heading="Kto zamiast propozycji automatu"
            roles={PROPOSAL_REPLACEMENT_ROLES}
            excludeIds={[person.user_id, ...workingIds]}
            emptyLabel="Nie ma innej osoby do wskazania."
            onPick={(user) =>
              void run(
                `replace:${person.user_id}`,
                () =>
                  decideProposal(jobId, person.user_id, {
                    decision: "replace",
                    replacement_user_id: user.id,
                  }),
                {
                  done: `${user.name} pracuje nad tą rekrutacją zamiast propozycji automatu.`,
                  failed: "Nie udało się zmienić propozycji.",
                },
              )
            }
            trigger={
              <button
                type="button"
                className={LINK_BUTTON_CLASS}
                disabled={pending != null}
                aria-label={`Zmień propozycję: ${person.name}`}
              >
                Zmień
              </button>
            }
          />
          <button
            type="button"
            className={LINK_BUTTON_CLASS}
            disabled={pending != null}
            onClick={() => void decide(person, "reject")}
          >
            Odrzuć
          </button>
        </>
      )
    : undefined;

  const caption = (person: JobRecruiter): ReactNode =>
    person.proposed ? (
      <span className="font-medium text-warning-muted-foreground">
        Czeka na akceptację Head of Recruitment
      </span>
    ) : (
      assignedByCaption(person)
    );

  // „Co dalej” tylko wtedy, gdy nie ma nikogo — także propozycji (ta mówi sama
  // za siebie: czeka na akceptację).
  const inactiveOwnerNote =
    job.primary_owner && !ownerSeatTaken
      ? `${job.primary_owner.name} ma nieaktywne konto. `
      : "";
  // „Przyjmujemy kandydatów” = nie szukamy aktywnie; automat takim requestom
  // nikogo nie proponuje, więc nie obiecujemy propozycji.
  const passive = priorityLevelOf(job) === "accepting";
  const nextStep =
    people.length > 0
      ? null
      : `${inactiveOwnerNote}${
          canStaff
            ? passive
              ? "Przypisz osobę — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje."
              : "Przypisz osobę albo poczekaj na propozycję automatu (jeśli jest włączony)."
            : canClaim
              ? "Możesz wziąć tę rekrutację — kliknij „Biorę”."
              : "Rekrutera przydziela Delivery Lead albo Head of Recruitment."
        }`;

  const hasActions = canStaff || canAdd || canClaim || canJoin;

  return (
    <div className="min-w-0 space-y-1.5" data-testid="job-recruiters">
      <RecruiterChips
        people={people}
        size="md"
        label="Rekruter"
        caption={caption}
        onRemove={(person) => void remove(person)}
        // Propozycję odrzuca „Odrzuć” obok „Akceptuj” — bez drugiego krzyżyka.
        canRemove={(person) =>
          !person.proposed && canRemoveRecruiter(person, access)
        }
        proposalActions={proposalActions}
        emptyLabel={NO_RECRUITER_LABEL}
      />
      {nextStep ? (
        <p className="text-[11px] leading-snug text-muted-foreground">
          {nextStep}
        </p>
      ) : null}
      {hasActions ? (
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          {canAssign && !ownerWorking ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={pending != null}
              onClick={() => setReassignOpen(true)}
            >
              Przypisz…
            </Button>
          ) : null}
          {canClaim ? (
            <Button
              type="button"
              size="sm"
              variant={canStaff ? "outline" : "primary"}
              loading={pending === "claim"}
              disabled={pending != null}
              onClick={() =>
                void run("claim", () => claimJob(jobId), {
                  done: "Od teraz pracujesz nad tą rekrutacją.",
                  failed: "Nie udało się wziąć rekrutacji.",
                })
              }
            >
              Biorę
            </Button>
          ) : null}
          {canJoin && meId != null ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              loading={pending === "join"}
              disabled={pending != null}
              onClick={() =>
                void run("join", () => joinJob(jobId, meId), {
                  done: "Dołączono do rekrutacji.",
                  failed: "Nie udało się dołączyć do rekrutacji.",
                })
              }
            >
              Dołącz
            </Button>
          ) : null}
          {canAssign && ownerWorking ? (
            <button
              type="button"
              className={LINK_BUTTON_CLASS}
              disabled={pending != null}
              aria-label="Zmień rekrutera"
              onClick={() => setReassignOpen(true)}
            >
              Zmień
            </button>
          ) : null}
          {canAdd ? (
            <PersonPicker
              heading="Kolejna osoba przy rekrutacji"
              roles={COLLABORATOR_ROLES}
              excludeIds={workingIds}
              emptyLabel="Wszyscy już pracują nad tą rekrutacją."
              onPick={(user) =>
                void run(
                  "add",
                  () =>
                    addRecruiter(jobId, user.id, {
                      hasWorkingOwner: ownerWorking,
                      canStaff,
                    }),
                  {
                    done: `${user.name}: dodano do rekrutacji.`,
                    failed: "Nie udało się dodać osoby do rekrutacji.",
                  },
                )
              }
              trigger={
                <button
                  type="button"
                  className={LINK_BUTTON_CLASS}
                  disabled={pending != null}
                >
                  + Dodaj osobę
                </button>
              }
            />
          ) : null}
        </div>
      ) : null}

      {canStaff ? (
        <ReassignOwnerV2
          open={reassignOpen}
          onOpenChange={setReassignOpen}
          jobId={jobId}
          jobTitle={jobTitle}
          currentOwner={ownerWorking ? (job.primary_owner ?? null) : null}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}

interface DirectoryUser {
  id: number;
  name: string;
  role?: string | null;
  roles?: string[] | null;
}

function roleLabelOf(user: DirectoryUser): string | null {
  if (!user.role) return null;
  return ROLE_LABELS[user.role as UserRole] ?? user.role;
}

/**
 * Lista osób do wskazania jednym kliknięciem. Ten sam katalog i klucz co
 * `UserMultiSelect` (`["users-directory"]`) — bez drugiego zapytania; wczytuje
 * się dopiero po otwarciu.
 */
function PersonPicker({
  trigger,
  heading,
  roles,
  excludeIds,
  emptyLabel,
  onPick,
}: {
  trigger: ReactElement;
  heading: string;
  /** Tylko osoby z którąkolwiek z tych ról (rola główna albo dodatkowa). */
  roles: readonly string[];
  excludeIds: readonly number[];
  emptyLabel: string;
  onPick: (user: DirectoryUser) => void;
}) {
  const [open, setOpen] = useState(false);
  const { data, isPending, isError, isSuccess, refetch } = useQuery<
    DirectoryUser[]
  >({
    queryKey: ["users-directory"],
    queryFn: () => api.get("/api/users").then((r) => r.data),
    staleTime: 60_000,
    enabled: open,
  });
  const users = (data ?? []).filter(
    (user) =>
      !excludeIds.includes(user.id) &&
      roles.some(
        (role) => user.role === role || (user.roles ?? []).includes(role),
      ),
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <Command>
          <CommandInput placeholder="Szukaj osoby…" aria-label={heading} />
          <CommandList>
            <PickerQueryState
              isPending={isPending}
              isError={isError}
              onRetry={() => void refetch()}
              loadingLabel="Ładowanie listy osób…"
              errorLabel="Nie udało się pobrać listy osób."
            />
            {isSuccess && <CommandEmpty>{emptyLabel}</CommandEmpty>}
            <CommandGroup>
              {users.map((user) => (
                <CommandItem
                  key={user.id}
                  // Id w wartości: dwie osoby o tym samym nazwisku to dwie pozycje.
                  value={`${user.name} ${user.id}`}
                  onSelect={() => {
                    setOpen(false);
                    onPick(user);
                  }}
                >
                  <span className="min-w-0 flex-1 truncate">{user.name}</span>
                  {roleLabelOf(user) ? (
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {roleLabelOf(user)}
                    </span>
                  ) : null}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
