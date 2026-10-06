"use client";

import type { JobListNav } from "@/components/v2/jobs/job-list-nav";

import { type ReactNode, useState } from "react";
import Link from "next/link";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Link2,
  PencilLine,
  Target,
  UserPlus,
} from "lucide-react";

import api, {
  EMPTY_CHAMPION_VERIFICATION,
  type ChampionVerification,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn, formatRelativeTime } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { hasPermission, permissionLabel } from "@/lib/permissions";
import { canMutateSection, hasSectionAccess } from "@/lib/section-access";
import {
  jobEditScope,
} from "@/lib/job-edit-access";
import { hasRole, useAuthStore } from "@/store/auth";
import { useToast } from "@/components/Toast";
import { httpStatusFromError, resolveViewState } from "@/lib/view-state";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { Button, buttonVariants } from "@/components/ui/button";
import { TabbedNav } from "@/components/ds";
import { useCapability } from "@/hooks/useCapability";
import { extractSkills } from "@/lib/job-skills";
import {
  buildStageFunnel,
  funnelRejectedTotal,
  funnelTotal,
  type FunnelGroup,
  type PipelineStageSummary,
} from "@/lib/job-pipeline-funnel";
import { EditJobModal } from "@/components/AppShell";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import {
  JobOwnershipPanel,
  type JobOwnershipJob,
} from "@/components/v2/jobs/JobOwnershipPanel";
import { JobSettingsPanel } from "@/components/v2/jobs/JobSettingsPanel";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import { JobPriorityContext } from "@/components/v2/priority-work";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import {
  ReadinessRow,
  type ReadinessRowState,
} from "@/components/v2/jobs/ReadinessRow";
import { jobClientLine, jobDisplayTitle, type JobNames } from "@/lib/job-names";
import {
  CLAIM_ELIGIBLE_ROLES,
  hasActiveOwner,
} from "@/components/v2/jobs/ownership-types";
import {
  claimJob,
  hasRecruiter,
  proposedRecruiters,
  recruitersOf,
  workingRecruiters,
} from "@/lib/job-team";
import { formatJobBudgetLabel } from "@/lib/job-budget";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { priorityLevelOf, type PrioritySource } from "@/lib/request-priority";

/**
 * Do 04.10.2026 był też wariant „champion” (panel obok Profilu Championa).
 * Jego treść żyje teraz w zakładkach Profilu Championa (`ChampionWorkspace`):
 * „Do dopięcia” nad Briefem, „Zespół i ogłoszenie”.
 */
export type JobReadinessDockVariant = "list";

/**
 * Przewijanie po wierszach BIEŻĄCEJ STRONY listy (makieta: `‹ 1 z 12 ›`).
 *
 * `index` jest 1-BAZOWY, bo trafia wprost na ekran. Zakres to wczytana strona,
 * nie cały wynik zapytania — dok nie ma jak przeskoczyć na kolejną stronę, więc
 * „12" musi znaczyć „tyle wierszy widzisz", a nie „tyle jest rekrutacji".
 */
export type JobReadinessDockListNav = JobListNav;

interface JobReadinessDockProps {
  jobId: number | null;
  /**
   * Skrót pipeline'u z WIERSZA listy (`GET /api/jobs?include_stage_counts=true`)
   * — bez dodatkowego zapytania. `undefined`, gdy dane niedostępne (np. wiersz
   * spoza aktualnie wczytanej strony) — sekcja "Pipeline" po prostu się wtedy
   * nie renderuje, zamiast kłamać zerami. `stage_columns` grupuje ta sama
   * funkcja co szyny szczegółów (UAT B33).
   */
  stageBreakdown?: PipelineStageSummary;
  /**
   * `can_open` z wiersza listy (`GET /api/jobs` liczy go per wiersz). `false`
   * = detal (`GET /api/jobs/{id}`) odpowie 403 (zakres klient–TAC dla Delivery
   * Leada). Wtedy dok NIE wysyła żadnego zapytania i mówi wprost, jak zdobyć
   * dostęp — zamiast czerwonej ramki „Brak uprawnień" na każdym wejściu na
   * `/jobs` bez kliknięcia. Domyślnie `true`.
   */
  canOpen?: boolean;
  variant?: JobReadinessDockVariant;
  /** Patrz `JobReadinessDockListNav`. Tylko `variant="list"`. */
  listNav?: JobReadinessDockListNav;
  /**
   * Szczegóły z wiersza listy (`JobPreviewDetails`: wymagania, nazwy i numery,
   * podobne rekrutacje) — na górze zakładki „Gotowość”. Tylko `variant="list"`.
   * Nagłówek doku pokazuje wtedy samego klienta: reszta stoi w tej sekcji.
   */
  listDetails?: ReactNode;
  /**
   * Od jakiej szerokości okna dok stoi `sticky` obok treści i przewija się
   * sam: `"xl"` (domyślnie, strona rekrutacji) albo `"wide"` = 1680 px —
   * lista rekrutacji, gdzie węziej dok jest arkuszem wysuwanym nad tabelę.
   */
  stickyFrom?: "xl" | "wide";
}

type DockTab = "readiness" | "pipeline" | "team" | "history";

const LIST_DOCK_TABS: { value: DockTab; label: string }[] = [
  { value: "readiness", label: "Gotowość" },
  { value: "pipeline", label: "Pipeline" },
  { value: "team", label: "Zespół" },
  { value: "history", label: "Historia" },
];


// `GET /jobs/{id}/readiness` wymaga uprawnienia „Rekrutacje: zakładanie,
// zamykanie, wysyłka CV do klienta” (`RecruitmentManageUser`). Bez niego
// zapytanie kończy się 403 ZAWSZE — nie wysyłamy go (z `retry: 1` byłyby to
// dwa 403 na każde zaznaczenie wiersza); notatka „kto to widzi" renderuje się
// bez sieci.
const GATE_PERMISSION = "recruitment_manage" as const;

interface ReadinessItem {
  key: string;
  done: boolean;
  /** `neutral` — nie przypisano/nie dotyczy; patrz `ReadinessRowState`. */
  state?: ReadinessRowState;
  title: string;
  description: string;
  action?: ReactNode;
}

/** Link akcji wiersza — jeden wygląd na wszystkie wiersze listy gotowości. */
function rowLinkClass() {
  return "text-[11px] font-medium text-primary hover:underline";
}

/**
 * Bramka oficjalna „Przekaż do searchu” (`GET /api/jobs/{id}/readiness`).
 *
 * Widoczna WYŁĄCZNIE z uprawnieniem do prowadzenia rekrutacji (konto z rolą
 * Delivery Leada — u klientów ze swojego zakresu, to sprawdza handler) — dla
 * każdego innego konta to zapytanie kończy się 403. To NIE jest błąd do
 * ukrycia: pokazujemy czytelną notatkę „kto to widzi", żeby recruiter nie
 * myślał, że coś się nie wczytało.
 *
 * Od fali 3 werdykt jest JEDNĄ LINIĄ z licznikiem braków, rozwijaną kliknięciem
 * — pełna lista blokerów potrafiła zająć pół doku i spychała pod krawędź to,
 * po co ten dok istnieje (akcje). Nic nie znika: lista jest o jedno kliknięcie.
 */
function ReadinessGateBlock({
  query,
  canSeeGate,
}: {
  query: UseQueryResult<any, unknown>;
  /** Uprawnienie `GATE_PERMISSION` — bez niego zapytanie nie jest wysyłane
   *  (patrz wyżej). */
  canSeeGate: boolean;
}) {
  const [open, setOpen] = useState(false);

  const notice = (
    <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
      Bramka „Przekaż do searchu” — widoczna z uprawnieniem „
      {permissionLabel(GATE_PERMISSION)}” (Delivery Lead: u swoich klientów).
    </p>
  );

  if (!canSeeGate) return notice;
  if (query.isLoading) {
    return <Skeleton className="h-9 w-full rounded-md" />;
  }
  if (query.isError) {
    const status = httpStatusFromError(query.error);
    if (status === 403) return notice;
    return (
      <div className="flex items-center justify-between gap-2 rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
        <span>Nie udało się sprawdzić bramki „Przekaż do searchu”.</span>
        <button
          type="button"
          className="shrink-0 font-medium text-primary hover:underline"
          onClick={() => void query.refetch()}
        >
          Ponów
        </button>
      </div>
    );
  }
  const data = query.data;
  if (!data) return null;
  if (data.already_handed_off) {
    return (
      <p className="rounded-md border border-success/20 bg-success-muted px-2.5 py-2 text-[11px] text-success-muted-foreground">
        Już przekazana do searchu.
      </p>
    );
  }
  if (data.closed) {
    return (
      <p className="rounded-md border border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
        Rekrutacja zamknięta — bramka „Przekaż do searchu” nie dotyczy.
      </p>
    );
  }

  const blockers: string[] = Array.isArray(data.blockers) ? data.blockers : [];
  const expandable = !data.ready && blockers.length > 0;

  return (
    <div
      className={cn(
        "rounded-md border text-[11px]",
        data.ready
          ? "border-success/20 bg-success-muted text-success-muted-foreground"
          : "border-warning/25 bg-warning-muted text-warning-muted-foreground",
      )}
      data-testid="readiness-gate-block"
    >
      {expandable ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-center gap-1.5 px-2.5 py-2 text-left font-medium"
        >
          <span className="min-w-0 flex-1">
            Bramka „Przekaż do searchu”: zablokowana ·{" "}
            {countPl(blockers.length, "brak", "braki", "braków")}
          </span>
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" aria-hidden="true" />
          )}
        </button>
      ) : (
        <div className="px-2.5 py-2 font-medium">
          Bramka „Przekaż do searchu”: {data.ready ? "gotowa" : "zablokowana"}
        </div>
      )}
      {expandable && open ? (
        <ul className="list-disc space-y-0.5 px-2.5 pb-2 pl-7">
          {blockers.map((blocker: string) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Kropka etapu — kolor mówi „są tu ludzie", nie „to jest teraz aktywny krok". */
function stepDotClass(group: FunnelGroup): string {
  if (group.count === 0) return "bg-muted";
  if (group.key === "hired") return "bg-success";
  return "bg-primary";
}

function PipelineStepRow({
  label,
  count,
  dotClass,
}: {
  label: string;
  count: number;
  dotClass: string;
}) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-[11px]">
      <span
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", dotClass)}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate text-muted-foreground">{label}</span>
      <span className="shrink-0 font-medium tabular-nums text-foreground">
        {count}
      </span>
    </div>
  );
}

/**
 * Skrót pipeline'u w zakładce „Gotowość" — grupy Z LUDŹMI plus odrzuceni.
 *
 * Grupy zerowe schodzą tu z oczu (pełny rozkład jest w zakładce „Pipeline"),
 * ale ODRZUCENI zostają zawsze, gdy są: to jedyna liczba w tym module, która
 * mówi, że praca się dzieje, a mimo to nie przybywa kandydatów.
 */
function PipelineSummary({
  jobId,
  stageBreakdown,
}: {
  jobId: number;
  stageBreakdown: PipelineStageSummary | undefined;
}) {
  // "jeśli dane" — bez `include_stage_counts` z wiersza listy sekcja się nie
  // pokazuje, zamiast renderować zafałszowane zero.
  if (!stageBreakdown) return null;
  const groups = buildStageFunnel(stageBreakdown);
  const total = funnelTotal(groups);
  const rejected = funnelRejectedTotal(stageBreakdown);
  const nonZero = groups.filter((g) => g.count > 0);
  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h4 className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
          Pipeline · {countPl(total, "kandydat", "kandydatów", "kandydatów")}
        </h4>
        <Link
          href={`/jobs/${jobId}`}
          className="shrink-0 text-[10.5px] font-medium text-primary hover:underline"
        >
          Otwórz kanban
        </Link>
      </div>
      {nonZero.length === 0 && rejected === 0 ? (
        <p className="text-[11px] text-muted-foreground">
          Brak kandydatów w tym procesie.
        </p>
      ) : (
        <div>
          {nonZero.map((g) => (
            <PipelineStepRow
              key={g.key}
              label={g.label}
              count={g.count}
              dotClass={stepDotClass(g)}
            />
          ))}
          {rejected > 0 ? (
            <PipelineStepRow
              label="Odrzuceni / wycofani"
              count={rejected}
              dotClass="bg-destructive"
            />
          ) : null}
        </div>
      )}
    </div>
  );
}

/** Zakładka „Pipeline" — WSZYSTKIE osiem kolumn Tablicy, także zerowe (rozkład, nie skrót). */
function PipelineTab({
  jobId,
  stageBreakdown,
}: {
  jobId: number;
  stageBreakdown: PipelineStageSummary | undefined;
}) {
  if (!stageBreakdown) {
    return (
      <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
        Rozkład etapów jest dostępny dla wierszy z bieżącej strony listy.{" "}
        <Link href={`/jobs/${jobId}`} className="font-medium text-primary hover:underline">
          Otwórz kanban
        </Link>
        , żeby zobaczyć pełny pipeline.
      </p>
    );
  }
  const groups = buildStageFunnel(stageBreakdown);
  const total = funnelTotal(groups);
  const rejected = funnelRejectedTotal(stageBreakdown);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
          Pipeline · {countPl(total, "kandydat", "kandydatów", "kandydatów")}
        </h4>
        <Link
          href={`/jobs/${jobId}`}
          className="shrink-0 text-[10.5px] font-medium text-primary hover:underline"
        >
          Otwórz kanban
        </Link>
      </div>
      <div className="rounded-lg border border-border bg-muted/20 px-3 py-2">
        {groups.map((g) => (
          <PipelineStepRow
            key={g.key}
            label={g.label}
            count={g.count}
            dotClass={stepDotClass(g)}
          />
        ))}
        <PipelineStepRow
          label="Odrzuceni / wycofani"
          count={rejected}
          dotClass={rejected > 0 ? "bg-destructive" : "bg-muted"}
        />
      </div>
    </div>
  );
}

export function JobReadinessDock({
  jobId,
  stageBreakdown,
  canOpen = true,
  listNav,
  listDetails,
  stickyFrom = "xl",
}: JobReadinessDockProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const canWritePipeline = canMutateSection(authUser, "pipeline", impersonating);
  const claimEligible = authUser ? hasRole(authUser, ...CLAIM_ELIGIBLE_ROLES) : false;
  // Uprawnienie + sufit sekcji Pipeline (U8): konto z odebraną sekcją nie
  // wysyła zapytania, które skończy się 403.
  const canSeeGate = authUser
    ? hasPermission(authUser, GATE_PERMISSION) &&
      hasSectionAccess(authUser, "pipeline", "read")
    : false;
  // Lustro `page.tsx` (dawny header „Zespół i priorytet") dla ról, którym
  // wolno edytować Championa / dane zlecenia z tej zakładki doku.
  const canUpdateJob = useCapability("job.update");
  const [showEdit, setShowEdit] = useState(false);
  const [showAddCandidates, setShowAddCandidates] = useState(false);
  const [dockTab, setDockTab] = useState<DockTab>("readiness");

  // Klucz `["job", "<id>"]` = DOKŁADNIE ten, pod którym strona rekrutacji
  // trzyma zlecenie (`page.tsx`: `["job", id]`, `id` to string z `useParams`).
  // Jeden klucz → jeden fetch na kroku 02 (dok stoi obok edytora) i jedna
  // kopia zlecenia: edycja z karty „Zlecenie", Claim, HM i zapis Championa
  // (sync stacku do `must_skills`) odświeżają dok i stronę naraz. Osobny
  // klucz dawał dwie rozjeżdżające się kopie tego samego zlecenia.
  // `retry: false` na obu: 403/404 są deterministyczne — ponowienie tylko
  // dubluje odmowy w logach.
  const jobQuery = useQuery({
    queryKey: ["job", String(jobId)],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then((r) => r.data),
    enabled: jobId != null && canOpen,
    retry: false,
  });

  // Ten sam klucz i `staleTime` co `JobHandoffButton` (`["job-readiness", jobId]`)
  // — na kroku 02 oba stoją na jednej karcie; dwa klucze = dwa żądania i dwie
  // niezależnie starzejące się kopie werdyktu bramki.
  const readinessQuery = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data),
    enabled: jobId != null && canOpen && canSeeGate,
    staleTime: 30_000,
    retry: false,
  });

  const claimMutation = useMutation({
    mutationFn: () => claimJob(jobId as number),
    onSuccess: () => {
      toast.showSuccess("Od teraz pracujesz nad tą rekrutacją.");
    },
    onError: (err: unknown) => {
      toast.showError(apiErrorMessage(err, "Nie udało się wziąć rekrutacji."));
    },
    // Także po odmowie: 409 znaczy, że ktoś wziął rekrutację wcześniej.
    onSettled: () => invalidateJobTeam(queryClient, jobId),
  });

  if (jobId == null) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        <Target className="h-6 w-6 opacity-40" aria-hidden="true" />
        Wybierz rekrutację z listy, aby zobaczyć gotowość zlecenia.
      </div>
    );
  }

  if (!canOpen) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
        <Target className="h-6 w-6 opacity-40" aria-hidden="true" />
        Nie masz dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu.
      </div>
    );
  }

  const viewState = resolveViewState({
    isLoading: jobQuery.isLoading,
    isError: jobQuery.isError,
    error: jobQuery.error,
    isSuccess: jobQuery.isSuccess,
  });

  if (viewState === "loading") {
    return (
      <div className="space-y-3 rounded-xl border border-border bg-card p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-1/2" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error"
  ) {
    return (
      <QueryStateNotice
        state={viewState}
        className="rounded-xl"
        description={
          viewState === "forbidden"
            ? "Twoja rola nie ma dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu."
            : undefined
        }
        onRetry={() => void jobQuery.refetch()}
      />
    );
  }

  const job = jobQuery.data;
  // Dwa poziomy edycji (22.09.2026, `lib/job-edit-access.ts`): pełna
  // (`job.update`) i treść (`can_edit` z serwera — rekruter i kolejne
  // osoby: opis, ogłoszenia, Champion).
  const editScope = jobEditScope(job, {
    canWritePipeline,
    canManageJob: canUpdateJob,
  });
  const canManageJob = editScope === "full";
  const must = extractSkills(job.must_skills);
  const nice = extractSkills(job.nice_skills);
  const verification: ChampionVerification =
    (job.champion_profile?.verification as ChampionVerification | undefined) ??
    EMPTY_CHAMPION_VERIFICATION;
  const clientVerified = verification.client.status === "verified";
  const consultantStatus = verification.consultant.status;
  const consultantVerified = consultantStatus === "verified";
  // `skipped` = konsultant świadomie pominięty (jest `skip_reason`) — zamyka
  // pozycję, ale NIE jest weryfikacją; opis nie może twierdzić, że była
  // (`ChampionVerificationChecklist` rozróżnia te stany tak samo).
  const consultantSkipped = consultantStatus === "skipped";
  const championVerified =
    clientVerified && (consultantVerified || consultantSkipped);
  const canClaim =
    canWritePipeline &&
    claimEligible &&
    !hasActiveOwner(job.primary_owner) &&
    // Zamkniętej rekrutacji nikt już nie bierze (serwer odpowiada 409).
    job.status !== "closed" &&
    !claimMutation.isSuccess;

  // Rola „Rekruter” (02.10.2026): osoby, które nad rekrutacją PRACUJĄ. Sama
  // propozycja automatu to jeszcze nie praca — warunek zostaje niespełniony.
  const recruiters = recruitersOf(job);
  const workingNames = workingRecruiters(recruiters).map((person) => person.name);
  const proposedNames = proposedRecruiters(recruiters).map((person) => person.name);
  const ownerItem: ReadinessItem = {
    key: "owner",
    done: hasRecruiter(recruiters),
    title: "Rekruter",
    description:
      workingNames.length > 0
        ? workingNames.join(", ")
        : proposedNames.length > 0
          ? `Bez rekrutera — propozycja automatu (${proposedNames.join(", ")}) czeka na akceptację Head of Recruitment.`
          : job.primary_owner && !hasActiveOwner(job.primary_owner)
            ? `Bez rekrutera — ${job.primary_owner.name} ma nieaktywne konto.`
            : "Bez rekrutera — nikt jeszcze nie pracuje nad tą rekrutacją.",
    action: canClaim ? (
      <Button
        type="button"
        size="sm"
        variant="outline"
        loading={claimMutation.isPending}
        onClick={() => claimMutation.mutate()}
      >
        Biorę
      </Button>
    ) : undefined,
  };

  const budgetItem: ReadinessItem = {
    key: "budget",
    done: job.has_budget_hourly === true,
    title: "Budżet kandydacki",
    description: job.has_budget_hourly
      ? job.rate_budget_hourly != null
        ? (formatJobBudgetLabel(job) ?? `do ${job.rate_budget_hourly} PLN/h`)
        : "Ustawiony — ze stawki w Profilu Championa."
      : "Brak — dodaj budżet PLN/h do rekrutacji lub stawkę w Profilu Championa.",
  };

  const skillsItem: ReadinessItem = {
    key: "skills",
    done: must.length > 0,
    title: "Must / nice zsynchronizowane",
    description:
      must.length > 0
        ? `${must.length} must · ${nice.length} nice · zasilają AI Matching i filtry.`
        : "Brak — dodaj wymagania w Profilu Championa (sekcja Stack) lub w rekrutacji.",
  };

  const hiringManagerItem: ReadinessItem = {
    key: "hiring_manager",
    done: job.hiring_manager_name != null,
    // Brak HM to nie „zaległość", tylko nieprzypisana rola po stronie klienta —
    // stąd neutralny znacznik, a nie ostrzeżenie (makieta: `.d.z`).
    state: job.hiring_manager_name != null ? "done" : "neutral",
    title: "Hiring manager (klient)",
    description: job.hiring_manager_name
      ? job.hiring_manager_name
      : "nie przypisano — weto HM nie zadziała.",
    action:
      job.hiring_manager_name == null ? (
        <Link href={`/jobs/${jobId}`} className={rowLinkClass()}>
          Przypisz
        </Link>
      ) : undefined,
  };

  const championItem: ReadinessItem = {
    key: "champion",
    done: championVerified,
    title: "Profil Championa",
    description: championVerified
      ? consultantSkipped
        ? `Zweryfikowany z klientem; konsultant pominięty${
            verification.consultant.skip_reason
              ? ` — ${verification.consultant.skip_reason}`
              : ""
          }.`
        : "Zweryfikowany z klientem i konsultantem."
      : clientVerified || consultantVerified
        ? "Częściowo zweryfikowany — brakuje drugiej strony (klient/konsultant)."
        : "Niezweryfikowany — brak rozmowy z klientem i konsultantem.",
    action: (
      <Link href={`/jobs/${jobId}?tab=champion`} className={rowLinkClass()}>
        Otwórz
      </Link>
    ),
  };

  const items: ReadinessItem[] = [
    ownerItem,
    championItem,
    budgetItem,
    skillsItem,
    hiringManagerItem,
  ];

  const doneCount = items.filter((i) => i.done).length;
  const totalCount = items.length;
  const pct = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  // 0380: klient · „nazwa od klienta” · numer u klienta, potem nasz numer.
  const subtitle =
    listDetails
      ? (job.client_name ?? "")
      : [jobClientLine(job), job.reference_number].filter(Boolean).join(" · ");

  const tabs = LIST_DOCK_TABS;

  const copyJobLink = () => {
    const url =
      typeof window !== "undefined"
        ? `${window.location.origin}/jobs/${jobId}`
        : `/jobs/${jobId}`;
    // `navigator.clipboard` nie istnieje w niezabezpieczonym kontekście — bez
    // tej gałęzi klik po prostu nic nie robi i wygląda na zepsuty przycisk.
    if (!navigator?.clipboard?.writeText) {
      toast.showError("Przeglądarka nie pozwala skopiować linku.");
      return;
    }
    void navigator.clipboard
      .writeText(url)
      .then(() => toast.showSuccess("Skopiowano link do rekrutacji."))
      .catch(() => toast.showError("Nie udało się skopiować linku."));
  };

  return (
    <>
    {/* `xl:max-h` + `overflow-y-auto`: dok jest `sticky` na `xl`, a bywa
        wyższy niż okno — element sticky wyższy od viewportu nigdy nie odsłania
        swojego dołu. Ten sam wzorzec co `PipelineCandidateDock`. */}
    <div
      className={cn(
        "flex flex-col rounded-xl border border-border bg-card",
        // Własne przewijanie tylko tam, gdzie dok stoi `sticky` obok treści;
        // w arkuszu wysuwanym nad listę przewija się arkusz, nie karta.
        stickyFrom === "wide"
          ? "min-[1680px]:max-h-[calc(100dvh-2rem)] min-[1680px]:overflow-y-auto"
          : "xl:max-h-[calc(100dvh-2rem)] xl:overflow-y-auto",
      )}
      data-testid="job-readiness-dock-full"
    >
      {/* ── nagłówek doku (makieta: `.dhd`) ───────────────────────────────── */}
      <div className="space-y-2.5 border-b border-border px-4 pb-0 pt-3">
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {listNav ? (
            <div className="flex items-center gap-1" data-testid="dock-list-nav">
              <button
                type="button"
                onClick={listNav.onPrev}
                disabled={listNav.index <= 1}
                aria-label="Poprzednia rekrutacja"
                className="rounded p-0.5 text-muted-foreground hover:text-foreground pointer-coarse:p-2.5 disabled:opacity-40"
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <span className="tabular-nums">
                {listNav.index} z {listNav.total}
              </span>
              <button
                type="button"
                onClick={listNav.onNext}
                disabled={listNav.index >= listNav.total}
                aria-label="Następna rekrutacja"
                className="rounded p-0.5 text-muted-foreground hover:text-foreground pointer-coarse:p-2.5 disabled:opacity-40"
              >
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          ) : (
            <span className="min-w-0 truncate">Gotowość zlecenia</span>
          )}
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={copyJobLink}
              aria-label="Kopiuj link do rekrutacji"
              title="Kopiuj link do rekrutacji"
              className="rounded p-0.5 text-muted-foreground hover:text-foreground pointer-coarse:p-2.5"
            >
              <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Dok stoi obok listy — mówi, o której rekrutacji jest mowa. */}
        <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Target className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <Link
                href={`/jobs/${jobId}`}
                className="block truncate text-sm font-semibold text-foreground hover:text-primary hover:underline"
                title={jobDisplayTitle(job)}
              >
                {jobDisplayTitle(job)}
              </Link>
              {subtitle && (
                <div className="truncate text-xs text-muted-foreground">
                  {subtitle}
                </div>
              )}
            </div>
          </div>

        {/* `overflow="scroll"`, nie „wrap": cztery zakładki zawijały się na
            kroku 02 do dwóch wierszy na 1440 px i zjadały wysokość doku.
            `dense`: w 360-px doku pełny padding `px-3 text-sm` na czterech
            zakładkach chował ostatnią za krawędź — ciaśniejsze triggery
            mieszczą wszystkie w jednym wierszu (scroll to fallback). */}
        <TabbedNav
          ariaLabel="Zakładki gotowości zlecenia"
          value={dockTab}
          onValueChange={(v) => setDockTab(v as DockTab)}
          tabs={tabs}
          overflow="scroll"
          dense
        />
      </div>

      {/* ── treść (makieta: `.dbody`) ─────────────────────────────────────── */}
      <div className="flex-1 space-y-3 px-4 py-3">
        {dockTab === "readiness" && (
          <>
            {listDetails}
            <div>
              <div className="flex items-end gap-2">
                <span
                  className={cn(
                    "text-3xl font-bold leading-none tabular-nums",
                    doneCount === totalCount ? "text-success" : "text-warning",
                  )}
                >
                  {doneCount}
                </span>
                {/* „Kompletność", NIE „gotowość do searchu": ta checklista liczy
                    rekrutera, Championa, budżet, skille i HM — zbiór ROZŁĄCZNY
                    z oficjalną bramką „Przekaż do searchu” (`job_readiness.py`:
                    tytuł, klient, kontekst projektu, ≥2 pytania screeningowe).
                    Werdykt bramki jest niżej, w `ReadinessGateBlock`; dwie liczby
                    pod tą samą nazwą przeczyłyby sobie na jednej karcie.
                    Makieta podpisuje ten licznik „gotowość zlecenia do searchu"
                    — świadomie NIE przejmujemy tego zdania. */}
                <span className="pb-0.5 text-xs text-muted-foreground">
                  / {totalCount} · kompletność zlecenia ({pct}%)
                </span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-1.5 rounded-full transition-all",
                    doneCount === totalCount ? "bg-success" : "bg-warning",
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>

            <ReadinessGateBlock query={readinessQuery} canSeeGate={canSeeGate} />

            <div className="space-y-1.5">
              {items.map((item) => (
                <ReadinessRow
                  key={item.key}
                  state={item.state ?? (item.done ? "done" : "todo")}
                  title={item.title}
                  description={item.description}
                  action={item.action}
                />
              ))}
            </div>

            <PipelineSummary jobId={jobId} stageBreakdown={stageBreakdown} />


            <div className="grid grid-cols-2 gap-2 pt-1">
              {/* Goły <a> ze stylami `buttonVariants`, nie `<Button asChild>` —
                  `Button` dokłada slot na spinner, więc Radix `Slot` dostałby dwoje
                  dzieci (lustro `PrepInviteActions.tsx`). Nawigacja, nie mutacja —
                  zawsze aktywna, niezależnie od `canWritePipeline`. */}
              <Link
                href={`/jobs/${jobId}?tab=people&seg=proposals`}
                className={cn(
                  buttonVariants({ variant: "primary", size: "sm" }),
                  "col-span-2 w-full",
                )}
              >
                <Target className="h-3.5 w-3.5" aria-hidden="true" /> Otwórz propozycje z bazy
              </Link>
              {canWritePipeline && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full justify-start"
                    onClick={() => setShowAddCandidates(true)}
                  >
                    <UserPlus className="h-3.5 w-3.5" /> Dodaj kandydata
                  </Button>
                  {editScope !== "none" && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="w-full justify-start"
                      onClick={() => setShowEdit(true)}
                    >
                      <PencilLine className="h-3.5 w-3.5" /> Edytuj rekrutację
                    </Button>
                  )}
                </>
              )}
            </div>
          </>
        )}

        {dockTab === "pipeline" && (
          <PipelineTab jobId={jobId} stageBreakdown={stageBreakdown} />
        )}

        {dockTab === "team" && <JobTeamTab jobId={jobId} job={job} />}

        {dockTab === "history" && (
          <RequestHistorySection
            jobId={jobId}
            clientId={job.client_id ?? null}
            readOnly={!canWritePipeline}
            compact
            maxItems={3}
          />
        )}
      </div>

      {/* ── stopka (makieta: `.dfoot`) ────────────────────────────────────── */}
      {job.updated_at ? (
        <div className="mt-auto flex items-center gap-1.5 border-t border-border bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
          <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
          Ostatnia zmiana: {formatRelativeTime(job.updated_at)}
        </div>
      ) : null}
      {canWritePipeline && showAddCandidates && (
        <AddCandidatesQuickModal
          open={showAddCandidates}
          onClose={() => setShowAddCandidates(false)}
          jobId={jobId}
          jobTitle={jobDisplayTitle(job)}
        />
      )}
      {editScope !== "none" && showEdit && (
        <EditJobModal
          job={job}
          scope={canManageJob ? "full" : "content"}
          onClose={() => setShowEdit(false)}
          onSuccess={() => {
            // Okno zmienia też rekrutera i kolejne osoby — odświeżamy obsadę
            // wszędzie, gdzie ją widać (rekrutacja, lista, liczniki, pulpit).
            invalidateJobTeam(queryClient, jobId);
            setShowEdit(false);
          }}
        />
      )}
    </div>
    </>
  );
}

/** Pola rekrutacji (`GET /api/jobs/{id}`), które czyta zakładka „Zespół”. */
export interface JobTeamTabJob extends JobOwnershipJob, PrioritySource, JobNames {
  client_id?: number | null;
  delivery_lead_id?: number | null;
  deadline?: string | null;
  deadline_time?: string | null;
  competence_category_id?: number | null;
  hiring_manager_contact_id?: number | null;
  hiring_manager_name?: string | null;
  /** 04.10.2026: „Klient nie podał” — decyzja zamiast pustego pola. */
  hiring_manager_not_provided?: boolean | null;
  deadline_not_provided?: boolean | null;
  headcount?: number | null;
  can_edit?: boolean | null;
  /** Czy bieżąca osoba ustawia priorytet TEJ rekrutacji; brak = capability. */
  can_set_priority?: boolean | null;
}

/**
 * Zakładka „Zespół” panelu zlecenia: karta z trzema rolami (Delivery Lead,
 * Rekruter, Kategoria), terminem i priorytetem, pod nią hiring manager klienta
 * i kontekst Priority Work. Osobny komponent, żeby harness
 * `/preview/job-team-panel` renderował DOKŁADNIE tę treść, którą pokazuje dok.
 */
export function JobTeamTab({
  jobId,
  job,
}: {
  jobId: number;
  job: JobTeamTabJob;
}) {
  const queryClient = useQueryClient();
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const canWritePipeline = canMutateSection(authUser, "pipeline", impersonating);
  const canUpdateJob = useCapability("job.update");
  const priorityCapability = useCapability("job.priority.update");
  // Ta sama reguła co w doku: pełna edycja (`job.update`) albo treść (`can_edit`).
  const editScope = jobEditScope(job, {
    canWritePipeline,
    canManageJob: canUpdateJob,
  });
  // `can_set_priority` z serwera zna zakres Delivery Leada; capability to rola.
  const canSetPriority =
    canWritePipeline &&
    (typeof job.can_set_priority === "boolean"
      ? job.can_set_priority
      : priorityCapability);

  return (
    <div className="space-y-4">
      <JobSettingsPanel
        jobId={jobId}
        clientId={job.client_id ?? null}
        deliveryLeadId={job.delivery_lead_id ?? null}
        deadline={job.deadline ?? null}
        deadlineTime={job.deadline_time ?? null}
        deadlineNotProvided={job.deadline_not_provided === true}
        headcount={job.headcount ?? null}
        canEdit={editScope === "full"}
        categoryId={job.competence_category_id ?? null}
        priorityLevel={priorityLevelOf(job)}
        canSetPriority={canSetPriority}
        recruiters={
          <JobOwnershipPanel
            jobId={jobId}
            jobTitle={jobDisplayTitle(job)}
            job={job}
            // Kolejne osoby dopisuje każdy, kto redaguje rekrutację (29.09.2026).
            canEdit={editScope !== "none"}
          />
        }
      />
      <HiringManagerPicker
        jobId={jobId}
        clientId={job.client_id ?? null}
        value={job.hiring_manager_contact_id ?? null}
        valueName={job.hiring_manager_name ?? null}
        notProvided={job.hiring_manager_not_provided === true}
        // HM ustawia każdy, kto redaguje rekrutację (decyzja 25.09.2026) —
        // lustro `ensure_job_editor` w `PUT …/hiring-manager`.
        canEdit={editScope !== "none"}
        onSaved={() =>
          queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] })
        }
      />
      <JobPriorityContext jobId={jobId} />
    </div>
  );
}
