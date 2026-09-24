"use client";

/**
 * Profil kandydata — orkiestrator. Stan adresu, zapytania wspólne dla kilku
 * zakładek, nagłówek, cztery zakładki i modale akcji. Treść zakładek żyje
 * w `components/v2/candidate-profile/*` (dawniej jeden plik ~4,9 tys. linii).
 *
 * Zakładki (`?tab=`): `summary` „Profil”, `recruitments` „Rekrutacje”,
 * `activity` „Historia”, `documents` „Pliki i umowy”. Stare klucze
 * (`matching`, `emails`, `chat`, `umowa`…) mapuje
 * `candidate-profile-navigation.ts` — linki z powiadomień są zapisane w bazie.
 */

import * as React from "react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Calendar, Files, MessageSquare, User } from "lucide-react";

import api, { candidatesApi, extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { EditCandidateModal } from "@/components/AppShell";
import { canHardDeleteCandidate } from "@/lib/candidate-delete-access";
import { canMergeCandidates } from "@/lib/api/candidateMerge";
import { CandidateMergeDialog } from "@/components/v2/candidate-profile/CandidateMergeDialog";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { CVGeneratorV2 } from "@/components/v2/modals/CVGeneratorV2";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { PrepInviteModal } from "@/components/v2/modals/PrepInviteModal";
import ScheduleInterviewModal from "@/components/calendar/ScheduleInterviewModal";
import { AddToMarketplaceButton } from "@/components/marketplace/AddToMarketplaceButton";
import { AtOurClientBanner } from "@/components/v2/CandidateHighlights";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { usePresence } from "@/hooks/usePresence";
import { useAuthStore, hasRole } from "@/store/auth";
import type { CandidateRiskProfile } from "@/types/candidate-risk";
import {
  useCandidateNavigation,
  type CandidateLite,
} from "@/hooks/useCandidateNavigation";
import {
  DEFAULT_FILTERS,
  type CandidateFilters,
  decodeNavContext,
  decodeJobBackRef,
  decodeTalentRadarBackRef,
  encodeNavContext,
} from "@/lib/url-filters";
import { useTabsStore } from "@/store/tabs";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { useCandidateHistoryQuery } from "@/components/v2/pages/candidate-history-query";
import {
  parseCandidateNoteFocus,
  parseCandidateProfileView,
  parseCandidateRecruitmentFocus,
  withCandidateProfileView,
  type CandidateActivityView,
  type CandidateProfileView,
  type CandidateProfileViewInput,
} from "@/components/v2/pages/candidate-profile-navigation";
import { ContactOutcomeSheet } from "@/components/candidate-contact/ContactOutcomeSheet";
import {
  candidateContactApi,
  candidateContactQueryKeys,
  type CandidateContactCase,
} from "@/lib/candidate-contact";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { useCapability } from "@/hooks/useCapability";
import { useCloudTalkEnabled } from "@/hooks/useCloudTalkEnabled";
import {
  ProfileHeader,
  ProfileTopBar,
} from "@/components/v2/candidate-profile/ProfileHeader";
import { ProfileTab } from "@/components/v2/candidate-profile/ProfileTab";
import { RecruitmentsTab } from "@/components/v2/candidate-profile/RecruitmentsTab";
import { HistoryTab } from "@/components/v2/candidate-profile/HistoryTab";
import { FilesContractsTab } from "@/components/v2/candidate-profile/FilesContractsTab";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload kandydata i osi czasu jest luźno typowany */

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  const response = (error as { response?: { status?: number } }).response;
  return response?.status ?? null;
}

/**
 * Navigation context for prev/next candidate browsing inside the profile.
 * Provided by parent (`CandidatesListV2`) for embedded Sheet mode. Full-page
 * mode reads it from URL via `decodeNavContext` instead.
 */
export interface CandidateDetailNavigation {
  filters: CandidateFilters;
  /** Current 1-based position in the filtered list. */
  position: number;
  /** Items currently loaded by parent (so hook can avoid re-fetch). */
  pageItems: CandidateLite[];
  /** Total filtered count from parent. */
  total: number;
  /** Page number `pageItems` belongs to. */
  pageNumber: number;
  /** Page size used by parent's list query. */
  pageSize: number;
  /** Called when user navigates — parent updates which candidate is shown. */
  onNavigate: (next: { candidateId: number; position: number }) => void;
}

export interface CandidateDetailV2Props {
  /** When true, render without page frame (for side-sheet embedding). */
  embedded?: boolean;
  /** Optional override for route param. */
  candidateId?: number;
  /** Close handler for embedded mode. */
  onClose?: () => void;
  /** When provided, renders prev/next nav strip (embedded mode). */
  navigation?: CandidateDetailNavigation;
  /**
   * Ścieżka strony, na której profil jest wyrenderowany — do zapisu `?tab=`.
   * Domyślnie `/candidates/{id}`; harness `/preview/candidate-profile` podaje
   * własną, żeby przełączanie zakładek nie wychodziło z podglądu.
   */
  basePath?: string;
}

export function CandidateDetailV2({
  embedded,
  candidateId,
  onClose,
  navigation,
  basePath,
}: CandidateDetailV2Props = {}) {
  const routeParams = useParams();
  const router = useRouter();
  const id = candidateId ?? Number(routeParams?.id);
  const profilePath = basePath ?? `/candidates/${id}`;
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const openTab = useTabsStore((s) => s.openTab);

  // ── Kontekst z adresu (pełna strona) ──────────────────────────────────
  const searchParams = useSearchParams();
  const searchString = searchParams?.toString() ?? "";
  const urlNav = React.useMemo(
    () => (embedded ? null : decodeNavContext(new URLSearchParams(searchString))),
    [embedded, searchString],
  );
  // Wejście z pipeline'u (`?from=job&jobId=N`) — powrót do rekrutacji.
  const backJobId = React.useMemo(
    () => (embedded ? null : decodeJobBackRef(new URLSearchParams(searchString))),
    [embedded, searchString],
  );
  // Wejście z rekrutacji bez jawnego `focusJobId` rozwija tę rekrutację.
  const requestedFocusJobId = React.useMemo(
    () =>
      embedded
        ? null
        : (parseCandidateRecruitmentFocus(new URLSearchParams(searchString)) ??
          backJobId),
    [backJobId, embedded, searchString],
  );
  // `?from=talent-radar` — powrót do trybu „Z treści requestu”.
  const backToTalentRadar = React.useMemo(
    () =>
      embedded ? false : decodeTalentRadarBackRef(new URLSearchParams(searchString)),
    [embedded, searchString],
  );
  const openTabsList = useTabsStore((s) => s.tabs);
  const backJobTitle =
    backJobId != null
      ? (openTabsList.find((t) => t.type === "job" && t.entityId === backJobId)
          ?.title ?? null)
      : null;
  const focusedNoteId = React.useMemo(
    () => (embedded ? null : parseCandidateNoteFocus(new URLSearchParams(searchString))),
    [embedded, searchString],
  );

  // ── Zakładka i filtr z adresu ─────────────────────────────────────────
  const profileViewFromUrl = React.useMemo(
    () =>
      parseCandidateProfileView(new URLSearchParams(searchString), {
        fromJob: backJobId != null,
      }),
    [backJobId, searchString],
  );
  const [profileView, setProfileView] = useState<CandidateProfileView>(profileViewFromUrl);
  useEffect(() => {
    setProfileView((current) =>
      current.section === profileViewFromUrl.section &&
      current.activity === profileViewFromUrl.activity &&
      current.documents === profileViewFromUrl.documents &&
      current.recruitments === profileViewFromUrl.recruitments
        ? current
        : profileViewFromUrl,
    );
  }, [profileViewFromUrl]);

  const replaceProfileView = React.useCallback(
    (next: CandidateProfileViewInput) => {
      const params = withCandidateProfileView(new URLSearchParams(searchString), next);
      const parsed = parseCandidateProfileView(params);
      setProfileView({ ...parsed, isLegacy: false });
      if (embedded) return;
      router.replace(`${profilePath}?${params.toString()}`, { scroll: false });
    },
    [embedded, profilePath, router, searchString],
  );

  const goToSection = React.useCallback(
    (
      section: CandidateProfileView["section"],
      sub: Partial<Pick<CandidateProfileView, "activity" | "documents" | "recruitments">> = {},
    ) =>
      replaceProfileView({
        section,
        activity: sub.activity ?? "timeline",
        documents: sub.documents ?? "files",
        recruitments: sub.recruitments ?? "list",
      }),
    [replaceProfileView],
  );

  // „Dodaj notatkę”: Historia + fokus w jedynym kompozytorze. Link
  // `?tab=activity&activity=notes&compose=1` robi to samo; parametr znika
  // z adresu po odczycie, żeby odświeżenie strony nie kradło fokusu.
  const [composeNoteRequest, setComposeNoteRequest] = useState(0);
  const clearComposeNoteRequest = React.useCallback(() => setComposeNoteRequest(0), []);
  const openNoteComposer = React.useCallback(() => {
    goToSection("activity", { activity: "notes" });
    setComposeNoteRequest((value) => value + 1);
  }, [goToSection]);
  const composeParam = embedded ? null : searchParams?.get("compose");
  useEffect(() => {
    if (composeParam !== "1") return;
    setComposeNoteRequest((value) => value + 1);
    const params = new URLSearchParams(searchString);
    params.delete("compose");
    router.replace(`${profilePath}?${params.toString()}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composeParam]);

  // Stare linki (`?tab=matching`, `?tab=chat&msg=`…) zamieniamy raz na
  // kanoniczny adres z zachowaniem kontekstu (`msg`, `nav`, `from`, `jobId`).
  useEffect(() => {
    if (embedded) return;
    const needsCanonicalUrl =
      profileViewFromUrl.isLegacy ||
      (backJobId != null && !profileViewFromUrl.hasExplicitTab);
    if (!needsCanonicalUrl) return;
    const params = withCandidateProfileView(
      new URLSearchParams(searchString),
      profileViewFromUrl,
    );
    router.replace(`${profilePath}?${params.toString()}`, { scroll: false });
  }, [backJobId, embedded, profilePath, profileViewFromUrl, router, searchString]);

  // „Uzupełnij dane do umowy” (zakładka Umowy) → Profil, szczegóły, JDG.
  const [jdgFocusRequest, setJdgFocusRequest] = useState(0);
  const clearJdgFocusRequest = React.useCallback(() => setJdgFocusRequest(0), []);

  const activeTab = profileView.section;

  // ── Poprzedni/następny kandydat ───────────────────────────────────────
  const navContext: CandidateDetailNavigation | null = navigation ?? null;
  const navMode: "embedded" | "url" | "off" = navContext ? "embedded" : urlNav ? "url" : "off";
  // Pozycja w trybie URL trzymana lokalnie, żeby licznik zmieniał się od razu
  // po kliknięciu (useSearchParams bywa o render spóźnione).
  const [urlPosition, setUrlPosition] = useState<number>(urlNav?.position ?? 1);
  useEffect(() => {
    if (urlNav?.position && urlNav.position !== urlPosition) {
      setUrlPosition(urlNav.position);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlNav?.position]);

  const navOnNavigate = React.useCallback(
    (next: { candidateId: number; position: number }) => {
      if (navContext) {
        navContext.onNavigate(next);
        return;
      }
      if (urlNav) {
        setUrlPosition(next.position);
        let sp = encodeNavContext(urlNav.filters, next.position);
        sp = withCandidateProfileView(sp, profileView);
        const messageId = searchParams?.get("msg");
        if (messageId) sp.set("msg", messageId);
        router.push(`/candidates/${next.candidateId}?${sp.toString()}`);
        router.refresh();
      }
    },
    [navContext, profileView, searchParams, urlNav, router],
  );

  const candidateNav = useCandidateNavigation(
    navMode === "embedded" && navContext
      ? {
          mode: "embedded",
          enabled: true,
          filters: navContext.filters,
          position: navContext.position,
          pageItems: navContext.pageItems,
          total: navContext.total,
          pageNumber: navContext.pageNumber,
          pageSize: navContext.pageSize,
          onNavigate: navOnNavigate,
        }
      : navMode === "url" && urlNav
        ? {
            mode: "url",
            enabled: true,
            filters: urlNav.filters,
            position: urlPosition,
            onNavigate: navOnNavigate,
          }
        : {
            mode: "url",
            enabled: false,
            filters: DEFAULT_FILTERS,
            position: 1,
            onNavigate: () => {},
          },
  );
  const showNav = navMode !== "off";

  // ── Modale ────────────────────────────────────────────────────────────
  const [emailOpen, setEmailOpen] = useState(false);
  const [cvOpen, setCvOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  // Osobno od `scheduleOpen`: „Zaplanuj rozmowę” wysyła przez Graph, a prep
  // daje rekruterowi SZKIC do własnego Outlooka (żeby dołożył CV).
  const [prepInviteOpen, setPrepInviteOpen] = useState(false);
  const [contactOutcomeOpen, setContactOutcomeOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editingIdentity, setEditingIdentity] = useState(false);
  const [marketplaceOpen, setMarketplaceOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  // ── Uprawnienia ───────────────────────────────────────────────────────
  const currentUser = useAuthStore((s) => s.user);
  // Akcje zapisu = capability `candidate.write` (lustro CANDIDATE_WRITE_ROLES
  // + sekcja sourcing write + blokada impersonacji).
  const canWriteSourcing = useCapability("candidate.write");
  const cloudTalkEnabled = useCloudTalkEnabled({
    enabled: Boolean(currentUser) && canWriteSourcing,
  });
  const contactFeature = useCandidateContactFeature({
    queryEnabled: hasRole(
      currentUser,
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
    ),
  });
  const { viewers: presenceViewers, setEditing: setPresenceEditing } = usePresence(
    "candidate",
    Number.isFinite(Number(id)) ? Number(id) : null,
  );

  // ── Zapytania wspólne dla kilku zakładek ──────────────────────────────
  const candidateQuery = useQuery({
    queryKey: candidateQueryKeys.detail(id),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${id}`, { signal }).then((r) => r.data),
    enabled: !!id,
  });
  const { data: candidate, isLoading } = candidateQuery;
  const contactCaseQuery = useQuery<CandidateContactCase | null>({
    queryKey: candidateContactQueryKeys.candidate(Number(id)),
    queryFn: () => candidateContactApi.forCandidate(Number(id)),
    enabled: contactFeature.enabled && Number.isFinite(Number(id)) && Number(id) > 0,
    staleTime: 30_000,
    retry: false,
  });

  useEffect(() => {
    if (candidate && !embedded) {
      openTab("candidate", Number(id), `${candidate.name} ${candidate.lastname}`.trim());
    }
  }, [candidate, id, openTab, embedded]);

  // Przełączenie kandydata (prev/next w szufladzie) zamyka edycję tożsamości.
  useEffect(() => {
    setEditingIdentity(false);
  }, [id]);

  // Oś czasu (50): licznik „Historia”, „Ostatnia aktywność” i filtr „Wszystko”.
  const timelineQuery = useQuery<{ timeline?: any[] } | any[]>({
    queryKey: candidateQueryKeys.timeline(id, 50),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${id}/timeline?limit=50`, { signal }).then((r) => r.data),
    enabled: !!id,
    staleTime: 30_000,
  });
  const timeline: any[] = Array.isArray(timelineQuery.data)
    ? timelineQuery.data
    : (timelineQuery.data?.timeline ?? []);

  // Rekrutacje: licznik zakładki, karty, selektor rekrutacji w kompozytorze.
  const historyQuery = useCandidateHistoryQuery(id, !!id);
  const historyRaw = historyQuery.visibleData;
  const history = React.useMemo<any[]>(
    () => (Array.isArray(historyRaw) ? historyRaw : (historyRaw?.jobs ?? [])),
    [historyRaw],
  );

  // Pliki: licznik zakładki (ten sam klucz co lista plików — jedno pobranie).
  const documentsQuery = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.documents(id),
    queryFn: async () => {
      const res = await api.get<CandidateDocument[]>(`/api/candidates/${id}/documents`);
      return res.data;
    },
    enabled: !!id,
    staleTime: 30_000,
  });

  // Ryzyko rezygnacji — odznaka w nagłówku (recompute event-driven + TTL 24h).
  const riskQuery = useQuery<CandidateRiskProfile>({
    queryKey: candidateQueryKeys.risk(id),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${id}/risk`, { signal }).then((r) => r.data),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  });

  // Trwałe usunięcie profilu — wyłącznie admin (migracja 0224 odpina umowy,
  // endpoint sprząta Qdranta i pliki w object storage).
  const canDeleteCandidate = canWriteSourcing && canHardDeleteCandidate(currentUser);
  const canMerge = canWriteSourcing && canMergeCandidates(currentUser);
  const [mergeOpen, setMergeOpen] = useState(false);
  const deleteMut = useMutation({
    mutationFn: () => candidatesApi.delete(id),
    onSuccess: () => {
      showSuccess("Profil kandydata usunięty z systemu");
      queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
      setDeleteOpen(false);
      if (embedded) onClose?.();
      else router.push("/candidates");
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się usunąć profilu kandydata"),
  });

  if (isLoading) {
    return (
      <div className="mx-auto max-w-[1440px] space-y-4 py-8" aria-busy="true">
        <div className="h-32 animate-pulse rounded-xl border border-border bg-muted/50" />
        <div className="h-80 animate-pulse rounded-xl border border-border bg-muted/40" />
      </div>
    );
  }

  if (candidateQuery.error || !candidate) {
    const status = requestStatus(candidateQuery.error);
    const missing = status === 404 || !Number.isFinite(Number(id));
    const title =
      status === 403
        ? "Nie masz dostępu do tego profilu"
        : missing
          ? "Nie znaleziono kandydata"
          : "Nie udało się otworzyć profilu";
    const description =
      status === 403
        ? "Poproś administratora o dostęp do danych kandydata."
        : missing
          ? "Kandydat mógł zostać usunięty albo link jest nieaktualny."
          : "Sprawdź połączenie i spróbuj ponownie.";
    return (
      <div
        role="alert"
        className="mx-auto flex max-w-2xl flex-col items-center rounded-xl border border-border bg-card px-6 py-16 text-center"
      >
        <AlertTriangle className="mb-4 h-8 w-8 text-destructive" />
        <h1 className="text-lg font-semibold text-foreground">{title}</h1>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>
        <div className="mt-5 flex gap-2">
          {status !== 403 && status !== 404 ? (
            <Button variant="primary" className="min-h-11 min-w-11" onClick={() => candidateQuery.refetch()}>
              Spróbuj ponownie
            </Button>
          ) : null}
          {embedded && onClose ? (
            <Button variant="outline" className="min-h-11 min-w-11" onClick={onClose}>
              Zamknij
            </Button>
          ) : (
            <Button variant="outline" className="min-h-11 min-w-11" asChild>
              <Link href="/candidates">Wróć do kandydatów</Link>
            </Button>
          )}
        </div>
      </div>
    );
  }

  const candidateNumericId = Number(id);
  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const readOnly = !canWriteSourcing;

  // „Zaloguj wynik” — tylko właściciel sprawy kontaktu w kolejce.
  const contactCase = contactCaseQuery.data ?? null;
  const canLogContactOutcome =
    Boolean(candidate.phone) &&
    canWriteSourcing &&
    contactCase != null &&
    hasRole(currentUser, "talent_community_manager", "tac", "recruiter", "sourcer") &&
    contactCase.owner?.id === currentUser?.id &&
    ["queued", "callback_due"].includes(contactCase.status);

  const fileCount = documentsQuery.isSuccess ? (documentsQuery.data ?? []).length : undefined;
  const tabs = [
    { value: "summary", label: "Profil", icon: User },
    {
      value: "recruitments",
      label: "Rekrutacje",
      icon: Calendar,
      count: historyQuery.visibleData !== undefined ? history.length : undefined,
    },
    {
      value: "activity",
      label: "Historia",
      icon: MessageSquare,
      count: timelineQuery.isSuccess ? timeline.length : undefined,
    },
    { value: "documents", label: "Pliki i umowy", icon: Files, count: fileCount },
  ];

  const navProps = showNav
    ? {
        position: candidateNav.position,
        total: candidateNav.total,
        hasPrev: candidateNav.hasPrev,
        hasNext: candidateNav.hasNext,
        onPrev: candidateNav.goPrev,
        onNext: candidateNav.goNext,
        isLoading: candidateNav.isLoading,
        error: candidateNav.error,
        onRetry: candidateNav.retry,
        ...(embedded
          ? {
              onClose,
              onExpand: navContext
                ? () => {
                    let sp = encodeNavContext(navContext.filters, candidateNav.position);
                    sp = withCandidateProfileView(sp, profileView);
                    router.push(`/candidates/${id}?${sp.toString()}`);
                  }
                : undefined,
            }
          : {}),
      }
    : null;

  return (
    <div className={embedded ? "space-y-4" : "mx-auto max-w-[1440px] space-y-5"}>
      <ProfileTopBar
        embedded={Boolean(embedded)}
        nav={navProps}
        backJobId={backJobId}
        backJobTitle={backJobTitle}
        backToTalentRadar={backToTalentRadar}
        candidateId={candidateNumericId}
      />

      {candidate.employment ? <AtOurClientBanner employment={candidate.employment} /> : null}

      {riskQuery.error ? (
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          <span>Ocena ryzyka jest chwilowo niedostępna.</span>
          <button
            type="button"
            className="inline-flex min-h-11 min-w-11 items-center justify-center font-medium underline"
            onClick={() => riskQuery.refetch()}
          >
            Ponów
          </button>
        </div>
      ) : null}

      <ProfileHeader
        candidate={candidate}
        candidateId={candidateNumericId}
        canWrite={canWriteSourcing}
        canCall={cloudTalkEnabled}
        riskProfile={riskQuery.data ?? null}
        contactCase={contactCase}
        showContactStatus={contactFeature.enabled}
        onLogContactOutcome={canLogContactOutcome ? () => setContactOutcomeOpen(true) : undefined}
        viewers={presenceViewers}
        editingIdentity={editingIdentity}
        onCloseIdentityEditor={() => setEditingIdentity(false)}
        onClose={embedded && !showNav ? onClose : undefined}
        actions={{
          onAssign: () => setAssignOpen(true),
          onAddNote: openNoteComposer,
          onEmail: () => setEmailOpen(true),
          onScheduleInterview: () => setScheduleOpen(true),
          onPrepInvite: () => setPrepInviteOpen(true),
          onGenerateCv: () => setCvOpen(true),
          onEdit: () => setEditOpen(true),
          onMarketplace: () => setMarketplaceOpen(true),
          onEditIdentity: candidate.identity_sync ? () => setEditingIdentity(true) : undefined,
          onDelete: canDeleteCandidate ? () => setDeleteOpen(true) : undefined,
          onMerge: canMerge ? () => setMergeOpen(true) : undefined,
        }}
      />

      <Card variant="default" size="md" className="overflow-hidden p-0!" data-help="candidate.profile.tabs">
        <TabbedNav
          value={activeTab}
          onValueChange={(value) => goToSection(value as CandidateProfileView["section"])}
          ariaLabel="Sekcje profilu kandydata"
          overflow="scroll"
          listClassName="max-w-full justify-start px-4 pt-2 *:shrink-0"
          tabs={tabs}
        >
          {/* `@container`: zakładki układają kolumnę boczną po szerokości
              karty, nie okna — obok szyny i paska bocznego karta bywa wąska. */}
          <div className="@container p-4 sm:p-5">
            <TabsContent value="summary" className="mt-0">
              <ProfileTab
                candidate={candidate}
                readOnly={readOnly}
                embedded={embedded}
                recentActivity={{ items: timeline, isPending: timelineQuery.isPending }}
                onNavigate={({ section }) => goToSection(section)}
                onGenerateCv={canWriteSourcing ? () => setCvOpen(true) : undefined}
                jdgFocusRequest={jdgFocusRequest}
                onJdgFocusHandled={clearJdgFocusRequest}
              />
            </TabsContent>

            <TabsContent value="recruitments" className="mt-0">
              <RecruitmentsTab
                candidateId={candidateNumericId}
                candidateName={fullName}
                history={history}
                // Dane z innego zakresu widza są ukryte do końca pobrania —
                // wtedy „ładowanie”, nie „brak rekrutacji”.
                isPending={
                  historyQuery.isPending ||
                  (historyQuery.isFetching && historyQuery.visibleData === undefined)
                }
                error={historyQuery.error}
                refetch={() => void historyQuery.refetch()}
                refreshing={historyQuery.isRefreshing}
                focusedJobId={requestedFocusJobId}
                defaultJobId={backJobId}
                view={profileView.recruitments}
                readOnly={readOnly}
              />
            </TabsContent>

            <TabsContent value="activity" className="mt-0">
              <HistoryTab
                candidateId={candidateNumericId}
                candidate={candidate}
                activityView={profileView.activity}
                onActivityViewChange={(activity: CandidateActivityView) =>
                  goToSection("activity", { activity })
                }
                timeline={{
                  items: timeline,
                  isPending: timelineQuery.isPending,
                  error: timelineQuery.error,
                  refetch: () => void timelineQuery.refetch(),
                }}
                recruitments={history}
                defaultJobId={backJobId}
                readOnly={readOnly}
                canModerate={hasRole(currentUser, "admin")}
                currentUserId={currentUser?.id}
                viewers={presenceViewers}
                setPresenceEditing={setPresenceEditing}
                focusedNoteId={focusedNoteId}
                composeRequest={composeNoteRequest}
                onComposeHandled={clearComposeNoteRequest}
              />
            </TabsContent>

            <TabsContent value="documents" className="mt-0">
              <FilesContractsTab
                candidateId={candidateNumericId}
                candidateName={fullName}
                candidatePhone={candidate.phone ?? null}
                jdgComplete={Boolean(candidate.legal_name && candidate.nip)}
                focus={profileView.documents}
                onFillJdg={
                  canWriteSourcing
                    ? () => {
                        goToSection("summary");
                        setJdgFocusRequest((value) => value + 1);
                      }
                    : undefined
                }
              />
            </TabsContent>
          </div>
        </TabbedNav>
      </Card>

      {canWriteSourcing ? (
        <>
          <SendEmailV2
            open={emailOpen}
            onOpenChange={setEmailOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
            candidateEmail={candidate.email ?? ""}
          />
          <CVGeneratorV2
            open={cvOpen}
            onOpenChange={setCvOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
          />
          <QuickAssignV2
            open={assignOpen}
            onOpenChange={setAssignOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
            onAssigned={() => invalidateCandidateMutation(queryClient, id, "assignment")}
          />
          {editOpen ? (
            <EditCandidateModal
              candidate={candidate}
              onClose={() => setEditOpen(false)}
              onSuccess={() => {
                invalidateCandidateMutation(queryClient, id, "edit");
                setEditOpen(false);
              }}
            />
          ) : null}
          <ScheduleInterviewModal
            open={scheduleOpen}
            onOpenChange={setScheduleOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
            candidateEmail={candidate.email ?? null}
          />
          {/* `onToast` jest w praktyce wymagane: bez niego nieudane kopiowanie
              (brak HTTPS, odmowa uprawnień) byłoby na tym ekranie nieme. */}
          <PrepInviteModal
            open={prepInviteOpen}
            onOpenChange={setPrepInviteOpen}
            candidateName={fullName}
            onToast={(message, type) =>
              type === "error" ? showError(message) : showSuccess(message)
            }
          />
          {/* Modal targu sterowany z rodzica — nakładka przeżywa zamknięcie menu. */}
          <AddToMarketplaceButton
            candidateId={candidate.id}
            candidateName={fullName}
            hideTrigger
            open={marketplaceOpen}
            onOpenChange={setMarketplaceOpen}
          />
          <ContactOutcomeSheet
            contactCase={contactCase}
            open={contactOutcomeOpen}
            onOpenChange={setContactOutcomeOpen}
            onSaved={() => void contactCaseQuery.refetch()}
            onConflict={() => void contactCaseQuery.refetch()}
          />
        </>
      ) : null}
      {canMerge && candidate ? (
        <CandidateMergeDialog
          open={mergeOpen}
          onOpenChange={setMergeOpen}
          candidate={{
            id: candidateNumericId,
            name: candidate.name,
            lastname: candidate.lastname,
            email: candidate.email,
            phone: candidate.phone,
            linkedin: candidate.linkedin,
          }}
        />
      ) : null}
      {canDeleteCandidate ? (
        <ConfirmV2
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          variant="destructive"
          title="Trwale usunąć profil kandydata?"
          // Co zniknie ORAZ co zostanie: umowy i faktury przeżywają (odpięte,
          // migracja 0224), payloady integracji Traffit nie mają FK na kandydata.
          description={`${fullName} oraz powiązane dane rekrutacyjne (CV, notatki, historia procesu, oceny, komentarze) zostaną trwale usunięte z systemu. Umowy i faktury zostaną zachowane bez powiązania z osobą — retencja dokumentów księgowych nie zależy od obecności kandydata w bazie. Tej operacji nie można cofnąć.`}
          confirmLabel="Usuń trwale"
          cancelLabel="Anuluj"
          loading={deleteMut.isPending}
          onConfirm={() => deleteMut.mutate()}
        />
      ) : null}
    </div>
  );
}
