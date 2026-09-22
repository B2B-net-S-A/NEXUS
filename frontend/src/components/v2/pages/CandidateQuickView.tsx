"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  Mail,
  Maximize2,
  MessageSquare,
  MoreHorizontal,
  Phone,
  UserPlus,
  X,
} from "lucide-react";

import api from "@/lib/api";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { DEFAULT_FILTERS, encodeNavContext } from "@/lib/url-filters";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SheetDescription, SheetTitle } from "@/components/ui/sheet";
import CallButton from "@/components/calls/CallButton";
import {
  AtOurClientBanner,
  type EmploymentInfo,
} from "@/components/v2/CandidateHighlights";
import { CompetenceCategoryBadge } from "@/components/v2/CompetenceCategoryBadge";
import { MarkEmployedAction } from "@/components/v2/MarkEmployedAction";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { RiskBadge } from "@/components/v2/RiskBadge";
import { useCandidateNavigation } from "@/hooks/useCandidateNavigation";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { CandidateDetailNavigation } from "@/components/v2/pages/CandidateDetailV2";
import { getCandidateInitials } from "@/components/v2/pages/candidate-list-helpers";
import { withCandidateProfileView } from "@/components/v2/pages/candidate-profile-navigation";
import { hasRole, useAuthStore } from "@/store/auth";
import { ContactOutcomeSheet } from "@/components/candidate-contact/ContactOutcomeSheet";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import {
  candidateContactApi,
  candidateContactQueryKeys,
  type CandidateContactCase,
  type CandidateContactSummary,
} from "@/lib/candidate-contact";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { useCloudTalkEnabled } from "@/hooks/useCloudTalkEnabled";
import { canMutateSection } from "@/lib/section-access";
import { rateCellText } from "@/components/v2/candidates/candidate-row-format";

type QuickViewDestination =
  | "summary"
  | "recruitments"
  | "activity"
  | "matching"
  | "documents";

type DatePrecision = "date" | "month" | "year" | "unknown";

interface QuickViewCandidate {
  id: number;
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
  phone?: string | null;
  city?: string | null;
  location?: string | null;
  status?: string | null;
  employment?: EmploymentInfo | null;
  competence_category_id?: number | null;
  competence_category?: string | null;
  contact_case?: CandidateContactSummary | null;
  expected_rate_hourly?: number | string | null;
  expected_rate_currency?: string | null;
}

interface CandidateQuickViewData {
  candidate: QuickViewCandidate;
  current_position: {
    title: string | null;
    started_at: string | null;
    precision: DatePrecision;
  };
  availability: {
    status: string | null;
    available_from: string | null;
    notice_period: number | null;
    notice_period_unit: "days" | "weeks" | "months" | null;
  };
  current_recruitments: Array<{
    job_id: number;
    job_title: string;
    client_name: string | null;
    stage_id: number;
    stage_name: string;
    moved_at: string;
    moved_by_name: string | null;
  }>;
  recent_notes: Array<{
    id: number;
    content: string;
    created_at: string;
    author_name: string | null;
  }>;
  cv_highlights?: {
    years_experience?: number | null;
  } | null;
  capabilities: {
    can_assign: boolean;
    can_mark_employed: boolean;
    can_view_documents: boolean;
    can_open_full_profile: boolean;
  };
}

export interface CandidateQuickViewProps {
  candidateId: number;
  onClose: () => void;
  /** The same filtered-list context previously consumed by CandidateDetailV2. */
  navigation?: CandidateDetailNavigation;
  onOpenFullProfile?: (
    candidateId: number,
    destination?: QuickViewDestination,
  ) => void;
  /**
   * Stawka z profilu, już sformatowana („160 zł/h") — z wiersza listy, bo
   * `quick-view` jej nie niesie. `null` = osoba nie ma stawki (pokazujemy
   * „brak"), `undefined` = nie wiemy (np. kandydat spoza bieżącej strony).
   */
  rateLookup?: (candidateId: number) => string | null | undefined;
}

/** Let a Radix menu close (and return focus) before the next layer opens. */
function deferMenuAction(action: () => void) {
  window.setTimeout(action, 0);
}

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  return (error as { response?: { status?: number } }).response?.status ?? null;
}

function availabilityLabel(
  availability: CandidateQuickViewData["availability"],
): string | null {
  const statusLabels: Record<string, string> = {
    actively_looking: "Szuka aktywnie",
    open_to_offers: "Otwarty na oferty",
    not_looking: "Nie szuka",
    available: "Dostępny",
  };
  const status = availability.status ? (statusLabels[availability.status] ?? null) : null;
  if (availability.available_from) return `od ${formatDate(availability.available_from)}`;
  if (availability.notice_period != null && availability.notice_period_unit) {
    const units = { days: "dni", weeks: "tyg.", months: "mies." } as const;
    const notice = `wypowiedzenie ${availability.notice_period} ${units[availability.notice_period_unit]}`;
    return status ? `${status} · ${notice}` : notice;
  }
  return status;
}

function yearsLabel(years: number | null | undefined): string | null {
  if (years == null || !Number.isFinite(years) || years <= 0) return null;
  if (years === 1) return "1 rok";
  const lastDigit = years % 10;
  const lastTwo = years % 100;
  const few = lastDigit >= 2 && lastDigit <= 4 && !(lastTwo >= 12 && lastTwo <= 14);
  return `${years} ${few ? "lata" : "lat"}`;
}

function QuickSectionError({
  label,
  onRetry,
}: {
  label: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive"
    >
      <span>{label}</span>
      <button type="button" onClick={onRetry} className="font-medium underline">
        Ponów
      </button>
    </div>
  );
}

/** Kafel faktu — „brak" wyszarzony, żeby pustka nie udawała wartości. */
function FactTile({ label, value }: { label: string; value: React.ReactNode }) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="min-w-0 rounded-lg border border-border bg-muted/30 px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={
          missing
            ? "mt-0.5 text-sm text-muted-foreground"
            : "mt-0.5 truncate text-sm font-medium text-foreground"
        }
      >
        {missing ? "brak" : value}
      </dd>
    </div>
  );
}

/**
 * Szybki podgląd kandydata z listy (makieta „Podgląd", 22.09.2026): kto to
 * jest, czy jest dostępny i za ile, jak się skontaktować, w jakich procesach
 * już jest i co ostatnio zanotowano. Dwie akcje: przypisać albo otworzyć
 * pełny profil — wszystko inne (notatki, CV, dopasowania) żyje w profilu.
 */
export function CandidateQuickView({
  candidateId,
  onClose,
  navigation,
  onOpenFullProfile,
  rateLookup,
}: CandidateQuickViewProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((state) => state.user);
  const isImpersonating = useAuthStore((state) => state.realUser !== null);
  const canWriteSourcing = canMutateSection(
    currentUser,
    "sourcing",
    isImpersonating,
  );
  const contactFeature = useCandidateContactFeature({
    queryEnabled: Boolean(currentUser),
  });
  const cloudTalkEnabled = useCloudTalkEnabled({
    enabled: Boolean(currentUser) && canWriteSourcing,
  });
  const [assignOpen, setAssignOpen] = React.useState(false);
  const [markEmployedOpen, setMarkEmployedOpen] = React.useState(false);
  const [contactOutcomeOpen, setContactOutcomeOpen] = React.useState(false);

  const navigationState = useCandidateNavigation(
    navigation
      ? {
          mode: "embedded",
          enabled: true,
          filters: navigation.filters,
          position: navigation.position,
          pageItems: navigation.pageItems,
          total: navigation.total,
          pageNumber: navigation.pageNumber,
          pageSize: navigation.pageSize,
          onNavigate: navigation.onNavigate,
        }
      : {
          mode: "url",
          enabled: false,
          filters: DEFAULT_FILTERS,
          position: 1,
          onNavigate: () => undefined,
        },
  );

  const quickViewQuery = useQuery<CandidateQuickViewData>({
    queryKey: candidateQueryKeys.quickView(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/quick-view`, { signal })
        .then((response) => response.data),
    enabled: Number.isFinite(candidateId) && candidateId > 0,
  });
  const riskQuery = useQuery<CandidateRiskProfile>({
    queryKey: candidateQueryKeys.risk(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/risk`, { signal })
        .then((response) => response.data),
    enabled: Number.isFinite(candidateId) && candidateId > 0,
    staleTime: 5 * 60_000,
  });

  const quickView = quickViewQuery.data;
  const candidate = quickView?.candidate;
  const canOwnContact =
    canWriteSourcing &&
    contactFeature.enabled &&
    Boolean(candidate?.phone) &&
    Boolean(candidate?.contact_case) &&
    hasRole(
      currentUser,
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
    ) &&
    candidate?.contact_case?.owner?.id === currentUser?.id &&
    ["queued", "callback_due"].includes(
      candidate?.contact_case?.status ?? "",
    );
  const fullContactCaseQuery = useQuery<CandidateContactCase | null>({
    queryKey: candidateContactQueryKeys.candidate(candidateId),
    queryFn: () => candidateContactApi.forCandidate(candidateId),
    enabled: canOwnContact,
    staleTime: 30_000,
    retry: false,
  });

  const openFullProfile = React.useCallback(
    (destination: QuickViewDestination = "summary") => {
      if (onOpenFullProfile) {
        onOpenFullProfile(candidateId, destination);
        return;
      }

      let params = navigation
        ? encodeNavContext(navigation.filters, navigationState.position)
        : new URLSearchParams();
      params = withCandidateProfileView(params, {
        section: destination,
        activity: "timeline",
        documents: "files",
      });
      onClose();
      router.push(`/candidates/${candidateId}?${params.toString()}`);
    },
    [
      candidateId,
      navigation,
      navigationState.position,
      onClose,
      onOpenFullProfile,
      router,
    ],
  );

  const fullName = candidate
    ? `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim()
    : "Profil kandydata";
  // Stawka z odpowiedzi podglądu; wiersz listy tylko do czasu jej wczytania.
  const rate = (candidate ? rateCellText(candidate) : null) ?? rateLookup?.(candidateId);

  const isEmployedAtClient =
    candidate?.employment?.state === "employed_at_client";
  const canMarkEmployed =
    canWriteSourcing &&
    !isEmployedAtClient &&
    quickView?.capabilities.can_mark_employed === true;
  // „Oznacz jako zatrudnionego" nie ma innego miejsca w aplikacji — zostaje
  // w małym menu „⋯". Popover akcji kotwiczy się na tym opakowaniu (korzeń
  // menu Radixa nie renderuje własnego DOM-u).
  const moreActionsMenu = (
    <div className="flex">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Więcej akcji kandydata"
            title="Więcej akcji"
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          {isEmployedAtClient ? (
            <DropdownMenuItem disabled>
              <BriefcaseBusiness className="h-4 w-4" />
              Oznaczono jako zatrudnionego
            </DropdownMenuItem>
          ) : canMarkEmployed ? (
            <DropdownMenuItem
              onSelect={() =>
                deferMenuAction(() => setMarkEmployedOpen(true))
              }
            >
              <BriefcaseBusiness className="h-4 w-4" />
              Oznacz jako zatrudnionego
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem disabled>
              <BriefcaseBusiness className="h-4 w-4" />
              Oznacz jako zatrudnionego
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  const titleLine = [
    quickView?.current_position.title || null,
    yearsLabel(quickView?.cv_highlights?.years_experience),
  ]
    .filter(Boolean)
    .join(" · ");
  const latestNote = quickView?.recent_notes[0] ?? null;

  return (
    <div
      className="flex h-full min-h-0 flex-col bg-card"
      data-testid="candidate-quick-view"
    >
      <SheetTitle className="sr-only">{fullName}</SheetTitle>
      <SheetDescription className="sr-only">
        Szybki podgląd: dostępność, stawka, kontakt, procesy i ostatnia notatka.
      </SheetDescription>

      <header className="sticky top-0 z-20 border-b border-border bg-card/95 px-3 py-2 backdrop-blur-sm sm:px-5">
        <div className="flex items-center justify-between gap-3">
          {navigation ? (
            <div className="flex items-center gap-1">
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={navigationState.goPrev}
                disabled={!navigationState.hasPrev || navigationState.isLoading}
                aria-label="Poprzedni kandydat"
                aria-keyshortcuts="K"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="min-w-20 text-center text-xs tabular-nums text-muted-foreground">
                <strong className="text-foreground">
                  {navigationState.position}
                </strong>
                {" z "}
                {navigationState.total}
              </span>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={navigationState.goNext}
                disabled={!navigationState.hasNext || navigationState.isLoading}
                aria-label="Następny kandydat"
                aria-keyshortcuts="J"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <span className="text-sm font-medium text-muted-foreground">
              Szybki podgląd
            </span>
          )}

          <Button
            size="icon-sm"
            variant="ghost"
            onClick={onClose}
            aria-label="Zamknij szybki podgląd"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {navigationState.error ? (
          <div
            role="alert"
            className="mt-2 flex items-center justify-between gap-2 text-xs text-destructive"
          >
            <span>{navigationState.error}</span>
            <button
              type="button"
              onClick={navigationState.retry}
              className="font-medium underline"
            >
              Ponów
            </button>
          </div>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {quickViewQuery.isPending ? (
          <div className="space-y-4 p-5" aria-busy="true">
            <div className="h-24 animate-pulse rounded-xl bg-muted" />
            <div className="h-16 animate-pulse rounded-xl bg-muted/70" />
            <div className="h-32 animate-pulse rounded-xl bg-muted/50" />
          </div>
        ) : quickViewQuery.error || !quickView || !candidate ? (
          <div
            role="alert"
            className="flex min-h-80 flex-col items-center justify-center px-6 text-center"
          >
            <AlertTriangle className="mb-3 h-8 w-8 text-destructive" />
            <h2 className="text-base font-semibold text-foreground">
              {requestStatus(quickViewQuery.error) === 403
                ? "Nie masz dostępu do tego profilu"
                : requestStatus(quickViewQuery.error) === 404
                  ? "Nie znaleziono kandydata"
                  : "Nie udało się otworzyć podglądu"}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {requestStatus(quickViewQuery.error) === 404
                ? "Kandydat mógł zostać usunięty."
                : "Sprawdź połączenie albo spróbuj ponownie."}
            </p>
            {![403, 404].includes(
              requestStatus(quickViewQuery.error) ?? 0,
            ) ? (
              <Button
                className="mt-4"
                onClick={() => quickViewQuery.refetch()}
              >
                Spróbuj ponownie
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="space-y-5 px-4 py-5 sm:px-6">
            {candidate.employment ? (
              <AtOurClientBanner employment={candidate.employment} />
            ) : null}
            {candidate.status === "blacklisted" ||
            riskQuery.data?.level === "high" ? (
              <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {candidate.status === "blacklisted"
                  ? "Kandydat znajduje się na blacklist."
                  : "Kandydat ma wysokie ryzyko wycofania z procesu."}
              </div>
            ) : null}

            <section className="flex min-w-0 items-start gap-4">
              <Avatar size="lg" className="shrink-0">
                <AvatarFallback>
                  {getCandidateInitials(candidate) || "?"}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <h2 className="max-w-full overflow-x-auto whitespace-nowrap pb-0.5 text-xl font-semibold tracking-tight text-foreground">
                  {fullName}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {titleLine || "Stanowisko nieuzupełnione"}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {candidate.status ? (
                    <Badge
                      size="sm"
                      variant={
                        candidate.status === "blacklisted"
                          ? "danger"
                          : candidate.status === "passive"
                            ? "warning"
                            : "success"
                      }
                    >
                      {candidate.status === "active"
                        ? "Aktywny"
                        : candidate.status === "passive"
                          ? "Pasywny"
                          : "Zablokowany"}
                    </Badge>
                  ) : null}
                  <CompetenceCategoryBadge
                    categoryId={candidate.competence_category_id}
                    slug={candidate.competence_category}
                    size="sm"
                  />
                  {riskQuery.data && riskQuery.data.level === "high" ? (
                    <RiskBadge profile={riskQuery.data} />
                  ) : null}
                  {contactFeature.enabled ? (
                    <ContactStatusBadge
                      contactCase={candidate.contact_case}
                      size="sm"
                    />
                  ) : null}
                </div>
              </div>
            </section>

            <dl className="grid grid-cols-3 gap-2" aria-label="Najważniejsze fakty">
              <FactTile label="Dostępność" value={availabilityLabel(quickView.availability)} />
              <FactTile label="Stawka B2B" value={rate === undefined ? "—" : rate} />
              <FactTile label="Lokalizacja" value={candidate.location || candidate.city || null} />
            </dl>

            <section aria-label="Kontakt" className="space-y-1.5 text-sm">
              <div className="flex min-w-0 items-center gap-2">
                <Mail className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                {candidate.email ? (
                  <a
                    href={`mailto:${candidate.email}`}
                    className="truncate text-foreground hover:text-primary"
                  >
                    {candidate.email}
                  </a>
                ) : (
                  <span className="text-muted-foreground">brak e-maila</span>
                )}
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <Phone className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                {candidate.phone ? (
                  canWriteSourcing && cloudTalkEnabled ? (
                    <CallButton
                      candidateId={candidateId}
                      phone={candidate.phone}
                      compact
                      className="whitespace-nowrap"
                    />
                  ) : (
                    <span className="text-foreground">{candidate.phone}</span>
                  )
                ) : (
                  <span className="text-muted-foreground">brak telefonu</span>
                )}
              </div>
            </section>

            <section aria-labelledby="quick-recruitments-heading" className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <h3 id="quick-recruitments-heading" className="text-sm font-semibold text-foreground">
                  W procesie
                </h3>
                {quickView.current_recruitments.length > 0 ? (
                  <Button size="sm" variant="ghost" onClick={() => openFullProfile("recruitments")}>
                    Wszystkie
                  </Button>
                ) : null}
              </div>
              {quickView.current_recruitments.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nie jest w żadnym procesie.</p>
              ) : (
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {quickView.current_recruitments.slice(0, 3).map((item) => (
                    <li key={item.job_id} className="flex items-center justify-between gap-3 px-3 py-2">
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-foreground">
                          {item.job_title}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {item.client_name ?? "—"}
                        </span>
                      </span>
                      <Badge size="sm" variant="soft" className="shrink-0">
                        {item.stage_name}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="quick-note-heading" className="space-y-2">
              <h3 id="quick-note-heading" className="text-sm font-semibold text-foreground">
                Ostatnia notatka
              </h3>
              {latestNote ? (
                <figure className="flex gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
                  <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
                  <div className="min-w-0">
                    <blockquote className="line-clamp-4 whitespace-pre-wrap text-sm text-foreground">
                      {latestNote.content}
                    </blockquote>
                    <figcaption className="mt-1 text-xs text-muted-foreground">
                      {latestNote.author_name || "System / import"}
                      {" · "}
                      {formatRelativeTime(latestNote.created_at)}
                    </figcaption>
                  </div>
                </figure>
              ) : (
                <p className="text-sm text-muted-foreground">Brak notatek.</p>
              )}
            </section>

            {riskQuery.error ? (
              <QuickSectionError
                label="Ocena ryzyka jest niedostępna"
                onRetry={() => riskQuery.refetch()}
              />
            ) : null}
          </div>
        )}
      </div>

      {quickView && candidate ? (
        <footer
          className="flex flex-wrap items-center gap-2 border-t border-border bg-card px-4 py-3 sm:px-6"
          aria-label="Akcje kandydata"
        >
          {canWriteSourcing ? (
            <Button
              onClick={() => setAssignOpen(true)}
              disabled={!quickView.capabilities.can_assign}
            >
              <UserPlus className="h-4 w-4" />
              Przypisz do rekrutacji
            </Button>
          ) : null}
          <Button
            variant="outline"
            onClick={() => openFullProfile("summary")}
            disabled={!quickView.capabilities.can_open_full_profile}
          >
            <Maximize2 className="h-4 w-4" />
            Otwórz profil
          </Button>
          {canOwnContact && fullContactCaseQuery.data ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setContactOutcomeOpen(true)}
            >
              <Phone className="h-3.5 w-3.5" />
              Zaloguj wynik telefonu
            </Button>
          ) : null}
          {canWriteSourcing ? (
            <div className="ml-auto">
              {canMarkEmployed ? (
                <MarkEmployedAction
                  candidateId={candidateId}
                  employment={candidate.employment}
                  open={markEmployedOpen}
                  onOpenChange={setMarkEmployedOpen}
                  anchor={moreActionsMenu}
                />
              ) : (
                moreActionsMenu
              )}
            </div>
          ) : null}
        </footer>
      ) : null}

      {canWriteSourcing && candidate ? (
        <QuickAssignV2
          open={assignOpen}
          onOpenChange={setAssignOpen}
          candidateId={candidateId}
          candidateName={fullName}
          onAssigned={() => {
            invalidateCandidateMutation(queryClient, candidateId, "assignment");
            void queryClient.invalidateQueries({
              queryKey: candidateQueryKeys.quickView(candidateId),
            });
          }}
        />
      ) : null}
      {canWriteSourcing ? (
        <ContactOutcomeSheet
          contactCase={fullContactCaseQuery.data ?? null}
          open={contactOutcomeOpen}
          onOpenChange={setContactOutcomeOpen}
          onSaved={() =>
            void Promise.all([
              queryClient.invalidateQueries({
                queryKey: candidateQueryKeys.quickView(candidateId),
              }),
              fullContactCaseQuery.refetch(),
            ])
          }
          onConflict={() => void fullContactCaseQuery.refetch()}
        />
      ) : null}
    </div>
  );
}
