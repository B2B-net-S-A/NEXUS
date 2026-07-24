"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BriefcaseBusiness,
  Calendar,
  ChevronLeft,
  ChevronRight,
  FileText,
  Mail,
  MapPin,
  Maximize2,
  MessageSquare,
  Phone,
  Sparkles,
  UserPlus,
  X,
} from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { DEFAULT_FILTERS, encodeNavContext } from "@/lib/url-filters";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import CallButton from "@/components/calls/CallButton";
import {
  AtOurClientBanner,
  type EmploymentInfo,
} from "@/components/v2/CandidateHighlights";
import { CompetenceCategoryBadge } from "@/components/v2/CompetenceCategoryBadge";
import { DeferUntilVisible } from "@/components/v2/DeferUntilVisible";
import {
  type CandidateDocument,
  downloadDocumentBlob,
  FilePreviewModal,
} from "@/components/v2/files/FilePreviewModal";
import { MarkEmployedAction } from "@/components/v2/MarkEmployedAction";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { RiskBadge } from "@/components/v2/RiskBadge";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import { useCandidateNavigation } from "@/hooks/useCandidateNavigation";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { CandidateDetailNavigation } from "@/components/v2/pages/CandidateDetailV2";
import { getCandidateInitials } from "@/components/v2/pages/candidate-list-helpers";
import { withCandidateProfileView } from "@/components/v2/pages/candidate-profile-navigation";

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
  skills?: Array<string | { name?: string | null }> | null;
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
  source: {
    added_by_name: string;
    acquisition_source: string | null;
    imported_via: string | null;
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
  cv_highlights: {
    bullets: string[];
  };
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
}

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  return (error as { response?: { status?: number } }).response?.status ?? null;
}

function candidateSkills(candidate: QuickViewCandidate): string[] {
  if (!Array.isArray(candidate.skills)) return [];
  const names = candidate.skills
    .map((skill) =>
      typeof skill === "string" ? skill.trim() : String(skill.name ?? "").trim(),
    )
    .filter(Boolean);
  return Array.from(new Set(names)).slice(0, 8);
}

function availabilityLabel(
  availability: CandidateQuickViewData["availability"],
): string {
  const statusLabels: Record<string, string> = {
    actively_looking: "Dostępny aktywnie",
    open_to_offers: "Otwarty na oferty",
    not_looking: "Niedostępny",
    available: "Dostępny",
    unknown: "Nieznana",
  };
  const status = availability.status
    ? (statusLabels[availability.status] ?? availability.status)
    : null;
  const details: string[] = [];
  if (availability.available_from) {
    details.push(`od ${formatDate(availability.available_from)}`);
  } else if (
    availability.notice_period != null &&
    availability.notice_period_unit
  ) {
    const units = {
      days: "dni",
      weeks: "tyg.",
      months: "mies.",
    } as const;
    details.push(
      `${availability.notice_period} ${units[availability.notice_period_unit]}`,
    );
  }
  return [status, ...details].filter(Boolean).join(" · ") || "Brak danych";
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

function ContactItem({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        <span>{label}</span>
      </div>
      <div className="max-w-full overflow-x-auto whitespace-nowrap text-sm font-medium text-foreground">
        {children}
      </div>
    </div>
  );
}

function QuickNotes({
  candidateId,
  notes,
}: {
  candidateId: number;
  notes: CandidateQuickViewData["recent_notes"];
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [composerOpen, setComposerOpen] = React.useState(false);
  const [note, setNote] = React.useState("");

  const addNote = useMutation({
    mutationFn: () =>
      api.post("/api/notes", {
        candidate_id: candidateId,
        content: note.trim(),
        note_type: "general",
      }),
    onSuccess: () => {
      setNote("");
      setComposerOpen(false);
      invalidateCandidateMutation(queryClient, candidateId, "note");
      void queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.quickView(candidateId),
      });
      showSuccess("Notatka dodana");
    },
    onError: (error) =>
      showError(extractErrorMsg(error) || "Nie udało się dodać notatki"),
  });

  return (
    <section aria-labelledby="quick-notes-heading" className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3
          id="quick-notes-heading"
          className="text-sm font-semibold text-foreground"
        >
          Notatki
        </h3>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setComposerOpen((open) => !open)}
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Dodaj notatkę
        </Button>
      </div>

      {composerOpen ? (
        <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            placeholder="Krótka notatka o kandydacie…"
            aria-label="Treść notatki"
          />
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setComposerOpen(false)}
            >
              Anuluj
            </Button>
            <Button
              size="sm"
              onClick={() => addNote.mutate()}
              loading={addNote.isPending}
              disabled={!note.trim()}
            >
              Zapisz
            </Button>
          </div>
        </div>
      ) : null}

      {notes.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-5 text-center text-sm text-muted-foreground">
          Brak notatek.
        </p>
      ) : (
        <ol className="divide-y divide-border rounded-lg border border-border">
          {notes.map((item) => (
            <li key={item.id} className="flex gap-3 px-3 py-3">
              <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="whitespace-pre-wrap text-sm text-foreground">
                  {item.content}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.author_name || "System / import"}
                  {" · "}
                  {formatRelativeTime(item.created_at)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function CandidateQuickView({
  candidateId,
  onClose,
  navigation,
  onOpenFullProfile,
}: CandidateQuickViewProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [assignOpen, setAssignOpen] = React.useState(false);
  const [previewDocumentId, setPreviewDocumentId] = React.useState<
    number | null
  >(null);

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
  const documentsQuery = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.cvDocuments(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/documents?kind=cv`, { signal })
        .then((response) => response.data),
    enabled:
      Number.isFinite(candidateId) &&
      candidateId > 0 &&
      quickViewQuery.data?.capabilities.can_view_documents === true,
    staleTime: 30_000,
  });

  const quickView = quickViewQuery.data;
  const candidate = quickView?.candidate;
  const cvDocuments = Array.isArray(documentsQuery.data)
    ? documentsQuery.data
    : [];
  const primaryCv =
    cvDocuments.find((document) => document.is_primary) ?? cvDocuments[0] ?? null;

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
  const skills = candidate ? candidateSkills(candidate) : [];
  const canOpenCv =
    Boolean(quickView?.capabilities.can_view_documents) &&
    Boolean(primaryCv) &&
    !documentsQuery.isPending;
  const cvButtonTitle =
    quickView?.capabilities.can_view_documents === false
      ? "Brak uprawnień do dokumentów"
      : documentsQuery.error
        ? "Nie udało się pobrać listy CV"
        : !primaryCv && !documentsQuery.isPending
          ? "Brak sklasyfikowanego CV"
          : undefined;

  const downloadDocument = React.useCallback(
    async (document: CandidateDocument) => {
      try {
        await downloadDocumentBlob(candidateId, document);
      } catch (error) {
        showError(extractErrorMsg(error) || "Nie udało się pobrać dokumentu");
      }
    },
    [candidateId, showError],
  );

  return (
    <div
      className="flex h-full min-h-0 flex-col bg-card"
      data-testid="candidate-quick-view"
    >
      <SheetTitle className="sr-only">{fullName}</SheetTitle>
      <SheetDescription className="sr-only">
        Szybki podgląd danych, rekrutacji i ostatnich notatek kandydata.
      </SheetDescription>

      <header className="sticky top-0 z-20 border-b border-border bg-card/95 px-3 py-2 backdrop-blur sm:px-5">
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
            <div className="h-52 animate-pulse rounded-xl bg-muted" />
            <div className="h-36 animate-pulse rounded-xl bg-muted/70" />
            <div className="h-48 animate-pulse rounded-xl bg-muted/50" />
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
          <div className="divide-y divide-border">
            <section className="space-y-4 px-4 py-5 sm:px-6">
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

              <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,24rem)]">
                <div className="min-w-0 space-y-4">
                  <div className="flex min-w-0 items-start gap-4">
                    <Avatar size="xl" className="shrink-0">
                      <AvatarFallback>
                        {getCandidateInitials(candidate) || "?"}
                      </AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <h2 className="max-w-full overflow-x-auto whitespace-nowrap pb-1 text-[clamp(1.35rem,3.6vw,2rem)] font-semibold tracking-tight text-foreground">
                        {fullName}
                      </h2>
                      <p className="text-sm text-muted-foreground">
                        {quickView.current_position.title ||
                          "Stanowisko nieuzupełnione"}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
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
                    {riskQuery.data ? (
                      <RiskBadge profile={riskQuery.data} />
                    ) : null}
                    <CompetenceCategoryBadge
                      categoryId={candidate.competence_category_id}
                      slug={candidate.competence_category}
                      size="sm"
                    />
                  </div>

                  <div className="grid gap-2 sm:grid-cols-2">
                    <ContactItem
                      icon={<Mail className="h-3.5 w-3.5" />}
                      label="E-mail"
                    >
                      {candidate.email ? (
                        <a
                          href={`mailto:${candidate.email}`}
                          className="hover:text-primary"
                        >
                          {candidate.email}
                        </a>
                      ) : (
                        "Brak danych"
                      )}
                    </ContactItem>
                    <ContactItem
                      icon={<Phone className="h-3.5 w-3.5" />}
                      label="Telefon"
                    >
                      {candidate.phone ? (
                        <CallButton
                          candidateId={candidateId}
                          phone={candidate.phone}
                          compact
                          className="whitespace-nowrap"
                        />
                      ) : (
                        "Brak danych"
                      )}
                    </ContactItem>
                    <ContactItem
                      icon={<MapPin className="h-3.5 w-3.5" />}
                      label="Lokalizacja"
                    >
                      {candidate.location || candidate.city || "Brak danych"}
                    </ContactItem>
                    <ContactItem
                      icon={<Calendar className="h-3.5 w-3.5" />}
                      label="Dostępność"
                    >
                      {availabilityLabel(quickView.availability)}
                    </ContactItem>
                  </div>
                </div>

                <div
                  className="grid grid-cols-2 gap-2 self-start"
                  aria-label="Akcje kandydata"
                >
                  <Button
                    className="h-auto min-h-20 justify-start whitespace-normal px-4 py-3 text-left"
                    onClick={() => setAssignOpen(true)}
                    disabled={!quickView.capabilities.can_assign}
                  >
                    <UserPlus className="h-5 w-5 shrink-0" />
                    Przypisz do rekrutacji
                  </Button>
                  {candidate.employment?.state === "employed_at_client" ? (
                    <Button
                      variant="outline"
                      disabled
                      className="h-auto min-h-20 justify-start whitespace-normal px-4 py-3 text-left"
                    >
                      <BriefcaseBusiness className="h-5 w-5 shrink-0" />
                      Oznaczono jako zatrudnionego
                    </Button>
                  ) : quickView.capabilities.can_mark_employed ? (
                    <MarkEmployedAction
                      candidateId={candidateId}
                      employment={candidate.employment}
                      variant="outline"
                      className="h-auto min-h-20 justify-start whitespace-normal px-4 py-3 text-left"
                    />
                  ) : (
                    <Button
                      variant="outline"
                      disabled
                      className="h-auto min-h-20 justify-start whitespace-normal px-4 py-3 text-left"
                    >
                      Oznacz jako zatrudnionego
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    className="h-auto min-h-20 justify-start whitespace-normal px-4 py-3 text-left"
                    onClick={() =>
                      primaryCv && setPreviewDocumentId(primaryCv.id)
                    }
                    disabled={!canOpenCv}
                    title={cvButtonTitle}
                  >
                    <FileText className="h-5 w-5 shrink-0" />
                    Otwórz CV
                  </Button>
                  <Button
                    variant="outline"
                    className="h-auto min-h-20 justify-start whitespace-normal px-4 py-3 text-left"
                    onClick={() => openFullProfile("summary")}
                    disabled={!quickView.capabilities.can_open_full_profile}
                  >
                    <Maximize2 className="h-5 w-5 shrink-0" />
                    Pełny profil
                  </Button>
                </div>
              </div>

              {riskQuery.error ? (
                <QuickSectionError
                  label="Ocena ryzyka jest niedostępna"
                  onRetry={() => riskQuery.refetch()}
                />
              ) : null}
              {documentsQuery.error ? (
                <QuickSectionError
                  label="Nie udało się pobrać listy CV"
                  onRetry={() => documentsQuery.refetch()}
                />
              ) : null}
            </section>

            <section className="grid gap-4 px-4 py-5 sm:px-6 lg:grid-cols-2">
              <article className="rounded-xl border border-border bg-card p-4">
                <h3 className="text-sm font-semibold text-foreground">Źródło</h3>
                <dl className="mt-3 space-y-3 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Dodał</dt>
                    <dd className="mt-0.5 font-medium text-foreground">
                      {quickView.source.added_by_name || "System / import"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      Pozyskano z
                    </dt>
                    <dd className="mt-0.5 font-medium text-foreground">
                      {quickView.source.acquisition_source || "Brak danych"}
                    </dd>
                  </div>
                  {quickView.source.imported_via ? (
                    <div>
                      <dt className="text-xs text-muted-foreground">
                        Zaimportowano przez
                      </dt>
                      <dd className="mt-0.5 font-medium text-foreground">
                        {quickView.source.imported_via}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </article>

              <article className="rounded-xl border border-border bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-foreground">
                    Pipeline
                  </h3>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openFullProfile("recruitments")}
                  >
                    Wszystkie
                  </Button>
                </div>
                {quickView.current_recruitments.length === 0 ? (
                  <p className="mt-3 rounded-lg border border-dashed border-border py-5 text-center text-sm text-muted-foreground">
                    Brak aktywnych rekrutacji.
                  </p>
                ) : (
                  <ul className="mt-2 divide-y divide-border">
                    {quickView.current_recruitments.slice(0, 3).map((item) => (
                      <li key={item.job_id} className="py-2.5 first:pt-1">
                        <p className="text-sm font-medium text-foreground">
                          {item.stage_name}
                          <span className="font-normal text-muted-foreground">
                            {" · "}
                            {item.job_title}
                            {item.client_name ? ` · ${item.client_name}` : ""}
                          </span>
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          Dodano {formatDate(item.moved_at)} przez{" "}
                          {item.moved_by_name || "System / import"}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            </section>

            <section className="space-y-4 px-4 py-5 sm:px-6">
              <div>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Podsumowanie AI
                </h3>
                {quickView.cv_highlights.bullets.length > 0 ? (
                  <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-6 text-muted-foreground">
                    {quickView.cv_highlights.bullets.slice(0, 4).map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-muted-foreground">
                    Brak wiarygodnych danych wyekstrahowanych z CV.
                  </p>
                )}
              </div>
              {skills.length > 0 ? (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-foreground">
                    Umiejętności
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {skills.map((skill) => (
                      <Badge key={skill} variant="soft" size="md">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            <div className="px-4 py-5 sm:px-6">
              <QuickNotes
                candidateId={candidateId}
                notes={quickView.recent_notes}
              />
            </div>

            <div className="px-4 py-5 sm:px-6">
              <DeferUntilVisible minHeight={180} rootMargin="200px">
                <SuggestedJobsWidget
                  candidateId={candidateId}
                  variant="compact"
                  maxItems={2}
                  hideWhenEmpty
                  onShowAll={() => openFullProfile("matching")}
                />
              </DeferUntilVisible>
            </div>
          </div>
        )}
      </div>

      {candidate ? (
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
      <FilePreviewModal
        documents={cvDocuments}
        initialDocumentId={previewDocumentId}
        candidateId={candidateId}
        onClose={() => setPreviewDocumentId(null)}
        onDownload={downloadDocument}
      />
    </div>
  );
}
