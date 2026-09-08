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
  championApi,
  EMPTY_CHAMPION_VERIFICATION,
  type ChampionBriefing,
  type ChampionVerification,
  type RecommendedSearch,
} from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import { countPl } from "@/lib/plural-pl";
import { canMutateSection } from "@/lib/section-access";
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
} from "@/lib/job-pipeline-funnel";
import { EditJobModal } from "@/components/AppShell";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import { RECRUITMENT_TYPE_LABEL } from "@/lib/recruitment-type";
import {
  ChampionVerificationChecklist,
  championVerificationDone,
} from "@/components/ChampionVerificationChecklist";
import { ChampionRecommendedSearches } from "@/components/ChampionRecommendedSearches";
import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import { JobPriorityContext } from "@/components/v2/priority-work";
import { JobHandoffButton } from "@/components/v2/jobs/JobHandoffButton";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import {
  ReadinessRow,
  type ReadinessRowState,
} from "@/components/v2/jobs/ReadinessRow";

export type JobReadinessDockVariant = "list" | "champion";

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
   * nie renderuje, zamiast kłamać zerami.
   */
  stageBreakdown?: Record<string, number>;
  /**
   * `can_open` z wiersza listy (`GET /api/jobs` liczy go per wiersz). `false`
   * = detal (`GET /api/jobs/{id}`) odpowie 403 (zakres klient–TAC dla Delivery
   * Leada). Wtedy dok NIE wysyła żadnego zapytania i mówi wprost, jak zdobyć
   * dostęp — zamiast czerwonej ramki „Brak uprawnień" na każdym wejściu na
   * `/jobs` bez kliknięcia. Domyślnie `true`.
   */
  canOpen?: boolean;
  /**
   * "champion" (krok 02 „Zlecenie i Champion", program „flow w języku C2"):
   * weryfikacja dwustronna i briefing wchodzą do JEDNEJ listy gotowości (7
   * warunków zamiast 5), dochodzą zakładki „Zespół i priorytet" /
   * „Wyszukiwania (AI)", a `JobHandoffButton` jest główną akcją. "list"
   * (krok 01) zostaje przy pięciu warunkach i identyfikacji zlecenia
   * w nagłówku — tam dok stoi obok listy, więc musi mówić, o której
   * rekrutacji jest mowa.
   */
  variant?: JobReadinessDockVariant;
  /** Patrz `JobReadinessDockListNav`. Tylko `variant="list"`. */
  listNav?: JobReadinessDockListNav;
}

type DockTab = "readiness" | "pipeline" | "team" | "searches" | "history";

const LIST_DOCK_TABS: { value: DockTab; label: string }[] = [
  { value: "readiness", label: "Gotowość" },
  { value: "pipeline", label: "Pipeline" },
  { value: "team", label: "Zespół" },
  { value: "history", label: "Historia" },
];

// Etykiety krótsze niż w makiecie („Zespół i priorytet" / „Wyszukiwania (AI)")
// świadomie: dok ma 360 px, a cztery pełne etykiety nie mieszczą się w jednym
// wierszu — chowały „Historię" za krawędź. Krótsze + `dense` (patrz `TabbedNav`)
// pokazują wszystkie cztery naraz, jak zakłada makieta. Znaczenie zostaje jasne
// z kontekstu (treść zakładki „Zespół" to właściciel + HM + Priority Work).
const CHAMPION_DOCK_TABS: { value: DockTab; label: string }[] = [
  { value: "readiness", label: "Gotowość" },
  { value: "team", label: "Zespół" },
  { value: "searches", label: "Wyszukiwania" },
  { value: "history", label: "Historia" },
];

// Lustro `_OWNERSHIP_ELIGIBLE_ROLES` w `backend/app/api/jobs.py`:
// `POST /jobs/{id}/claim` odrzuca 403 („Read-only viewers cannot claim jobs")
// każdą inną rolę — także te z zapisem w sekcji pipeline (finance,
// head_of_recruitment, talent_community_manager). Przycisk bez tego lustra
// = gwarantowany 403 po kliknięciu.
const CLAIM_ELIGIBLE_ROLES = [
  "admin",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
] as const;

// `GET /jobs/{id}/readiness` → `DeliveryLeadPlus` (admin + delivery_lead).
// Dla pozostałych ról zapytanie kończy się 403 ZAWSZE — nie wysyłamy go
// (z `retry: 1` byłyby to dwa 403 na każde zaznaczenie wiersza); notatka
// „kto to widzi" renderuje się bez sieci.
const GATE_ROLES = ["admin", "delivery_lead"] as const;

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
 * Widoczna WYŁĄCZNIE dla admina/DL przypisanego do klienta tej rekrutacji
 * (`DeliveryLeadPlus` + zakres klient–DL w handlerze) — dla każdej innej roli
 * to zapytanie kończy się 403. To NIE jest błąd do ukrycia: pokazujemy
 * czytelną notatkę „kto to widzi", żeby recruiter nie myślał, że coś się nie
 * wczytało.
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
  /** Rola z `GATE_ROLES` — bez niej zapytanie nie jest wysyłane (patrz wyżej). */
  canSeeGate: boolean;
}) {
  const [open, setOpen] = useState(false);

  const notice = (
    <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
      Bramka „Przekaż do searchu” — widoczna dla Delivery Lead / admina
      przypisanego do tego klienta.
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
  stageBreakdown: Record<string, number> | undefined;
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

/** Zakładka „Pipeline" — WSZYSTKIE sześć grup, także zerowe (rozkład, nie skrót). */
function PipelineTab({
  jobId,
  stageBreakdown,
}: {
  jobId: number;
  stageBreakdown: Record<string, number> | undefined;
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
  variant = "list",
  listNav,
}: JobReadinessDockProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const canWritePipeline = canMutateSection(authUser, "pipeline", impersonating);
  const claimEligible = authUser ? hasRole(authUser, ...CLAIM_ELIGIBLE_ROLES) : false;
  const canSeeGate = authUser ? hasRole(authUser, ...GATE_ROLES) : false;
  // Lustro `page.tsx` (dawny header „Zespół i priorytet") dla ról, którym
  // wolno edytować Championa / dane zlecenia z tej zakładki doku.
  const canUpdateJob = useCapability("job.update");
  const canEditChampion = canWritePipeline && hasRole(authUser, "admin", "delivery_lead");
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

  // Weryfikacja/briefing/rekomendowane wyszukiwania żyją pod
  // `["champion-profile", jobId]` — TEN SAM klucz, którego używa
  // `ChampionProfileEditor` (współbieżnie zamontowany obok tego doku na
  // kroku 02), więc React Query dedupe'uje fetch zamiast go podwajać, a
  // mutacje w checkliście/wyszukiwaniach odświeżają OBA miejsca naraz.
  const championQuery = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId as number).then((r) => r.data),
    enabled: jobId != null && canOpen && variant === "champion",
    retry: false,
  });
  const championProfile = championQuery.data?.champion_profile as
    | {
        verification?: ChampionVerification;
        briefing?: ChampionBriefing;
        recommended_searches?: RecommendedSearch[];
        stack?: { must?: unknown; nice?: unknown };
      }
    | undefined;
  // Awaria `GET …/champion-profile` NIE może renderować się jako fakt
  // „Niezweryfikowany" / „brak propozycji" — bloki Championa montują się
  // wyłącznie pod `isSuccess`, a błąd dostaje własną notatkę z „Ponów".
  const championBlocked =
    variant === "champion" && !championQuery.isSuccess ? (
      championQuery.isError ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
          <span>Nie udało się pobrać Profilu Championa.</span>
          <button
            type="button"
            className="shrink-0 font-medium text-primary hover:underline"
            onClick={() => void championQuery.refetch()}
          >
            Ponów
          </button>
        </div>
      ) : (
        <Skeleton className="h-16 w-full rounded-md" />
      )
    ) : null;

  const claimMutation = useMutation({
    mutationFn: () => api.post(`/api/jobs/${jobId}/claim`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
      toast.showSuccess("Przejęto rekrutację.");
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Nie udało się przejąć projektu.";
      toast.showError(detail);
    },
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
  // Na kroku 02 źródłem prawdy o Championie jest `["champion-profile", jobId]`
  // — ten sam klucz, który unieważnia edytor i checklista obok. Czytanie
  // weryfikacji i stacku z kopii zlecenia dawało dok, który zaprzeczał
  // edytorowi stojącemu 300 px obok do czasu odświeżenia strony.
  const championStack = championProfile?.stack as
    | { must?: unknown; nice?: unknown }
    | undefined;
  const must = extractSkills(
    variant === "champion" && championStack ? championStack.must : job.must_skills,
  );
  const nice = extractSkills(
    variant === "champion" && championStack ? championStack.nice : job.nice_skills,
  );
  const verification: ChampionVerification =
    (variant === "champion"
      ? championProfile?.verification
      : (job.champion_profile?.verification as ChampionVerification | undefined)) ??
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
    job.primary_owner == null &&
    !claimMutation.isSuccess;

  const ownerItem: ReadinessItem = {
    key: "owner",
    done: job.primary_owner != null,
    title: "Właściciel projektu",
    description: job.primary_owner
      ? job.primary_owner.name
      : "Nieprzypisany — nikt nie dostanie alertów deadline'u.",
    action: canClaim ? (
      <Button
        type="button"
        size="sm"
        variant="outline"
        loading={claimMutation.isPending}
        onClick={() => claimMutation.mutate()}
      >
        Claim
      </Button>
    ) : undefined,
  };

  const budgetItem: ReadinessItem = {
    key: "budget",
    done: job.has_budget_hourly === true,
    title: "Budżet kandydacki",
    description: job.has_budget_hourly
      ? job.rate_budget_hourly != null
        ? `do ${job.rate_budget_hourly} PLN/h`
        : "Ustawiony — ze stawki w Profilu Championa."
      : "Brak — dodaj budżet PLN/h do oferty lub stawkę w Profilu Championa.",
  };

  const skillsItem: ReadinessItem = {
    key: "skills",
    done: must.length > 0,
    title:
      variant === "champion" ? "Stack → must / nice" : "Must / nice zsynchronizowane",
    description:
      must.length > 0
        ? `${must.length} must · ${nice.length} nice · zasilają C2 i filtry.`
        : "Brak — dodaj wymagania w Profilu Championa (sekcja Stack) lub w ofercie.",
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
        variant === "champion" ? (
          // Picker HM jest zakładką TEGO doku — przełączamy ją, zamiast
          // linkować na tę samą trasę (miękka nawigacja bez `?tab=` nie
          // zmienia niczego widocznego).
          <button
            type="button"
            onClick={() => setDockTab("team")}
            className={rowLinkClass()}
          >
            Przypisz
          </button>
        ) : (
          <Link href={`/jobs/${jobId}`} className={rowLinkClass()}>
            Przypisz
          </Link>
        )
      ) : undefined,
  };

  // Na kroku 02 „Profil Championa" NIE jest jednym wierszem: jego treścią są
  // trzy wiersze weryfikacji i briefingu wyżej, a edytor stoi tuż obok — wiersz
  // „Otwórz" prowadziłby na ekran, na którym użytkownik już jest.
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

  const items: ReadinessItem[] =
    variant === "champion"
      ? [skillsItem, budgetItem, ownerItem, hiringManagerItem]
      : [ownerItem, championItem, budgetItem, skillsItem, hiringManagerItem];

  // Trzy warunki weryfikacji liczy `championVerificationDone` — ta sama funkcja,
  // z której `ChampionVerificationChecklist` rysuje wiersze. Gdy profil się nie
  // wczytał, NIE dokładamy ich do mianownika: „2 / 7" sugerowałoby pięć braków
  // tam, gdzie o trzech po prostu nic nie wiemy.
  const verificationDone =
    variant === "champion" && championQuery.isSuccess
      ? championVerificationDone(
          championProfile?.verification,
          championProfile?.briefing,
        )
      : null;
  const verificationTotal = verificationDone ? 3 : 0;
  const verificationDoneCount = verificationDone
    ? [verificationDone.client, verificationDone.consultant, verificationDone.briefing].filter(
        Boolean,
      ).length
    : 0;

  const doneCount = items.filter((i) => i.done).length + verificationDoneCount;
  const totalCount = items.length + verificationTotal;
  const pct = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  const subtitle = [
    job.client_name,
    RECRUITMENT_TYPE_LABEL[job.recruitment_type as string] ?? job.recruitment_type,
    job.reference_number,
  ]
    .filter(Boolean)
    .join(" · ");

  const tabs = variant === "champion" ? CHAMPION_DOCK_TABS : LIST_DOCK_TABS;

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

  const teamTab = (
    <div className="space-y-4">
      <JobOwnershipPanel
        jobId={jobId}
        jobTitle={job.title}
        primaryOwner={job.primary_owner ?? null}
        collaborators={job.collaborators ?? []}
      />
      <HiringManagerPicker
        jobId={jobId}
        clientId={job.client_id ?? null}
        value={job.hiring_manager_contact_id ?? null}
        valueName={job.hiring_manager_name ?? null}
        canEdit={canWritePipeline && canUpdateJob}
        onSaved={() =>
          queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] })
        }
      />
      <JobPriorityContext jobId={jobId} />
    </div>
  );

  return (
    // `xl:max-h` + `overflow-y-auto`: dok jest `sticky` na `xl`, a wariant
    // champion bywa wyższy niż okno — element sticky wyższy od viewportu nigdy
    // nie odsłania swojego dołu (główna akcja byłaby nieosiągalna). Ten sam
    // wzorzec co `PipelineCandidateDock` i `InterviewDecisionDock`.
    <div className="flex flex-col rounded-xl border border-border bg-card xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto">
      {/* ── nagłówek doku (makieta: `.dhd`) ───────────────────────────────── */}
      <div className="space-y-2.5 border-b border-border px-4 pb-0 pt-3">
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {variant === "champion" ? (
            <span className="min-w-0 truncate">Zlecenie · gotowość do searchu</span>
          ) : listNav ? (
            <div className="flex items-center gap-1" data-testid="dock-list-nav">
              <button
                type="button"
                onClick={listNav.onPrev}
                disabled={listNav.index <= 1}
                aria-label="Poprzednia rekrutacja"
                className="rounded p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-40"
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
                className="rounded p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-40"
              >
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          ) : (
            <span className="min-w-0 truncate">Gotowość zlecenia</span>
          )}
          <button
            type="button"
            onClick={copyJobLink}
            aria-label="Kopiuj link do rekrutacji"
            title="Kopiuj link do rekrutacji"
            className="ml-auto rounded p-0.5 text-muted-foreground hover:text-foreground"
          >
            <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>

        {/* Identyfikacja zlecenia tylko na liście — na kroku 02 tytuł stoi
            w nagłówku strony tuż nad dokiem i powtarzanie go zabierałoby
            miejsce warunkom, po które ten dok istnieje. */}
        {variant === "list" ? (
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Target className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0 flex-1">
              <Link
                href={`/jobs/${jobId}`}
                className="block truncate text-sm font-semibold text-foreground hover:text-primary hover:underline"
              >
                {job.title}
              </Link>
              {subtitle && (
                <div className="truncate text-xs text-muted-foreground">
                  {subtitle}
                </div>
              )}
            </div>
          </div>
        ) : null}

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
                    właściciela, Championa, budżet, skille i HM — zbiór ROZŁĄCZNY
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
              {variant === "champion" ? (
                <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">
                  Search bez weryfikacji i briefingu to search po requeście
                  klienta, nie po tym, czego klient naprawdę potrzebuje.
                </p>
              ) : null}
            </div>

            <ReadinessGateBlock query={readinessQuery} canSeeGate={canSeeGate} />

            <div className="space-y-1.5">
              {variant === "champion"
                ? (championBlocked ?? (
                    <ChampionVerificationChecklist
                      jobId={jobId}
                      verification={championProfile?.verification}
                      briefing={championProfile?.briefing}
                      canEdit={canEditChampion}
                      variant="rows"
                    />
                  ))
                : null}
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

            {variant === "list" ? (
              <PipelineSummary jobId={jobId} stageBreakdown={stageBreakdown} />
            ) : null}

            {/* Ten sam komponent i ta sama mutacja co pełna zakładka
                „Wyszukiwania (AI)" — tylko trzy pierwsze propozycje. Zapytania
                o liczniki dzielą klucze z zakładką, więc podgląd nie kosztuje
                ani jednego dodatkowego żądania. */}
            {variant === "champion"
              ? (championBlocked ?? (
                  <ChampionRecommendedSearches
                    jobId={jobId}
                    searches={(championProfile?.recommended_searches ?? []).slice(0, 3)}
                    canEdit={canEditChampion}
                  />
                ))
              : null}

            {variant === "champion" ? (
              <JobPriorityContext jobId={jobId} variant="summary" />
            ) : null}

            <div className="grid grid-cols-2 gap-2 pt-1">
              {/* Krok 02: handoff jest GŁÓWNĄ akcją tego doku — dopiero po nim
                  rekruter dostaje dostęp i ranking się generuje. Ten sam warunek
                  widoczności, którego do tej pory używał `page.tsx` na zakładce
                  `champion` (`canWritePipeline && (isAdmin || DL)`). */}
              {variant === "champion" && canEditChampion && (
                <div className="col-span-2">
                  <JobHandoffButton jobId={jobId} />
                </div>
              )}
              {/* Goły <a> ze stylami `buttonVariants`, nie `<Button asChild>` —
                  `Button` dokłada slot na spinner, więc Radix `Slot` dostałby dwoje
                  dzieci (lustro `PrepInviteActions.tsx`). Nawigacja, nie mutacja —
                  zawsze aktywna, niezależnie od `canWritePipeline`. */}
              <Link
                href={`/jobs/${jobId}?tab=similar`}
                className={cn(
                  buttonVariants({ variant: "primary", size: "sm" }),
                  "col-span-2 w-full",
                )}
              >
                <Target className="h-3.5 w-3.5" aria-hidden="true" /> Otwórz warsztat
                (C2)
              </Link>
              {/* Makieta kroku 02 ma tu jeszcze „Wzór Word (SharePoint)"
                  i „Historia requestu" — pierwszego dok nie zna (link żyje
                  w `help_materials`, poza danymi tego komponentu), a drugie
                  jest ZAKŁADKĄ tego samego doku: przycisk obok zakładki o tej
                  samej nazwie to dwa wejścia do jednego miejsca.
                  „Dodaj kandydata" i „Edytuj rekrutację" zostają w OBU
                  wariantach — makieta ich na kroku 02 nie rysuje, ale dziś tam
                  są i ich zniknięcie byłoby utratą funkcji, nie porządkowaniem. */}
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
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="w-full justify-start"
                    onClick={() => setShowEdit(true)}
                  >
                    <PencilLine className="h-3.5 w-3.5" /> Edytuj rekrutację
                  </Button>
                </>
              )}
            </div>
          </>
        )}

        {dockTab === "pipeline" && (
          <PipelineTab jobId={jobId} stageBreakdown={stageBreakdown} />
        )}

        {dockTab === "team" && teamTab}

        {dockTab === "searches" && variant === "champion" && (
          <>
            {championBlocked ?? (
              <ChampionRecommendedSearches
                jobId={jobId}
                searches={championProfile?.recommended_searches}
                canEdit={canEditChampion}
              />
            )}
          </>
        )}

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
      {variant === "list" && job.updated_at ? (
        <div className="mt-auto flex items-center gap-1.5 border-t border-border bg-muted/20 px-4 py-2 text-[11px] text-muted-foreground">
          <Clock className="h-3 w-3 shrink-0" aria-hidden="true" />
          Ostatnia zmiana: {formatRelativeTime(job.updated_at)}
        </div>
      ) : null}
      {/* Makieta pisze tu „niezweryfikowany od 21 dni" — profil Championa nie
          niesie daty utworzenia, a `verified_at` istnieje dopiero PO
          weryfikacji, więc liczby dni nie ma z czego policzyć. Zdanie zostaje
          bez niej: ostrzeżenie jest prawdziwe, wymyślony licznik nie byłby. */}
      {variant === "champion" && championQuery.isSuccess && !championVerified ? (
        <div className="mt-auto border-t border-border bg-warning-muted px-4 py-2 text-[11px] text-warning-muted-foreground">
          Champion niezweryfikowany — rekruterzy widzą to na profilu kandydata
          jako ostrzeżenie.
        </div>
      ) : null}

      {canWritePipeline && showAddCandidates && (
        <AddCandidatesQuickModal
          open={showAddCandidates}
          onClose={() => setShowAddCandidates(false)}
          jobId={jobId}
          jobTitle={job.title}
        />
      )}
      {canWritePipeline && showEdit && (
        <EditJobModal
          job={job}
          onClose={() => setShowEdit(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
            queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
            setShowEdit(false);
          }}
        />
      )}
    </div>
  );
}
