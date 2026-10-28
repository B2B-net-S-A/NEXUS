"use client";

/**
 * Profil kandydata — orkiestrator. Stan adresu, zapytania wspólne dla kilku
 * zakładek, karta osoby, pięć zakładek i modale akcji. Treść zakładek żyje
 * w `components/v2/candidate-profile/*` (dawniej jeden plik ~4,9 tys. linii).
 *
 * Układ od 13.10.2026 (decyzje E1–E6, makiety
 * https://claude.ai/artifact/LPzm9GQGPQCrnWjdtg2WG9): na górze pasek osoby na
 * całą szerokość (imię, pigułki, kontakt, akcje, menu „⋯”), pod nim od 1100 px
 * dwie kolumny — po lewej karta „Do propozycji” (ramka „Pracuje u nas”,
 * fakty po jednej linii, „do sprawdzenia z rozmowy”), po prawej zakładki.
 * Węziej karta stoi nad zakładkami.
 *
 * Zakładki (`?tab=`): `summary` „Przegląd”, `recruitments` „Rekrutacje”
 * (licznik = w toku), `screening` „Screening”, `activity` „Notatki”, `cv`
 * „CV”, `documents` „Dokumenty”. Stare klucze (`matching`, `emails`, `chat`,
 * `umowa`, `calls`…) mapuje `candidate-profile-navigation.ts` — linki
 * z powiadomień są zapisane w bazie.
 */

import * as React from "react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useUrlWriter } from "@/lib/url-selection";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  FileText,
  Files,
  ListChecks,
  MessageSquare,
  User,
  Users,
} from "lucide-react";

import api, {
  candidateFactsApi,
  candidatesApi,
  extractErrorMsg,
  type CandidateNotesFacts,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { EditCandidateModal } from "@/components/AppShell";
import { canHardDeleteCandidate } from "@/lib/candidate-delete-access";
import { humanNoteCount } from "@/lib/candidate-notes-view";
import { canMergeCandidates } from "@/lib/api/candidateMerge";
import { CandidateMergeDialog } from "@/components/v2/candidate-profile/CandidateMergeDialog";
import {
  BlacklistDialog,
  BlacklistNotice,
} from "@/components/v2/candidate-profile/BlacklistDialogs";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { CvGeneratorDialog } from "@/components/v2/cv-generator/CvGeneratorDialog";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { PrepInviteModal } from "@/components/v2/modals/PrepInviteModal";
import ScheduleInterviewModal from "@/components/calendar/ScheduleInterviewModal";
import { AtOurClientBanner } from "@/components/v2/CandidateHighlights";
import { CandidateProfileFactsBar } from "@/components/v2/pages/CandidateProfileFactsBar";
import { CandidateFollowupDialog } from "@/components/v2/followups/CandidateFollowupDialog";
import { useCandidateFollowup } from "@/lib/api/candidateFollowups";
import {
  FilePreviewModal,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
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
  decodeJobSearchBackRef,
  encodeNavContext,
  listBackHref,
  withJobSearchBackRef,
} from "@/lib/url-filters";
import { readJobSearchReturn, writeJobSearchReturn, writeListSearch } from "@/lib/search-memory";
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
import { useCapability } from "@/hooks/useCapability";
import {
  ProfilePersonBar,
  ProfileTopBar,
} from "@/components/v2/candidate-profile/ProfileHeader";
import { CvSkillsSection } from "@/components/v2/candidate-profile/CvSkillsSection";
import {
  latestCvDocument,
  splitRecruitments,
} from "@/components/v2/candidate-profile/profile-helpers";
import { ProfileTab } from "@/components/v2/candidate-profile/ProfileTab";
import { RecruitmentsTab } from "@/components/v2/candidate-profile/RecruitmentsTab";
import { HistoryTab } from "@/components/v2/candidate-profile/HistoryTab";
import { FilesContractsTab } from "@/components/v2/candidate-profile/FilesContractsTab";
import { SimilarCandidatesTab } from "@/components/v2/similar-candidates/SimilarCandidatesTab";
import { CandidateScreeningAnswersCard } from "@/components/v2/candidate-profile/CandidateScreeningAnswersCard";
import {
  ConflictsVetoesDialog,
  NotesFactsDialog,
  TagsPoolsDialog,
} from "@/components/v2/candidate-profile/ProfileMenuDialogs";
import { useNoAnswer } from "@/components/v2/candidate-profile/useNoteActions";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload kandydata i osi czasu jest luźno typowany */

/**
 * Ile ustaleń z notatek różni się od profilu (serwer liczy `can_apply`) —
 * linia „N do sprawdzenia z rozmowy” w karcie „Do propozycji”.
 */
function notesFactsToCheck(data: CandidateNotesFacts | undefined): number {
  if (!data) return 0;
  return [data.rate, data.work_mode, data.contract_form, data.availability, data.office_cities].filter(
    (fact) => Boolean(fact && (fact as { can_apply?: boolean }).can_apply),
  ).length;
}

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
  const { replaceUrl } = useUrlWriter();
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
  // `?from=job-search&jobId=N` — profil z „Szukaj ręcznie” w oknie rekrutacji.
  const backJobSearchId = React.useMemo(
    () => (embedded ? null : decodeJobSearchBackRef(new URLSearchParams(searchString))),
    [embedded, searchString],
  );
  const backJobSearchQuery = useQuery({
    queryKey: ["job", String(backJobSearchId)],
    queryFn: () => api.get(`/api/jobs/${backJobSearchId}`).then((r) => r.data),
    enabled: backJobSearchId != null,
    staleTime: 5 * 60_000,
  });
  // „Wybieram” na profilu z „Szukaj ręcznie” — osoba wraca zaznaczona w oknie.
  // Czytane po montowaniu: pamięć karty nie istnieje przy renderze serwera.
  const [pickedIds, setPickedIds] = useState<number[]>([]);
  useEffect(() => {
    setPickedIds(backJobSearchId != null ? readJobSearchReturn(backJobSearchId).picked : []);
  }, [backJobSearchId]);
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
      replaceUrl(`${profilePath}?${params.toString()}`);
    },
    [embedded, profilePath, replaceUrl, searchString],
  );

  const goToSection = React.useCallback(
    (
      section: CandidateProfileView["section"],
      sub: Partial<Pick<CandidateProfileView, "activity" | "documents" | "recruitments">> = {},
    ) =>
      replaceProfileView({
        section,
        activity: sub.activity ?? "notes",
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
    replaceUrl(`${profilePath}?${params.toString()}`);
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
    replaceUrl(`${profilePath}?${params.toString()}`);
  }, [backJobId, embedded, profilePath, profileViewFromUrl, replaceUrl, searchString]);

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
        if (backJobSearchId != null) {
          sp = withJobSearchBackRef(sp, backJobSearchId);
          writeJobSearchReturn(backJobSearchId, { lastOpenedId: next.candidateId });
        } else {
          // Lista „Kandydaci” po powrocie wyróżnia ostatnio oglądaną osobę.
          writeListSearch({ lastOpenedId: next.candidateId });
        }
        sp = withCandidateProfileView(sp, profileView);
        const messageId = searchParams?.get("msg");
        if (messageId) sp.set("msg", messageId);
        // `replace`: „Wstecz” przeglądarki wraca do wyszukiwania jednym
        // kliknięciem, nie po kolei przez każdy przejrzany profil.
        router.replace(`/candidates/${next.candidateId}?${sp.toString()}`);
        router.refresh();
      }
    },
    [backJobSearchId, navContext, profileView, searchParams, urlNav, router],
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
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [tagsPoolsOpen, setTagsPoolsOpen] = useState(false);
  const [conflictsOpen, setConflictsOpen] = useState(false);
  const [notesFactsOpen, setNotesFactsOpen] = useState(false);
  const [followupOpen, setFollowupOpen] = useState(false);
  const [blacklistOpen, setBlacklistOpen] = useState(false);
  const [latestCvOpen, setLatestCvOpen] = useState(false);

  // ── Uprawnienia ───────────────────────────────────────────────────────
  const currentUser = useAuthStore((s) => s.user);
  // Akcje zapisu = capability `candidate.write` (lustro CANDIDATE_WRITE_ROLES
  // + sekcja sourcing write + blokada impersonacji).
  const canWriteSourcing = useCapability("candidate.write");
  const canManageProfileFacts = useCapability("candidate.profile_fact.manage");
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

  useEffect(() => {
    if (candidate && !embedded) {
      openTab("candidate", Number(id), `${candidate.name} ${candidate.lastname}`.trim());
    }
  }, [candidate, id, openTab, embedded]);

  // Notatki: licznik zakładki „Notatki i historia” (29.09.2026 — liczba
  // notatek ludzi, bez odpowiedzi i wpisów automatów) i „Ostatnia rozmowa”
  // w Przeglądzie. Ten sam klucz i zapytanie co lista w zakładce, więc jedno
  // pobranie. Oś czasu ładuje się dopiero w zakładce (04.10.2026).
  const notesCountQuery = useQuery<{ items?: any[]; group_counts?: Record<string, number> }>({
    queryKey: candidateQueryKeys.notes(id),
    queryFn: ({ signal }) =>
      api.get(`/api/notes?candidate_id=${id}`, { signal }).then((r) => r.data),
    enabled: !!id,
    staleTime: 30_000,
  });

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

  // Follow-up z kandydatem (0372): „Teraz” w Przeglądzie i pozycja w menu „⋯”.
  const followupQuery = useCandidateFollowup(Number.isFinite(id) && id > 0 ? id : null);
  const hasFollowup = Boolean(followupQuery.data?.followup);
  const hasFollowupMeetings = (followupQuery.data?.meetings?.length ?? 0) > 0;
  const noAnswer = useNoAnswer(Number(id), !canWriteSourcing);

  // Ustalenia z notatek (bez wywołania modelu) — ta sama kwerenda co okno
  // „Ustalenia z notatek”, więc okno nie pobiera drugi raz.
  const notesFactsQuery = useQuery<CandidateNotesFacts>({
    queryKey: candidateQueryKeys.notesFacts(id),
    queryFn: () => candidateFactsApi.getNotesFacts(id),
    enabled: !!id && canManageProfileFacts,
    retry: false,
    staleTime: 30_000,
  });

  // Ryzyko rezygnacji — odznaka w pasku osoby (recompute event-driven + TTL 24h).
  // Awaria = brak odznaki (dodatek, nie warunek działania profilu).
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
  // „Scal…” przy możliwym duplikacie z zakładki „Podobni” — okno od razu na porównaniu.
  const [mergeDuplicateId, setMergeDuplicateId] = useState<number | null>(null);
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
  const toCheck = notesFactsToCheck(notesFactsQuery.data);

  const fileCount = documentsQuery.isSuccess ? (documentsQuery.data ?? []).length : undefined;
  // „Najnowsze CV” w pasku osoby — z tej samej listy plików, bez osobnego zapytania.
  const cvDocuments = (documentsQuery.data ?? []).filter((doc) => doc.document_kind === "cv");
  const latestCv = latestCvDocument(cvDocuments);
  const tabs = [
    { value: "summary", label: "Przegląd", icon: User },
    {
      value: "recruitments",
      label: "Rekrutacje",
      icon: Calendar,
      // E6 (13.10.2026): licznik = procesy w toku; zakończone widać w zakładce.
      count:
        historyQuery.visibleData !== undefined
          ? splitRecruitments(history).active.length
          : undefined,
    },
    // Bez licznika: liczba rozmów wymagałaby dodatkowego zapytania przy
    // każdym otwarciu profilu.
    { value: "screening", label: "Screening", icon: ListChecks },
    {
      value: "activity",
      label: "Notatki",
      icon: MessageSquare,
      count: notesCountQuery.isSuccess
        ? humanNoteCount(notesCountQuery.data?.items ?? [])
        : undefined,
    },
    { value: "cv", label: "CV", icon: FileText },
    { value: "documents", label: "Dokumenty", icon: Files, count: fileCount },
    // 22.10.2026: osoby z podobnym CV (bez licznika — liczba wymagałaby
    // zapytania do wyszukiwarki przy każdym otwarciu profilu).
    { value: "similar", label: "Podobni", icon: Users },
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

  // Powrót do wyszukiwania: okno „Szukaj ręcznie” rekrutacji albo lista z filtrami.
  const backJobSearchTitle: string | null = backJobSearchQuery.data?.title ?? null;
  const backSearch =
    backJobSearchId != null
      ? {
          href: `/jobs/${backJobSearchId}?win=add&wintab=manual`,
          context: backJobSearchTitle,
        }
      : urlNav && backJobId == null && !backToTalentRadar
        ? { href: listBackHref(urlNav.filters), context: null }
        : null;
  const pick =
    backJobSearchId != null
      ? {
          picked: pickedIds.includes(candidateNumericId),
          count: pickedIds.length,
          onToggle: () => {
            const next = pickedIds.includes(candidateNumericId)
              ? pickedIds.filter((x) => x !== candidateNumericId)
              : [...pickedIds, candidateNumericId];
            setPickedIds(writeJobSearchReturn(backJobSearchId, { picked: next }).picked);
          },
        }
      : null;

  return (
    // Laptop z Windows (1280–1536 px): mniejsze odstępy nad zakładkami, żeby
    // zaczynały się w górnych 80% okna — pilnuje `e2e/responsive-preview.spec.ts`.
    <div
      className={
        embedded ? "space-y-4" : "mx-auto max-w-[1440px] space-y-5 md:max-2xl:space-y-3"
      }
    >
      <ProfileTopBar
        embedded={Boolean(embedded)}
        nav={navProps}
        backJobId={backJobId}
        backJobTitle={backJobTitle}
        backToTalentRadar={backToTalentRadar}
        backSearch={backSearch}
        pick={pick}
        candidateId={candidateNumericId}
      />

      <ProfilePersonBar
        candidate={candidate}
        candidateId={candidateNumericId}
        canWrite={canWriteSourcing}
        riskProfile={riskQuery.data ?? null}
        viewers={presenceViewers}
        onClose={embedded && !showNav ? onClose : undefined}
        actions={{
          onAssign: () => setAssignOpen(true),
          onAddNote: openNoteComposer,
          onNoAnswer: () => void noAnswer.recordNoAnswer(backJobId),
          noAnswerSaving: noAnswer.saving,
          onEmail: () => setEmailOpen(true),
          onScheduleInterview: () => setScheduleOpen(true),
          onPrepInvite: () => setPrepInviteOpen(true),
          onFollowup:
            hasFollowup || hasFollowupMeetings ? () => setFollowupOpen(true) : undefined,
          followupLabel: hasFollowupMeetings
            ? "Spotkania i transkrypty Teams"
            : "Zaplanuj follow-up w Teams",
          onEdit: () => setEditOpen(true),
          onTagsPools: () => setTagsPoolsOpen(true),
          onConflicts: () => setConflictsOpen(true),
          onDelete: canDeleteCandidate ? () => setDeleteOpen(true) : undefined,
          onMerge: canMerge ? () => setMergeOpen(true) : undefined,
          onBlacklist: canWriteSourcing ? () => setBlacklistOpen(true) : undefined,
          latestCv,
          onOpenLatestCv: () => setLatestCvOpen(true),
        }}
      />

      {/* Czarna lista „u nas” (17.10.2026): kto, kiedy i dlaczego — zamiast
          plakietki w pasku osoby. „Zdejmij…” tylko admin, DL i HoR. */}
      {candidate.status === "blacklisted" ? (
        <BlacklistNotice
          candidateId={candidateNumericId}
          candidateName={fullName}
          blacklist={candidate.blacklist}
        />
      ) : null}

      {/* Od 1100 px: karta „Do propozycji” po lewej (przyklejona), zakładki
          po prawej. `min-[1100px]` = szerokość okna; w szufladzie (embedded)
          zawsze jedna kolumna — szuflada jest wąska. */}
      <div
        className={
          embedded
            ? "space-y-4"
            : "grid items-start gap-4 min-[1100px]:grid-cols-[17.5rem_minmax(0,1fr)] md:max-2xl:gap-3"
        }
      >
        <aside
          aria-label="Karta kandydata"
          className={
            embedded
              ? "space-y-4"
              : "space-y-4 min-[1100px]:sticky min-[1100px]:top-4 min-[1100px]:max-h-[calc(100dvh-2rem)] min-[1100px]:overflow-y-auto min-[1100px]:pb-2"
          }
        >
          <CandidateProfileFactsBar
            candidate={candidate}
            layout="proposal"
            lead={
              candidate.employment ? (
                <AtOurClientBanner
                  employment={candidate.employment}
                  marker={candidate.employment_marker}
                  variant="compact"
                />
              ) : null
            }
          >
            {canManageProfileFacts ? (
              toCheck > 0 ? (
                <button
                  type="button"
                  data-help="candidate.profile.notes_facts"
                  onClick={() => setNotesFactsOpen(true)}
                  className="mt-2 flex min-h-9 w-full items-center justify-between gap-2 rounded-lg bg-warning-muted px-2.5 text-left text-xs font-medium text-warning-muted-foreground hover:underline"
                >
                  <span>
                    {toCheck === 1
                      ? "1 rzecz do sprawdzenia z rozmowy"
                      : `${toCheck} rzeczy do sprawdzenia z rozmowy`}
                  </span>
                  <span className="shrink-0 underline">Sprawdź</span>
                </button>
              ) : (
                <button
                  type="button"
                  data-help="candidate.profile.notes_facts"
                  onClick={() => setNotesFactsOpen(true)}
                  className="mt-1 inline-flex min-h-8 items-center text-xs font-medium text-primary hover:underline"
                >
                  Ustalenia z notatek
                </button>
              )
            ) : null}
          </CandidateProfileFactsBar>
        </aside>

        <Card
          variant="default"
          size="md"
          className="min-w-0 overflow-hidden p-0!"
          data-help="candidate.profile.tabs"
        >
          <TabbedNav
            value={activeTab}
            onValueChange={(value) => goToSection(value as CandidateProfileView["section"])}
            ariaLabel="Sekcje profilu kandydata"
            overflow="scroll"
            listClassName="max-w-full justify-start px-4 pt-2 *:shrink-0"
            tabs={tabs}
          >
            {/* `@container`: treść zakładek układa się po szerokości karty,
                nie okna — obok lewej kolumny i paska bocznego karta bywa wąska. */}
            <div className="@container p-4 sm:p-5">
              <TabsContent value="summary" className="mt-0">
                <ProfileTab
                  candidate={candidate}
                  readOnly={readOnly}
                  recruitments={{
                    items: history,
                    isPending:
                      historyQuery.isPending ||
                      (historyQuery.isFetching && historyQuery.visibleData === undefined),
                    isError: Boolean(historyQuery.error),
                    refetch: () => void historyQuery.refetch(),
                  }}
                  notes={{
                    items: notesCountQuery.data?.items ?? [],
                    groupCounts: notesCountQuery.data?.group_counts ?? null,
                    isPending: notesCountQuery.isPending,
                    isError: notesCountQuery.isError,
                    refetch: () => void notesCountQuery.refetch(),
                  }}
                  onNavigate={(target) => {
                    if (target.section === "activity" && target.noteId) {
                      const params = withCandidateProfileView(new URLSearchParams(searchString), {
                        section: "activity",
                        activity: "notes",
                        documents: "files",
                        recruitments: "list",
                      });
                      params.set("note", String(target.noteId));
                      setProfileView({ ...parseCandidateProfileView(params), isLegacy: false });
                      if (!embedded) {
                        replaceUrl(`${profilePath}?${params.toString()}`);
                      }
                      return;
                    }
                    goToSection(
                      target.section,
                      target.section === "activity" && target.activity
                        ? { activity: target.activity }
                        : {},
                    );
                  }}
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
                  clientRateAccess={
                    historyRaw && !Array.isArray(historyRaw)
                      ? {
                          canView: historyRaw.can_view_client_rate,
                          canWrite: historyRaw.can_write_client_rate,
                        }
                      : undefined
                  }
                />
              </TabsContent>

              <TabsContent value="screening" className="mt-0">
                <CandidateScreeningAnswersCard candidateId={candidateNumericId} variant="tab" />
              </TabsContent>

              <TabsContent value="activity" className="mt-0">
                <HistoryTab
                  candidateId={candidateNumericId}
                  candidate={candidate}
                  activityView={profileView.activity}
                  onActivityViewChange={(activity: CandidateActivityView) =>
                    goToSection("activity", { activity })
                  }
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

              <TabsContent value="cv" className="mt-0">
                <CvSkillsSection
                  candidate={candidate}
                  readOnly={readOnly}
                  onGenerateCv={canWriteSourcing ? () => setCvOpen(true) : undefined}
                  onOpenFiles={() => goToSection("documents")}
                />
              </TabsContent>

              <TabsContent value="documents" className="mt-0">
                <FilesContractsTab
                  candidate={candidate}
                  candidateName={fullName}
                  readOnly={readOnly}
                  focus={profileView.documents}
                  recruitments={history}
                  historyContracts={
                    historyRaw && !Array.isArray(historyRaw) ? (historyRaw.contracts ?? []) : []
                  }
                  employmentMarker={candidate.employment_marker}
                />
              </TabsContent>

              <TabsContent value="similar" className="mt-0">
                {/* Montuje się dopiero na tej zakładce — wyszukiwarka nie
                    pracuje przy każdym otwarciu profilu. */}
                {activeTab === "similar" ? (
                  <SimilarCandidatesTab
                    candidateId={candidateNumericId}
                    candidateName={fullName}
                    recruitments={history}
                    canWrite={canWriteSourcing}
                    onMergeDuplicate={
                      canMerge
                        ? (duplicateId) => {
                            setMergeDuplicateId(duplicateId);
                            setMergeOpen(true);
                          }
                        : undefined
                    }
                  />
                ) : null}
              </TabsContent>
            </div>
          </TabbedNav>
        </Card>
      </div>

      <TagsPoolsDialog
        open={tagsPoolsOpen}
        onOpenChange={setTagsPoolsOpen}
        candidateId={candidateNumericId}
        tags={candidate.tags}
        canEdit={canWriteSourcing}
      />
      <ConflictsVetoesDialog
        open={conflictsOpen}
        onOpenChange={setConflictsOpen}
        candidateId={candidateNumericId}
      />
      {canManageProfileFacts ? (
        <NotesFactsDialog
          open={notesFactsOpen}
          onOpenChange={setNotesFactsOpen}
          candidateId={candidateNumericId}
          readOnly={readOnly}
        />
      ) : null}
      {followupOpen ? (
        <CandidateFollowupDialog
          candidateId={candidateNumericId}
          open={followupOpen}
          onOpenChange={setFollowupOpen}
        />
      ) : null}

      {latestCvOpen && latestCv ? (
        <FilePreviewModal
          documents={cvDocuments}
          initialDocumentId={latestCv.id}
          candidateId={candidateNumericId}
          onClose={() => setLatestCvOpen(false)}
          onDownload={(doc) =>
            downloadDocumentBlob(candidateNumericId, doc).catch(() =>
              showError("Nie udało się pobrać pliku."),
            )
          }
        />
      ) : null}

      {canWriteSourcing ? (
        <>
          {emailOpen && (
            <SendEmailV2
              open
              onOpenChange={setEmailOpen}
              candidateId={candidateNumericId}
              candidateName={fullName}
              candidateEmail={candidate.email ?? ""}
              requestId={backJobId ?? undefined}
            />
          )}
          <CvGeneratorDialog
            open={cvOpen}
            onOpenChange={setCvOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
          />
          <BlacklistDialog
            open={blacklistOpen}
            onOpenChange={setBlacklistOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
            alreadyBlacklisted={candidate.status === "blacklisted"}
          />
          <QuickAssignV2
            open={assignOpen}
            onOpenChange={setAssignOpen}
            candidateId={candidateNumericId}
            candidateName={fullName}
            employment={candidate.employment_marker}
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
        </>
      ) : null}
      {canMerge && candidate ? (
        <CandidateMergeDialog
          // Okno czyta duplikat tylko przy montowaniu — inny duplikat = nowe okno.
          key={mergeDuplicateId ?? "pick"}
          open={mergeOpen}
          onOpenChange={(next) => {
            setMergeOpen(next);
            if (!next) setMergeDuplicateId(null);
          }}
          initialDuplicateId={mergeDuplicateId}
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
