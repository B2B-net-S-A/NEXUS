"use client";

import { type ReactNode, useState } from "react";
import Link from "next/link";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
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
import { cn } from "@/lib/utils";
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
  funnelTotal,
} from "@/lib/job-pipeline-funnel";
import { EditJobModal } from "@/components/AppShell";
import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import { RECRUITMENT_TYPE_LABEL } from "@/lib/recruitment-type";
import { ChampionVerificationChecklist } from "@/components/ChampionVerificationChecklist";
import { ChampionRecommendedSearches } from "@/components/ChampionRecommendedSearches";
import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import { HiringManagerPicker } from "@/components/jobs/HiringManagerPicker";
import { JobPriorityContext } from "@/components/v2/priority-work";
import { JobHandoffButton } from "@/components/v2/jobs/JobHandoffButton";

export type JobReadinessDockVariant = "list" | "champion";

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
   * "champion" (krok 02 „Zlecenie i Champion", program „flow w języku C2",
   * PR 5/7): dokłada zakładki „Zespół i priorytet" / „Wyszukiwania (AI)" do
   * istniejącej „Gotowość" (weryfikacja dwustronna + briefing DL dołączają
   * tam) i `JobHandoffButton` jako główną akcję. Domyślnie "list" (krok 01,
   * zachowanie sprzed tej zmiany bit w bit — patrz testy „JobReadinessDock —
   * dane" wyżej w tym pliku).
   */
  variant?: JobReadinessDockVariant;
}

type ChampionDockTab = "readiness" | "team" | "searches";

const CHAMPION_DOCK_TABS: { value: ChampionDockTab; label: string }[] = [
  { value: "readiness", label: "Gotowość" },
  { value: "team", label: "Zespół i priorytet" },
  { value: "searches", label: "Wyszukiwania (AI)" },
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
  title: string;
  description: string;
  action?: ReactNode;
}

function ReadinessRow({ done, title, description, action }: Omit<ReadinessItem, "key">) {
  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <span
        className={cn(
          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
          done
            ? "bg-success-muted text-success-muted-foreground"
            : "bg-warning-muted text-warning-muted-foreground",
        )}
        aria-hidden="true"
      >
        {done ? <Check className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground">{description}</div>
      </div>
      {action ? <div className="shrink-0 pt-0.5">{action}</div> : null}
    </div>
  );
}

/**
 * Bramka oficjalna „Przekaż do searchu” (`GET /api/jobs/{id}/readiness`).
 *
 * Widoczna WYŁĄCZNIE dla admina/DL przypisanego do klienta tej rekrutacji
 * (`DeliveryLeadPlus` + zakres klient–DL w handlerze) — dla każdej innej roli
 * to zapytanie kończy się 403. To NIE jest błąd do ukrycia: pokazujemy
 * czytelną notatkę „kto to widzi", żeby recruiter nie myślał, że coś się nie
 * wczytało. Sekcja jest drugorzędna względem checklisty wyżej (tamta liczy się
 * z danych zlecenia widocznych dla każdej roli) — stąd lżejszy traktament niż
 * pełnoekranowy `QueryStateNotice`.
 */
function ReadinessGateBlock({
  query,
  canSeeGate,
}: {
  query: UseQueryResult<any, unknown>;
  /** Rola z `GATE_ROLES` — bez niej zapytanie nie jest wysyłane (patrz wyżej). */
  canSeeGate: boolean;
}) {
  if (!canSeeGate) {
    return (
      <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
        Bramka „Przekaż do searchu” — widoczna dla Delivery Lead / admina
        przypisanego do tego klienta.
      </p>
    );
  }
  if (query.isLoading) {
    return <Skeleton className="h-9 w-full rounded-md" />;
  }
  if (query.isError) {
    const status = httpStatusFromError(query.error);
    if (status === 403) {
      return (
        <p className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
          Bramka „Przekaż do searchu” — widoczna dla Delivery Lead / admina
          przypisanego do tego klienta.
        </p>
      );
    }
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
  return (
    <div
      className={cn(
        "rounded-md border px-2.5 py-2 text-[11px]",
        data.ready
          ? "border-success/20 bg-success-muted text-success-muted-foreground"
          : "border-warning/25 bg-warning-muted text-warning-muted-foreground",
      )}
    >
      <div className="font-medium">
        Bramka „Przekaż do searchu”: {data.ready ? "gotowa" : "zablokowana"}
      </div>
      {!data.ready && Array.isArray(data.blockers) && data.blockers.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {data.blockers.map((blocker: string) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

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
  const nonZero = groups.filter((g) => g.count > 0);
  return (
    <div className="space-y-1.5 border-t border-border pt-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold text-foreground">
          Pipeline · {countPl(total, "kandydat", "kandydatów", "kandydatów")}
        </h4>
        <Link
          href={`/jobs/${jobId}`}
          className="shrink-0 text-[11px] font-medium text-primary hover:underline"
        >
          Otwórz kanban
        </Link>
      </div>
      {nonZero.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Brak kandydatów w tym procesie.
        </p>
      ) : (
        <div className="space-y-1">
          {nonZero.map((g) => (
            <div key={g.key} className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{g.label}</span>
              <span className="font-medium tabular-nums text-foreground">
                {g.count}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function JobReadinessDock({
  jobId,
  stageBreakdown,
  canOpen = true,
  variant = "list",
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
  const [dockTab, setDockTab] = useState<ChampionDockTab>("readiness");

  // `retry: false` na obu: 403/404 są deterministyczne — ponowienie tylko
  // dubluje odmowy w logach.
  const jobQuery = useQuery({
    queryKey: ["job-readiness-dock", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then((r) => r.data),
    enabled: jobId != null && canOpen,
    retry: false,
  });

  const readinessQuery = useQuery({
    queryKey: ["job-readiness-dock-gate", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data),
    enabled: jobId != null && canOpen && canSeeGate,
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
      }
    | undefined;

  const claimMutation = useMutation({
    mutationFn: () => api.post(`/api/jobs/${jobId}/claim`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job-readiness-dock", jobId] });
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
    job.primary_owner == null &&
    !claimMutation.isSuccess;

  const items: ReadinessItem[] = [
    {
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
    },
    {
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
        <Link
          href={`/jobs/${jobId}?tab=champion`}
          className="text-xs font-medium text-primary hover:underline"
        >
          Otwórz
        </Link>
      ),
    },
    {
      key: "budget",
      done: job.has_budget_hourly === true,
      title: "Budżet kandydacki",
      description: job.has_budget_hourly
        ? job.rate_budget_hourly != null
          ? `do ${job.rate_budget_hourly} PLN/h`
          : "Ustawiony — ze stawki w Profilu Championa."
        : "Brak — dodaj budżet PLN/h do oferty lub stawkę w Profilu Championa.",
    },
    {
      key: "skills",
      done: must.length > 0,
      title: "Must / nice zsynchronizowane",
      description:
        must.length > 0
          ? `${must.length} must · ${nice.length} nice · zasilają C2 i filtry.`
          : "Brak — dodaj wymagania w Profilu Championa (sekcja Stack) lub w ofercie.",
    },
    {
      key: "hiring_manager",
      done: job.hiring_manager_name != null,
      title: "Hiring manager (klient)",
      description: job.hiring_manager_name
        ? job.hiring_manager_name
        : "nie przypisano — weto HM nie zadziała.",
      action: job.hiring_manager_name == null ? (
        <Link
          href={`/jobs/${jobId}`}
          className="text-xs font-medium text-primary hover:underline"
        >
          Przypisz
        </Link>
      ) : undefined,
    },
  ];
  const doneCount = items.filter((i) => i.done).length;
  const subtitle = [
    job.client_name,
    RECRUITMENT_TYPE_LABEL[job.recruitment_type as string] ?? job.recruitment_type,
    job.reference_number,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="space-y-4 rounded-xl border border-border bg-card p-4">
      <div className="flex items-start gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
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
            <div className="truncate text-xs text-muted-foreground">{subtitle}</div>
          )}
        </div>
      </div>

      <div>
        <div className="flex items-end gap-2">
          <span
            className={cn(
              "text-2xl font-bold tabular-nums",
              doneCount === items.length ? "text-success" : "text-warning",
            )}
          >
            {doneCount}
          </span>
          {/* „Kompletność", NIE „gotowość do searchu": ta checklista liczy
              właściciela, Championa, budżet, skille i HM — zbiór ROZŁĄCZNY
              z oficjalną bramką „Przekaż do searchu” (`job_readiness.py`:
              tytuł, klient, kontekst projektu, ≥2 pytania screeningowe).
              Werdykt bramki jest niżej, w `ReadinessGateBlock`; dwie liczby
              pod tą samą nazwą przeczyłyby sobie na jednej karcie. */}
          <span className="pb-0.5 text-xs text-muted-foreground">
            / {items.length} · kompletność zlecenia
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              "h-1.5 rounded-full transition-all",
              doneCount === items.length ? "bg-success" : "bg-warning",
            )}
            style={{ width: `${(doneCount / items.length) * 100}%` }}
          />
        </div>
      </div>

      {variant === "champion" && (
        <TabbedNav
          ariaLabel="Zakładki gotowości zlecenia"
          value={dockTab}
          onValueChange={(v) => setDockTab(v as ChampionDockTab)}
          tabs={CHAMPION_DOCK_TABS}
          overflow="wrap"
        />
      )}

      {(variant === "list" || dockTab === "readiness") && (
        <>
          <ReadinessGateBlock query={readinessQuery} canSeeGate={canSeeGate} />

          <div className="divide-y divide-border/60">
            {items.map((item) => (
              <ReadinessRow
                key={item.key}
                done={item.done}
                title={item.title}
                description={item.description}
                action={item.action}
              />
            ))}
          </div>

          <PipelineSummary jobId={jobId} stageBreakdown={stageBreakdown} />

          {variant === "champion" && (
            <div className="border-t border-border pt-3">
              <ChampionVerificationChecklist
                jobId={jobId}
                verification={championProfile?.verification}
                briefing={championProfile?.briefing}
                canEdit={canEditChampion}
              />
            </div>
          )}
        </>
      )}

      {variant === "champion" && dockTab === "team" && (
        <div className="space-y-4 border-t border-border pt-3">
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
              queryClient.invalidateQueries({ queryKey: ["job-readiness-dock", jobId] })
            }
          />
          <JobPriorityContext jobId={jobId} />
        </div>
      )}

      {variant === "champion" && dockTab === "searches" && (
        <div className="border-t border-border pt-3">
          <ChampionRecommendedSearches
            jobId={jobId}
            searches={championProfile?.recommended_searches}
            canEdit={canEditChampion}
          />
        </div>
      )}

      <div className="space-y-2 pt-1">
        {/* Krok 02: handoff jest GŁÓWNĄ akcją tego doku — dopiero po nim
            rekruter dostaje dostęp i ranking się generuje. Ten sam warunek
            widoczności, którego do tej pory używał `page.tsx` na zakładce
            `champion` (`canWritePipeline && (isAdmin || DL)`). */}
        {variant === "champion" && canEditChampion && (
          <JobHandoffButton jobId={jobId} />
        )}
        {/* Goły <a> ze stylami `buttonVariants`, nie `<Button asChild>` —
            `Button` dokłada slot na spinner, więc Radix `Slot` dostałby dwoje
            dzieci (lustro `PrepInviteActions.tsx`). Nawigacja, nie mutacja —
            zawsze aktywna, niezależnie od `canWritePipeline`. */}
        <Link
          href={`/jobs/${jobId}?tab=similar`}
          className={cn(buttonVariants({ variant: "primary", size: "sm" }), "w-full")}
        >
          <Target className="h-3.5 w-3.5" aria-hidden="true" /> Otwórz warsztat (C2)
        </Link>
        {canWritePipeline && (
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="flex-1"
              onClick={() => setShowAddCandidates(true)}
            >
              <UserPlus className="h-3.5 w-3.5" /> Dodaj kandydata
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="flex-1"
              onClick={() => setShowEdit(true)}
            >
              <PencilLine className="h-3.5 w-3.5" /> Edytuj rekrutację
            </Button>
          </div>
        )}
      </div>

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
            queryClient.invalidateQueries({ queryKey: ["job-readiness-dock", jobId] });
            queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
            setShowEdit(false);
          }}
        />
      )}
    </div>
  );
}
