"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  Calendar,
  ChevronLeft,
  ChevronRight,
  FileText,
  Loader2,
  Mail,
  MapPin,
  Maximize2,
  MessageSquare,
  Sparkles,
  UserPlus,
  Wallet,
  X,
} from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import { DEFAULT_FILTERS, encodeNavContext } from "@/lib/url-filters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import CallButton from "@/components/calls/CallButton";
import { AtOurClientBanner } from "@/components/v2/CandidateHighlights";
import { MarkEmployedAction } from "@/components/v2/MarkEmployedAction";
import { DeferUntilVisible } from "@/components/v2/DeferUntilVisible";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { RiskBadge } from "@/components/v2/RiskBadge";
import { SuggestedJobsWidget } from "@/components/SuggestedJobsWidget";
import { useCandidateNavigation } from "@/hooks/useCandidateNavigation";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import {
  formatCandidateLocation,
  getCurrentTitle,
  getExperienceLabel,
} from "@/components/v2/pages/candidate-list-helpers";
import { getCandidateSummaryLine } from "@/components/v2/pages/candidate-profile-helpers";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { withCandidateProfileView } from "@/components/v2/pages/candidate-profile-navigation";
import { CandidateProfileHeader } from "@/components/v2/pages/CandidateProfileHeader";
import { KeyFacts } from "@/components/ds/KeyFacts";
import type { CandidateDetailNavigation } from "@/components/v2/pages/CandidateDetailV2";

type QuickViewDestination =
  | "summary"
  | "recruitments"
  | "activity"
  | "matching"
  | "documents";

export interface CandidateQuickViewProps {
  candidateId: number;
  onClose: () => void;
  /** The same filtered-list context previously consumed by CandidateDetailV2. */
  navigation?: CandidateDetailNavigation;
  /**
   * Called before leaving the drawer. The optional destination lets the host
   * open e.g. matching or files while preserving its own list context.
   */
  onOpenFullProfile?: (
    candidateId: number,
    destination?: QuickViewDestination,
  ) => void;
}

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  return (error as { response?: { status?: number } }).response?.status ?? null;
}

function candidateSkills(candidate: any): string[] {
  if (!Array.isArray(candidate?.skills)) return [];
  const names = (candidate.skills as unknown[])
    .map<string>((skill) =>
      typeof skill === "string"
        ? skill.trim()
        : skill && typeof skill === "object" && "name" in skill
          ? String((skill as { name?: unknown }).name ?? "").trim()
          : "",
    )
    .filter(Boolean);
  return Array.from(new Set(names)).slice(0, 6);
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

function QuickFacts({ candidate }: { candidate: any }) {
  const title = getCurrentTitle(candidate);
  const experience = getExperienceLabel(candidate.years_it_experience)?.label;
  const location = formatCandidateLocation(candidate.city ?? candidate.location);
  const salary =
    candidate.expected_salary != null
      ? `${Number(candidate.expected_salary).toLocaleString("pl-PL")} ${candidate.currency ?? "PLN"}`
      : candidate.salary_expectation != null
        ? `${Number(candidate.salary_expectation).toLocaleString("pl-PL")} ${candidate.salary_currency ?? "PLN"}`
        : null;
  const availability = candidate.available_from
    ? formatDate(candidate.available_from)
    : candidate.availability_status === "actively_looking"
      ? "Dostępny aktywnie"
      : candidate.availability_status === "open_to_offers"
        ? "Otwarty na oferty"
        : null;
  const source = candidate.created_by_name ?? candidate.source ?? null;

  const facts = [
    { id: "role", icon: BriefcaseBusiness, label: "Rola", value: title },
    { id: "experience", icon: Calendar, label: "Doświadczenie", value: experience },
    { id: "location", icon: MapPin, label: "Lokalizacja", value: location },
    { id: "salary", icon: Wallet, label: "Oczekiwania", value: salary },
    { id: "availability", icon: Calendar, label: "Dostępność", value: availability },
    { id: "source", icon: UserPlus, label: "Źródło / opiekun", value: source },
  ].filter((fact) => fact.value);

  if (facts.length === 0) return null;

  return (
    <KeyFacts
      facts={facts.slice(0, 6)}
      columns={2}
      density="compact"
      className="rounded-xl border border-border bg-muted/30 p-4"
    />
  );
}

function QuickActivitySection({ candidateId }: { candidateId: number }) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [composerOpen, setComposerOpen] = React.useState(false);
  const [note, setNote] = React.useState("");

  const timelineQuery = useQuery<{ timeline?: any[] } | any[]>({
    queryKey: candidateQueryKeys.timeline(candidateId, 3),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/timeline?limit=3`, { signal })
        .then((response) => response.data),
    staleTime: 30_000,
  });
  const timeline = Array.isArray(timelineQuery.data)
    ? timelineQuery.data
    : timelineQuery.data?.timeline ?? [];

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
      showSuccess("Notatka dodana");
    },
    onError: (error) =>
      showError(extractErrorMsg(error) || "Nie udało się dodać notatki"),
  });

  return (
    <section aria-labelledby="quick-activity-heading" className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 id="quick-activity-heading" className="text-sm font-semibold text-foreground">
          Ostatnia aktywność
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
            <Button size="sm" variant="ghost" onClick={() => setComposerOpen(false)}>
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

      {timelineQuery.error ? (
        <QuickSectionError
          label="Nie udało się pobrać aktywności"
          onRetry={() => timelineQuery.refetch()}
        />
      ) : timelineQuery.isPending ? (
        <div className="flex items-center justify-center gap-2 py-5 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Ładowanie aktywności…
        </div>
      ) : timeline.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border py-5 text-center text-sm text-muted-foreground">
          Brak zapisanej aktywności.
        </p>
      ) : (
        <ol className="divide-y divide-border rounded-lg border border-border">
          {timeline.slice(0, 3).map((item: any, index: number) => (
            <li key={`${item.type}-${item.id}-${index}`} className="flex gap-3 px-3 py-2.5">
              <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="line-clamp-1 text-sm text-foreground">
                  {item.content ?? item.description ?? item.title ?? "Aktywność kandydata"}
                </p>
                {item.timestamp ? (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {formatRelativeTime(item.timestamp)}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function QuickDocumentShortcut({
  candidateId,
  onOpen,
}: {
  candidateId: number;
  onOpen: () => void;
}) {
  const documentsQuery = useQuery<Array<{ id: number; filename: string; is_primary?: boolean }>>({
    queryKey: candidateQueryKeys.documents(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/documents`, { signal })
        .then((response) => response.data),
    staleTime: 30_000,
  });
  const primary =
    documentsQuery.data?.find((document) => document.is_primary) ??
    documentsQuery.data?.[0];

  if (documentsQuery.isPending) {
    return <div className="mt-3 h-10 animate-pulse rounded-lg bg-muted" />;
  }
  if (documentsQuery.error) {
    return (
      <div className="mt-3">
        <QuickSectionError
          label="Nie udało się pobrać skrótu do CV"
          onRetry={() => documentsQuery.refetch()}
        />
      </div>
    );
  }
  if (!primary) return null;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="mt-3 flex w-full items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 text-left transition-colors hover:bg-accent"
    >
      <FileText className="h-4 w-4 shrink-0 text-primary" />
      <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
        {primary.filename}
      </span>
      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
    </button>
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
  const [assignOpen, setAssignOpen] = React.useState(false);

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

  const candidateQuery = useQuery<any>({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}`, { signal })
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
  const historyQuery = useQuery<{ jobs?: any[] } | any[]>({
    queryKey: candidateQueryKeys.history(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/history`, { signal })
        .then((response) => response.data),
    enabled: Number.isFinite(candidateId) && candidateId > 0,
    staleTime: 30_000,
  });
  const aiProfileQuery = useQuery<any>({
    queryKey: candidateQueryKeys.aiProfile(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/ai-profile`, { signal })
        .then((response) => response.data),
    enabled: Number.isFinite(candidateId) && candidateId > 0,
    staleTime: 30_000,
  });

  const candidate = candidateQuery.data;
  const history = Array.isArray(historyQuery.data)
    ? historyQuery.data
    : historyQuery.data?.jobs ?? [];
  const activeRecruitments = history
    .filter(
      (job: any) =>
        !["rejected", "withdrawn", "hired"].includes(
          String(job.latest_stage ?? "").toLowerCase(),
        ),
    )
    .slice(0, 3);

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

  return (
    <div className="flex h-full min-h-0 flex-col bg-card" data-testid="candidate-quick-view">
      <SheetTitle className="sr-only">{fullName}</SheetTitle>
      <SheetDescription className="sr-only">
        Szybki podgląd danych, rekrutacji i ostatniej aktywności kandydata.
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
                <strong className="text-foreground">{navigationState.position}</strong>
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
            <span className="text-sm font-medium text-muted-foreground">Szybki podgląd</span>
          )}

          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => openFullProfile("summary")}
            >
              <Maximize2 className="h-4 w-4" />
              <span className="hidden sm:inline">Pełny profil</span>
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={onClose}
              aria-label="Zamknij szybki podgląd"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
        {navigationState.error ? (
          <div
            role="alert"
            className="mt-2 flex items-center justify-between gap-2 text-xs text-destructive"
          >
            <span>{navigationState.error}</span>
            <button type="button" onClick={navigationState.retry} className="font-medium underline">
              Ponów
            </button>
          </div>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {candidateQuery.isPending ? (
          <div className="space-y-4 p-5" aria-busy="true">
            <div className="h-28 animate-pulse rounded-xl bg-muted" />
            <div className="h-36 animate-pulse rounded-xl bg-muted/70" />
            <div className="h-48 animate-pulse rounded-xl bg-muted/50" />
          </div>
        ) : candidateQuery.error || !candidate ? (
          <div
            role="alert"
            className="flex min-h-80 flex-col items-center justify-center px-6 text-center"
          >
            <AlertTriangle className="mb-3 h-8 w-8 text-destructive" />
            <h2 className="text-base font-semibold text-foreground">
              {requestStatus(candidateQuery.error) === 403
                ? "Nie masz dostępu do tego profilu"
                : requestStatus(candidateQuery.error) === 404
                  ? "Nie znaleziono kandydata"
                  : "Nie udało się otworzyć podglądu"}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {requestStatus(candidateQuery.error) === 404
                ? "Kandydat mógł zostać usunięty."
                : "Sprawdź połączenie albo spróbuj ponownie."}
            </p>
            {![403, 404].includes(requestStatus(candidateQuery.error) ?? 0) ? (
              <Button className="mt-4" onClick={() => candidateQuery.refetch()}>
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
              {candidate.status === "blacklisted" || riskQuery.data?.level === "high" ? (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  {candidate.status === "blacklisted"
                    ? "Kandydat znajduje się na blacklist."
                    : "Kandydat ma wysokie ryzyko wycofania z procesu."}
                </div>
              ) : null}

              <CandidateProfileHeader
                candidate={candidate}
                headingLevel={2}
                density="compact"
                summary={getCandidateSummaryLine(candidate) ?? candidate.current_role}
                badges={
                  <>
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
                    {riskQuery.data ? <RiskBadge profile={riskQuery.data} /> : null}
                  </>
                }
                metadata={
                  <>
                    {candidate.email ? (
                      <a
                        href={`mailto:${candidate.email}`}
                        className="inline-flex min-w-0 items-center gap-1.5 text-foreground hover:text-primary"
                      >
                        <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="max-w-64 truncate">{candidate.email}</span>
                      </a>
                    ) : null}
                    {candidate.phone ? (
                      <CallButton candidateId={candidateId} phone={candidate.phone} compact />
                    ) : null}
                  </>
                }
                actions={
                  <>
                    <Button size="sm" onClick={() => setAssignOpen(true)}>
                      <UserPlus className="h-4 w-4" />
                      Przypisz do rekrutacji
                    </Button>
                    <MarkEmployedAction
                      candidateId={candidateId}
                      employment={candidate.employment}
                      size="sm"
                      variant="outline"
                    />
                    {candidate.cv_filename ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openFullProfile("documents")}
                      >
                        <FileText className="h-4 w-4" />
                        Otwórz CV
                      </Button>
                    ) : null}
                  </>
                }
              />

              {riskQuery.error ? (
                <QuickSectionError
                  label="Ocena ryzyka jest niedostępna"
                  onRetry={() => riskQuery.refetch()}
                />
              ) : null}
            </section>

            <section className="space-y-4 px-4 py-5 sm:px-6">
              <QuickFacts candidate={candidate} />
              {candidateSkills(candidate).length > 0 ? (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-foreground">Umiejętności</h3>
                  <div className="flex flex-wrap gap-2">
                    {candidateSkills(candidate).map((skill) => (
                      <Badge key={skill} variant="soft" size="md">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
              {aiProfileQuery.error ? (
                <QuickSectionError
                  label="Podsumowanie AI jest niedostępne"
                  onRetry={() => aiProfileQuery.refetch()}
                />
              ) : (aiProfileQuery.data?.summary ?? candidate.ai_summary) ? (
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Sparkles className="h-4 w-4 text-primary" />
                    Podsumowanie AI
                  </h3>
                  <p className="line-clamp-3 text-sm leading-6 text-muted-foreground">
                    {aiProfileQuery.data?.summary ?? candidate.ai_summary}
                  </p>
                </div>
              ) : null}
            </section>

            <section className="space-y-3 px-4 py-5 sm:px-6" aria-labelledby="quick-recruitments-heading">
              <div className="flex items-center justify-between gap-3">
                <h3 id="quick-recruitments-heading" className="text-sm font-semibold text-foreground">
                  Aktywne rekrutacje
                </h3>
                <Button size="sm" variant="ghost" onClick={() => openFullProfile("recruitments")}>
                  Wszystkie
                </Button>
              </div>
              {historyQuery.error ? (
                <QuickSectionError
                  label="Nie udało się pobrać rekrutacji"
                  onRetry={() => historyQuery.refetch()}
                />
              ) : historyQuery.isPending ? (
                <div className="flex items-center justify-center gap-2 py-5 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Ładowanie rekrutacji…
                </div>
              ) : activeRecruitments.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border py-5 text-center text-sm text-muted-foreground">
                  Brak aktywnych rekrutacji.
                </p>
              ) : (
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {activeRecruitments.map((job: any, index: number) => (
                    <li
                      key={job.job_id ?? job.id ?? index}
                      className="flex items-center justify-between gap-3 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">
                          {job.job_title ?? `Rekrutacja #${job.job_id ?? job.id}`}
                        </p>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">
                          {job.latest_stage ?? "Etap nieuzupełniony"}
                          {(job.last_moved_at ??
                          job.latest_stage_moved_at ??
                          job.stages?.[0]?.moved_at)
                            ? ` · ${formatRelativeTime(
                                job.last_moved_at ??
                                  job.latest_stage_moved_at ??
                                  job.stages?.[0]?.moved_at,
                              )}`
                            : ""}
                        </p>
                      </div>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <div className="px-4 py-5 sm:px-6">
              <DeferUntilVisible minHeight={180} rootMargin="200px">
                <>
                  <QuickActivitySection candidateId={candidateId} />
                  <QuickDocumentShortcut
                    candidateId={candidateId}
                    onOpen={() => openFullProfile("documents")}
                  />
                </>
              </DeferUntilVisible>
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

            <footer className="px-4 py-5 sm:px-6">
              <Button className="w-full" variant="outline" onClick={() => openFullProfile("summary")}>
                Otwórz pełny profil
                <ArrowRight className="h-4 w-4" />
              </Button>
            </footer>
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
          }}
        />
      ) : null}
    </div>
  );
}
