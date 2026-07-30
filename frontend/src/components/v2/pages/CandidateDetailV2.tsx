"use client";

import * as React from"react";
import { useEffect, useMemo, useRef, useState } from"react";
import Link from"next/link";
import { useParams, useRouter, useSearchParams } from"next/navigation";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { EditorContent, useEditor } from"@tiptap/react";
import StarterKit from"@tiptap/starter-kit";
import {
 AlertTriangle,
 ArrowLeft,
  ArrowRight,
 Ban,
 Calendar,
 CheckCircle2,
 ChevronDown,
 ChevronUp,
 Download,
 FileSignature,
 FileText,
 Files,
 Gauge,
 GraduationCap,
 Link2,
 Linkedin,
 Loader2,
 Mail,
 MapPin,
  MessageSquare,
 PencilLine,
 Plus,
 Printer,
 RefreshCcw,
 ShieldAlert,
 Sparkles,
 Star,
 Store,
 Target,
 Trash2,
 User,
 UserPlus,
  Wallet,
  X,
} from"lucide-react";
import api, {
 candidatesApi,
 contractsApi,
 extractErrorMsg,
 type ContractDraftResponse,
 type RateUnit,
 candidateStageCvApi,
 type CVOriginalSnapshot,
  type CVBrandedState,
  callsApi,
  type Call,
} from"@/lib/api";
import { downloadContractDocument } from"@/lib/contract-documents";
import { celebrate } from"@/lib/celebrate";
import CallButton from"@/components/calls/CallButton";
import { useToast } from"@/components/Toast";
import { Input } from"@/components/ui/input";
import { Label } from"@/components/ui/label";
import { PinButton } from"@/components/v2/PinButton";
import { DeferUntilVisible } from"@/components/v2/DeferUntilVisible";
import { ExpandableText } from"@/components/v2/ExpandableText";
import {
 getCandidateSummaryLine,
 getEducationList,
} from"@/components/v2/pages/candidate-profile-helpers";
import {
 formatCandidateLocation,
 getCandidateInitials,
 getCurrentTitle,
 getExperienceLabel,
 getTagName,
} from"@/components/v2/pages/candidate-list-helpers";
import { CandidateEngagementPanel } from"@/components/candidates/CandidateEngagementPanel";
import { CandidateLocationPanel } from"@/components/candidates/CandidateLocationPanel";
import { CandidateSourcesPanel } from"@/components/candidates/CandidateSourcesPanel";
import { cn, formatDate, formatRelativeTime } from"@/lib/utils";
import { stageLabel } from "@/lib/cv-generator";
import { useTabsStore } from"@/store/tabs";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from"@/components/ui/card";
import { Separator } from"@/components/ui/separator";
import { TabsContent } from"@/components/ui/tabs";
import { TabbedNav } from "@/components/ds/TabbedNav";
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuSeparator,
 DropdownMenuTrigger,
} from"@/components/ui/dropdown-menu";
import { Textarea } from"@/components/ui/textarea";
import { MentionTextarea } from"@/components/v2/forms/MentionTextarea";
import { detectNotePersonMismatch } from"@/lib/note-person-mismatch";
import { useMentionableUsers, type MentionScope } from"@/hooks/useMentionableUsers";
import {
 buildUsersByEmail,
 renderWithMentions,
} from"@/lib/renderMentions";
import { EditCandidateModal } from"@/components/AppShell";
import { IdentityEditor } from"./CandidateIdentityEditor";
import { ScreeningSheet } from"@/components/v2/modals/ScreeningSheet";
import { SendEmailV2 } from"@/components/v2/modals/SendEmailV2";
import { AutentiEnvelopeCard } from"@/components/v2/contract/AutentiEnvelopeCard";
import { CVGeneratorV2 } from"@/components/v2/modals/CVGeneratorV2";
import { CVOriginalPreviewModal } from"@/components/v2/modals/CVOriginalPreviewModal";
import { openAuthenticatedFile } from "@/lib/authenticated-files";
import { CVBrandedEditModal } from"@/components/v2/modals/CVBrandedEditModal";
import { CVShareLinkModal } from"@/components/v2/modals/CVShareLinkModal";
import {
  FilePreviewModal,
  FilePreviewContent,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { CandidateFilesTab } from "@/components/v2/files/CandidateFilesTab";
import {
 Dialog,
 DialogContent,
} from"@/components/ui/dialog";
import { QuickAssignV2 } from"@/components/v2/modals/QuickAssignV2";
import { RiskBadge } from"@/components/v2/RiskBadge";
import { CompetenceCategoryBadge } from"@/components/v2/CompetenceCategoryBadge";
import type { CandidateRiskProfile } from"@/types/candidate-risk";
import { SuggestedJobsWidget } from"@/components/SuggestedJobsWidget";
import { SuggestedPoolsWidget } from"@/components/candidates/SuggestedPoolsWidget";
import ScheduleInterviewModal from"@/components/calendar/ScheduleInterviewModal";
import {
 CandidatePipelinesWidget,
 candidatePipelinesQueryKey,
} from"@/components/CandidatePipelinesWidget";
import { RateHistoryWidget } from"@/components/RateHistoryWidget";
import { ConflictsWidget } from"@/components/ConflictsWidget";
import { HiringManagerVetoesWidget } from"@/components/HiringManagerVetoesWidget";
import { AddToMarketplaceButton } from"@/components/marketplace/AddToMarketplaceButton";
import {
 AtOurClientBanner,
 CandidateHighlights,
} from"@/components/v2/CandidateHighlights";
import { LinkedinSyncPanel } from"@/components/v2/LinkedinSyncPanel";
import { ActiveViewers } from"@/components/v2/presence/ActiveViewers";
import { usePresence, type PresenceViewer } from"@/hooks/usePresence";
import { useAuthStore, hasRole } from"@/store/auth";
import CandidateChatTab from"@/components/v2/pages/CandidateChatTab";
import CallsTimeline from"@/components/calls/CallsTimeline";
import { DopasowanieTab } from"@/components/v2/pages/DopasowanieTab";
import { CandidateActivitySummaryCard } from"@/components/v2/pages/CandidateActivitySummaryCard";
import { CandidateProfileFactsBar } from"@/components/v2/pages/CandidateProfileFactsBar";
import { CandidateRecentRecruitmentsCard } from"@/components/v2/pages/CandidateRecentRecruitmentsCard";
import { CandidateNav } from"@/components/v2/CandidateNav";
import {
 useCandidateNavigation,
 type CandidateLite,
} from"@/hooks/useCandidateNavigation";
import {
 DEFAULT_FILTERS,
 type CandidateFilters,
 decodeNavContext,
 decodeJobBackRef,
 encodeNavContext,
} from"@/lib/url-filters";
import { candidateQueryKeys } from"@/components/v2/pages/candidate-query-keys";
import { invalidateCandidateMutation } from"@/components/v2/pages/candidate-cache";
import { useCandidateHistoryQuery } from"@/components/v2/pages/candidate-history-query";
import {
 ACTIVITY_VIEWS,
 DOCUMENT_VIEWS,
 focusCandidateRecruitmentCard,
 parseCandidateRecruitmentFocus,
 parseCandidateProfileView,
 resolveVisibleRecruitmentFocus,
 type CandidateActivityView,
 type CandidateDocumentView,
 type CandidateProfileSection,
 withCandidateProfileView,
} from"@/components/v2/pages/candidate-profile-navigation";
import { ContactOutcomeSheet } from "@/components/candidate-contact/ContactOutcomeSheet";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import {
 candidateContactApi,
 candidateContactQueryKeys,
 type CandidateContactCase,
} from "@/lib/candidate-contact";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";

const STATUS_VARIANT: Record<string, "success" |"warning" |"danger" |"neutral"> = {
 active: "success",
 passive: "warning",
 blacklisted: "danger",
};
const STATUS_LABELS: Record<string, string> = {
 active: "Aktywny",
 passive: "Pasywny",
 blacklisted: "Zablokowany",
};

const SKILL_LEVEL_VARIANT: Record<
 string, "burgundy" |"success" |"warning" |"neutral"
> = {
 expert: "burgundy",
 senior: "success",
 mid: "warning",
 junior: "neutral",
};

const PROFILE_SECTION_LABELS: Record<CandidateProfileSection, string> = {
 summary: "Podsumowanie",
 recruitments: "Rekrutacje",
 activity: "Aktywność",
 matching: "Dopasowanie",
 documents: "Pliki i umowy",
};

const ACTIVITY_LABELS: Record<CandidateActivityView, string> = {
 timeline: "Historia",
 notes: "Notatki",
 calls: "Rozmowy",
 chat: "Czat zespołu",
};

const DOCUMENT_LABELS: Record<CandidateDocumentView, string> = {
 files: "Pliki",
 contracts: "Umowy",
};

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
}

export function CandidateDetailV2({
 embedded,
 candidateId,
 onClose,
 navigation,
}: CandidateDetailV2Props = {}) {
 const routeParams = useParams();
 const router = useRouter();
 const id = candidateId ?? Number(routeParams?.id);
 const queryClient = useQueryClient();
 const { showError } = useToast();
 const openTab = useTabsStore((s) => s.openTab);

 // ── Prev/Next candidate navigation context ─────────────────────────────
 // Embedded mode receives `navigation` from parent (CandidatesListV2).
 // Full-page mode reads it from URL search params (?nav=search&pos=N&...).
 // Use `useSearchParams` so the value re-evaluates after client hydration
 // and on every push() — `window.location` inside useMemo wouldn't.
 const searchParamsForNav = useSearchParams();
 const requestedFocusJobId = React.useMemo(() => {
 if (embedded || !searchParamsForNav) return null;
 return parseCandidateRecruitmentFocus(
 new URLSearchParams(searchParamsForNav.toString()),
 );
 }, [embedded, searchParamsForNav]);
 const urlNav = React.useMemo(() => {
 if (embedded) return null; // embedded uses props, not URL
 if (!searchParamsForNav) return null;
 const sp = new URLSearchParams(searchParamsForNav.toString());
 return decodeNavContext(sp);
 }, [embedded, searchParamsForNav]);

 // ── "Came from a recruitment" back-reference ───────────────────────────
 // When the profile was opened from a job's pipeline (`?from=job&jobId=N`),
 // the back link returns to that recruitment instead of the candidate list.
 // The job title is resolved from the open-tabs store (the job page registers
 // it via `openTab`), falling back to a generic label when it isn't cached.
 const backJobId = React.useMemo(() => {
 if (embedded) return null; // embedded drawers carry their own nav
 if (!searchParamsForNav) return null;
 return decodeJobBackRef(new URLSearchParams(searchParamsForNav.toString()));
 }, [embedded, searchParamsForNav]);
 const openTabsList = useTabsStore((s) => s.tabs);
const backJobTitle =
 backJobId != null
 ? (openTabsList.find((t) => t.type === "job" && t.entityId === backJobId)
 ?.title ?? null)
: null;

 const profileViewFromUrl = React.useMemo(
 () =>
 parseCandidateProfileView(
 new URLSearchParams(searchParamsForNav?.toString() ?? ""),
 { fromJob: backJobId != null },
 ),
 [backJobId, searchParamsForNav],
 );
 const [profileView, setProfileView] = React.useState(profileViewFromUrl);

 React.useEffect(() => {
 setProfileView((current) =>
 current.section === profileViewFromUrl.section &&
 current.activity === profileViewFromUrl.activity &&
 current.documents === profileViewFromUrl.documents
 ? current
 : profileViewFromUrl,
 );
 }, [profileViewFromUrl]);

 const replaceProfileView = React.useCallback(
 (next: Pick<typeof profileView, "section" | "activity" | "documents">) => {
 const merged = { ...profileView, ...next, isLegacy: false };
 setProfileView(merged);
 if (embedded) return;
 const params = withCandidateProfileView(
 new URLSearchParams(searchParamsForNav?.toString() ?? ""),
 merged,
 );
 router.replace(`/candidates/${id}?${params.toString()}`, { scroll: false });
 },
 [embedded, id, profileView, router, searchParamsForNav],
 );

 const setActiveTab = React.useCallback(
 (value: string) => {
 const mapped = parseCandidateProfileView(
 new URLSearchParams(`tab=${encodeURIComponent(value)}`),
 );
 replaceProfileView({
 section: mapped.section,
 activity: mapped.activity,
 documents: mapped.documents,
 });
 },
 [replaceProfileView],
 );

 const setActivityView = React.useCallback(
 (activity: CandidateActivityView) =>
 replaceProfileView({ ...profileView, section: "activity", activity }),
 [profileView, replaceProfileView],
 );
 const setDocumentsView = React.useCallback(
 (documents: CandidateDocumentView) =>
 replaceProfileView({ ...profileView, section: "documents", documents }),
 [profileView, replaceProfileView],
 );

 // Replace legacy deep links once, preserving context such as `msg`, nav
 // filters and the job back-reference. A job entry without an explicit tab
 // opens Activity/History with the split CV view.
 React.useEffect(() => {
 if (embedded) return;
 const needsCanonicalUrl =
 profileViewFromUrl.isLegacy ||
 (backJobId != null && !profileViewFromUrl.hasExplicitTab);
 if (!needsCanonicalUrl) return;
 const params = withCandidateProfileView(
 new URLSearchParams(searchParamsForNav?.toString() ?? ""),
 profileViewFromUrl,
 );
 router.replace(`/candidates/${id}?${params.toString()}`, { scroll: false });
 }, [
 backJobId,
 embedded,
 id,
 profileViewFromUrl,
 router,
 searchParamsForNav,
 ]);

 const activeTab = profileView.section;
 const activityView = profileView.activity;
 const documentsView = profileView.documents;

const navContext: CandidateDetailNavigation | null = navigation ?? null;
 const navMode: "embedded" |"url" |"off" = navContext
 ?"embedded"
 : urlNav
 ?"url"
 :"off";

 // URL mode: keep an internal position state so the counter updates *now*
 // (on click) rather than waiting for `useSearchParams` to re-emit after
 // `router.push` settles — when the dynamic `[id]` segment is cached the
 // re-emit can lag a render. Sync from URL whenever it actually changes
 // (back/forward, refresh, deep link).
 const [urlPosition, setUrlPosition] = React.useState<number>(
 urlNav?.position ?? 1,
 );
 React.useEffect(() => {
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
 // URL mode: navigate to the new candidate, preserving filters + new pos.
 if (urlNav) {
 setUrlPosition(next.position); // optimistic — counter updates instantly
 let sp = encodeNavContext(urlNav.filters, next.position);
 sp = withCandidateProfileView(sp, profileView);
 const messageId = searchParamsForNav?.get("msg");
 if (messageId) sp.set("msg", messageId);
 router.push(`/candidates/${next.candidateId}?${sp.toString()}`);
 // Next.js caches the dynamic `[id]` segment, so `useSearchParams`
 // can lag a render. Refresh server data so subsequent navigations
 // see the up-to-date URL params.
 router.refresh();
 }
 },
 [navContext, profileView, searchParamsForNav, urlNav, router],
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
 // Disabled — no nav context available.
 mode: "url",
 enabled: false,
 filters: DEFAULT_FILTERS,
 position: 1,
 onNavigate: () => {},
 },
 );

 const showNav = navMode !== "off";

 const [emailOpen, setEmailOpen] = useState(false);
 const [cvOpen, setCvOpen] = useState(false);
 const [assignOpen, setAssignOpen] = useState(false);
 const [scheduleOpen, setScheduleOpen] = useState(false);
 const [contactOutcomeOpen, setContactOutcomeOpen] = useState(false);
 const [editOpen, setEditOpen] = useState(false);
 // Inline edycja tożsamości/kontaktu (imię, nazwisko, email, telefon) wprost
 // w nagłówku — szybka korekta np. kandydatów zaimportowanych jako "?".
 const [editingIdentity, setEditingIdentity] = useState(false);
 const [marketplaceOpen, setMarketplaceOpen] = useState(false);
 const [screeningStage, setScreeningStage] = useState<number | null>(null);
 const [noteText, setNoteText] = useState("");
 const [noteSaving, setNoteSaving] = useState(false);
 const [showActivityCv, setShowActivityCv] = useState(backJobId != null);
 useEffect(() => {
 if (backJobId != null) setShowActivityCv(true);
 }, [backJobId, id]);

 // Presence: one subscription per candidate page; viewers + setEditing are
 // passed into children so the NotatkiTab can emit edit signals without
 // mounting a second hook instance.
 const currentUser = useAuthStore((s) => s.user);
 const contactFeature = useCandidateContactFeature({
 queryEnabled: hasRole(
 currentUser,
 "admin",
 "head_of_recruitment",
 "delivery_lead",
 "tac",
 "recruiter",
 "sourcer",
 ),
 });
 const { viewers: presenceViewers, setEditing: setPresenceEditing } =
 usePresence("candidate", Number.isFinite(Number(id)) ? Number(id) : null);

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
 enabled:
 contactFeature.enabled &&
 Number.isFinite(Number(id)) &&
 Number(id) > 0,
 staleTime: 30_000,
 retry: false,
 });

 useEffect(() => {
 if (candidate && !embedded) {
 const fullName = `${candidate.name} ${candidate.lastname}`.trim();
 openTab("candidate", Number(id), fullName);
 }
 }, [candidate, id, openTab, embedded]);

 // Wyjdź z inline-edycji nagłówka przy przełączeniu kandydata (prev/next w
 // drawerze), żeby formularz nie pokazywał danych poprzedniego kandydata.
 useEffect(() => {
 setEditingIdentity(false);
 }, [id]);

 // Timeline API returns `{ timeline: [...] }` — normalize to array.
 const timelineQuery = useQuery<{ timeline?: any[] } | any[]>({
 queryKey: candidateQueryKeys.timeline(id, 50),
 queryFn: ({ signal }) =>
 api
 .get(`/api/candidates/${id}/timeline?limit=50`, { signal })
 .then((r) => r.data),
 enabled:
 !!id &&
 activeTab === "activity" &&
 (activityView === "timeline" || activityView === "notes"),
 });
 const { data: timelineRaw } = timelineQuery;
 const timeline: any[] = Array.isArray(timelineRaw)
 ? timelineRaw
 : (timelineRaw?.timeline ?? []);

 // Notatki tab — dedykowane, NIEUCINANE źródło notatek. Feed `/timeline`
 // miesza notatki z etapami/aktywnościami i ucina do limitu (50), więc przy
 // bogatej historii (np. import Traffit) starsze notatki znikały z zakładki.
 // `/api/notes` zwraca komplet, wzbogacony o author_name + content_rendered.
 const notesQuery = useQuery<{ items?: any[] }>({
 queryKey: candidateQueryKeys.notes(id),
 queryFn: ({ signal }) =>
 api.get(`/api/notes?candidate_id=${id}`, { signal }).then((r) => r.data),
 enabled: !!id && activeTab === "activity" && activityView === "notes",
 });
 const { data: notesRaw } = notesQuery;
 const noteItems: any[] = (notesRaw?.items ?? []).map((n: any) => ({
 ...n,
 type: "note",
 timestamp: n.created_at,
 }));

 // History API returns `{ jobs: [...], contracts: [...] }` — flatten jobs.
 // Także na zakładce "notatki" — potrzebujemy listy rekrutacji do selektora
 // "przypisz notatkę do rekrutacji".
 const historyQuery = useCandidateHistoryQuery(
 id,
 !!id &&
 (activeTab === "recruitments" ||
 activeTab === "matching" ||
 (activeTab === "activity" &&
 (activityView === "timeline" || activityView === "notes"))),
 );
 const historyRaw = historyQuery.visibleData;

 // Phase 17 (migracja 0068): risk profile — pokazujemy badge w nagłówku.
 // Recompute następuje event-driven po każdej tranzycji + TTL 24h, więc
 // staleTime 5 min jest tu bezpieczny.
 const riskQuery = useQuery<CandidateRiskProfile>({
 queryKey: candidateQueryKeys.risk(id),
 queryFn: ({ signal }) =>
 api.get(`/api/candidates/${id}/risk`, { signal }).then((r) => r.data),
 enabled: !!id,
 staleTime: 5 * 60 * 1000,
 });
 const { data: riskProfile } = riskQuery;
 const history = React.useMemo<any[]>(
 () => (Array.isArray(historyRaw) ? historyRaw : (historyRaw?.jobs ?? [])),
 [historyRaw],
 );
 const historyContracts: any[] = Array.isArray(historyRaw)
 ? []
 : (historyRaw?.contracts ?? []);
 const visibleFocusJobId = React.useMemo(
 () => resolveVisibleRecruitmentFocus(requestedFocusJobId, history),
 [history, requestedFocusJobId],
 );
 const handledRecruitmentFocusRef = React.useRef<string | null>(null);

 React.useEffect(() => {
 if (
 activeTab !== "recruitments" ||
 !historyQuery.isSuccess ||
 visibleFocusJobId == null
 ) {
 return;
 }

 const focusKey = `${id}:${visibleFocusJobId}`;
 if (handledRecruitmentFocusRef.current === focusKey) return;

 if (!focusCandidateRecruitmentCard(visibleFocusJobId)) return;
 handledRecruitmentFocusRef.current = focusKey;
 }, [activeTab, historyQuery.isSuccess, id, visibleFocusJobId]);

 const aiProfileQuery = useQuery<any>({
 queryKey: candidateQueryKeys.aiProfile(id),
 queryFn: ({ signal }) =>
 api.get(`/api/candidates/${id}/ai-profile`, { signal }).then((r) => r.data),
 enabled: !!id && activeTab === "summary",
 });
 const { data: aiProfile } = aiProfileQuery;

 // Lista umów kandydata — dla zakładki"Umowa". Backend już akceptuje
 // ?candidate_id w GET /api/contracts; zwraca paginowaną kopertę.
 const contractsQuery = useQuery<{ items?: any[] } | any[]>({
 queryKey: candidateQueryKeys.contracts(id),
 queryFn: () =>
 contractsApi.byCandidate(Number(id)).then((r: any) => r.data),
 enabled: !!id && activeTab === "documents" && documentsView === "contracts",
 });
 const { data: candidateContractsRaw } = contractsQuery;
 const candidateContracts: any[] = Array.isArray(candidateContractsRaw)
 ? candidateContractsRaw
 : (candidateContractsRaw?.items ?? []);

 const callsQuery = useQuery<Call[]>({
 queryKey: candidateQueryKeys.calls(id),
 queryFn: () => callsApi.getForCandidate(Number(id)),
 enabled: !!id && activeTab === "activity" && activityView === "calls",
 });

 const handleAddNote = async (jobId?: number | null) => {
 if (!noteText.trim()) return;
 setNoteSaving(true);
 try {
 // Bez trailing slash — backend rejestruje POST /api/notes (router prefix
 // + path ""). Wariant "/api/notes/" zwracał 404, a brak catcha połykał
 // błąd po cichu → przycisk "nie działał" (nic się nie dodawało).
 // job_id opcjonalny — gdy ustawiony, notatka jest przypięta do konkretnej
 // rekrutacji (a @mention scope na backendzie zawęża się do członków joba).
 await api.post("/api/notes", {
 candidate_id: Number(id),
 content: noteText.trim(),
 note_type: "general",
 ...(jobId ? { job_id: jobId } : {}),
 });
 setNoteText("");
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(id) });
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(id) });
 celebrate({ small: true, message: "Notatka dodana! 📝" });
 } catch (e) {
 showError(extractErrorMsg(e) || "Nie udało się dodać notatki");
 } finally {
 setNoteSaving(false);
 }
 };

 // Edycja istniejącej notatki. PATCH re-parsuje @mentions na backendzie i
 // dożywia tylko *nowo* dodanych. Zwraca bool — NotatkiTab wychodzi z trybu
 // edycji dopiero po sukcesie. Bez trailing slash (jak handleAddNote).
 const handleEditNote = async (
 noteId: number,
 content: string,
 ): Promise<boolean> => {
 try {
 await api.patch(`/api/notes/${noteId}`, { content });
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(id) });
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(id) });
 return true;
 } catch (e) {
 showError(extractErrorMsg(e) || "Nie udało się zapisać notatki");
 return false;
 }
 };

 // Usuwanie notatki. Backend kaskaduje NoteMention; zwraca 403 gdy user nie
 // jest autorem ani adminem (spójne z gating w NotatkiTab).
 const handleDeleteNote = async (noteId: number): Promise<boolean> => {
 try {
 await api.delete(`/api/notes/${noteId}`);
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(id) });
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(id) });
 return true;
 } catch (e) {
 showError(extractErrorMsg(e) || "Nie udało się usunąć notatki");
 return false;
 }
 };

 // Hard delete usunięty z UI (audyt M2 PR1, M2-PRIV-02): kaskada ON DELETE
 // czyściła kontrakty/notatki/historię, a storage/Qdrant zostawały osierocone.
 // Backend odpowiada 409 do czasu privacy executora (PR2 planu modułu).

 // Open a "Więcej" menu action on the next tick, after Radix finishes closing
 // the dropdown, so the opened overlay isn't disturbed by the menu's dismiss.
 // Radix Dialogs (Email / interview / Generuj CV) only open reliably from a
 // menu item nested in the drawer Sheet because the dropdown is modal={false}
 // (see the DropdownMenu below) — without that, the menu's body pointer-events
 // lock swallows the dialog open, which is what regressed in issue 533.
 const openFromMenu = (fn: () => void) => setTimeout(fn, 0);

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
 const title =
 status === 403
 ? "Nie masz dostępu do tego profilu"
 : status === 404 || !Number.isFinite(Number(id))
 ? "Nie znaleziono kandydata"
 : "Nie udało się otworzyć profilu";
 const description =
 status === 403
 ? "Poproś administratora o dostęp do danych kandydata."
 : status === 404 || !Number.isFinite(Number(id))
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
 <Button
 variant="primary"
 className="min-h-11 min-w-11"
 onClick={() => candidateQuery.refetch()}
 >
 Spróbuj ponownie
 </Button>
 ) : null}
 {embedded && onClose ? (
 <Button
 variant="outline"
 className="min-h-11 min-w-11"
 onClick={onClose}
 >
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

 const fullName = `${candidate.name ??""} ${candidate.lastname ??""}`.trim();
 const initials = getCandidateInitials(candidate) || "?";

 const rootClass = embedded
 ?"space-y-4"
 :"max-w-[1440px] mx-auto space-y-5";

 return (
 <div className={rootClass}>
 {/* Top row: back link (full-page) and prev/next nav (when in nav context) */}
 {embedded ? (
 showNav ? (
 <CandidateNav
 position={candidateNav.position}
 total={candidateNav.total}
 hasPrev={candidateNav.hasPrev}
 hasNext={candidateNav.hasNext}
 onPrev={candidateNav.goPrev}
 onNext={candidateNav.goNext}
 isLoading={candidateNav.isLoading}
 error={candidateNav.error}
 onRetry={candidateNav.retry}
 onClose={onClose}
 onExpand={
 navContext
 ? () => {
 let sp = encodeNavContext(
 navContext.filters,
 candidateNav.position,
 );
 sp = withCandidateProfileView(sp, profileView);
 router.push(`/candidates/${id}?${sp.toString()}`);
 }
 : undefined
 }
 />
 ) : null
 ) : (
 <div className="flex items-center justify-between gap-3 flex-wrap">
 {backJobId != null ? (
 <Link
 href={`/jobs/${backJobId}`}
 className="inline-flex min-h-11 min-w-11 max-w-88 items-center gap-1 px-2 text-sm text-muted-foreground hover:text-primary"
 title={backJobTitle ? `Wróć do rekrutacji: ${backJobTitle}` :"Wróć do rekrutacji"}
 >
 <ArrowLeft className="h-4 w-4 shrink-0" />
 <span className="truncate">
 {backJobTitle ? `Wróć do rekrutacji: ${backJobTitle}` :"Wróć do rekrutacji"}
 </span>
 </Link>
 ) : (
 <Link
 href="/candidates"
 className="inline-flex min-h-11 min-w-11 items-center gap-1 px-2 text-sm text-muted-foreground hover:text-primary"
 >
 <ArrowLeft className="h-4 w-4" /> Wróć do kandydatów
 </Link>
 )}
 {showNav && (
 <CandidateNav
 position={candidateNav.position}
 total={candidateNav.total}
 hasPrev={candidateNav.hasPrev}
 hasNext={candidateNav.hasNext}
 onPrev={candidateNav.goPrev}
 onNext={candidateNav.goNext}
 isLoading={candidateNav.isLoading}
 error={candidateNav.error}
 onRetry={candidateNav.retry}
 className="ml-auto"
 />
 )}
 </div>
 )}

 {candidate.employment && (
 <AtOurClientBanner employment={candidate.employment} />
 )}

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

 {/* ── HERO CARD ── */}
 <Card variant="default" size="md" className="p-0! overflow-hidden">
 {/* Top accent bar */}
 <div className="h-1 bg-linear-to-r from-[hsl(var(--primary))] to-[hsl(var(--card))]" />
 <div className="p-6">
 <div className="flex items-start gap-4 flex-wrap">
 <Avatar size="xl">
 <AvatarFallback>{initials}</AvatarFallback>
 </Avatar>

 <div className="flex-1 min-w-0">
 {editingIdentity ? (
 <IdentityEditor
 candidate={candidate}
 onClose={() => setEditingIdentity(false)}
 />
 ) : (
 <>
 <div className="flex items-center gap-2 flex-wrap">
 <h1 className="font-semibold text-2xl md:text-3xl font-extrabold tracking-heading-tight text-foreground">
 {fullName}
 </h1>
 {candidate.status && STATUS_LABELS[candidate.status] && (
 <Badge variant={STATUS_VARIANT[candidate.status] ??"neutral"} size="md">
 {STATUS_LABELS[candidate.status]}
 </Badge>
 )}
 {riskProfile && <RiskBadge profile={riskProfile} />}
 <CandidateHighlights candidate={candidate} variant="full" />
 <CompetenceCategoryBadge categoryId={candidate.competence_category_id} slug={candidate.competence_category} size="md" />
 {contactFeature.enabled ? (
 <ContactStatusBadge contactCase={contactCaseQuery.data} size="md" />
 ) : null}
 {candidate.source === "linkedin" && (
 <Badge variant="plum" size="sm">
 <Linkedin className="h-3 w-3" />
 LinkedIn
 </Badge>
 )}
 {candidate.invite_source && (
 <Badge
 variant="soft"
 size="sm"
 title={
 candidate.invite_source.previous_created_by_name
 ? `Przejęty: ${candidate.invite_source.previous_created_by_name} → ${candidate.invite_source.created_by_name} (${formatDate(candidate.invite_source.applied_at)})`
 : `Dodany przez ${candidate.invite_source.created_by_name} (${formatDate(candidate.invite_source.applied_at)})`
 }
 >
 <Link2 className="h-3 w-3" />
 Przez link
 {candidate.invite_source.label
 ? ` · ${candidate.invite_source.label}`
 :""}
 </Badge>
 )}
 <button
 type="button"
 onClick={() => setEditingIdentity(true)}
 className="inline-flex min-h-11 min-w-11 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
 title="Edytuj imię, nazwisko, e-mail i telefon"
 >
 <PencilLine className="h-3.5 w-3.5" />
 Edytuj kontakt
 </button>
 </div>
 {/* Scannable one-liner: title · experience · location · salary ·
 availability — falls back to current_role when no facts resolve. */}
 {(getCandidateSummaryLine(candidate) ?? candidate.current_role) && (
 <p className="text-sm text-foreground mt-0.5">
 {getCandidateSummaryLine(candidate) ?? candidate.current_role}
 </p>
 )}

 {/* Contact row */}
 <div className="flex items-center gap-4 flex-wrap mt-3 text-sm text-foreground">
 {candidate.email && (
 <a
 href={`mailto:${candidate.email}`}
 className="inline-flex min-h-11 min-w-11 items-center gap-1.5 hover:text-primary"
 >
 <Mail className="h-3.5 w-3.5 text-muted-foreground" />
 {candidate.email}
 </a>
 )}
 {candidate.phone && (
 <CallButton
 candidateId={Number(id)}
 phone={candidate.phone}
 compact
 className="min-h-11 min-w-11"
 />
 )}
 {candidate.phone &&
 contactCaseQuery.data &&
 hasRole(currentUser, "tac", "recruiter", "sourcer") &&
 contactCaseQuery.data.owner?.id === currentUser?.id &&
 ["queued", "callback_due"].includes(contactCaseQuery.data.status) ? (
 <Button
 type="button"
 size="sm"
 variant="outline"
 className="min-h-11 min-w-11"
 onClick={() => setContactOutcomeOpen(true)}
 >
 Zaloguj wynik
 </Button>
 ) : null}
 {(() => {
 const headerLoc = formatCandidateLocation(candidate.location);
 return headerLoc ? (
 <span className="inline-flex items-center gap-1.5">
 <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
 {headerLoc}
 </span>
 ) : null;
 })()}
 {candidate.linkedin_url && (
 <a
 href={candidate.linkedin_url}
 target="_blank"
 rel="noreferrer"
 className="inline-flex min-h-11 min-w-11 items-center gap-1.5 hover:text-primary"
 >
 <Linkedin className="h-3.5 w-3.5 text-brand-linkedin" />
 LinkedIn
 </a>
 )}
 </div>

 {/* Tags */}
 {(() => {
 const tagNames: string[] = Array.isArray(candidate.tags)
 ? Array.from(new Set(
 (candidate.tags as unknown[])
 .map((t) => getTagName(t))
 .filter((n): n is string => typeof n === "string"),
 ))
 : [];
 return tagNames.length > 0 ? (
 <div className="flex flex-wrap gap-1 mt-3">
 {tagNames.map((name: string, i: number) => (
 <span
 key={i}
 className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary"
 >
 #{name}
 </span>
 ))}
 </div>
 ) : null;
 })()}
 </>
 )}
 </div>

 {/* Active viewers (presence) — other users currently on this candidate */}
 <ActiveViewers
 resourceType="candidate"
 resourceId={Number.isFinite(Number(id)) ? Number(id) : null}
 viewers={presenceViewers}
 />

 {/* Close button (embedded fallback — when nav strip isn't shown). */}
 {embedded && !showNav && onClose && (
 <button
 type="button"
 onClick={onClose}
 aria-label="Zamknij"
 className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
 >
 <X className="h-5 w-5" />
 </button>
 )}
 </div>

 {/* Action row — primary recruiter tasks stay visible; secondary actions
 collapse into a "Więcej" menu so the strip reads as a clear hierarchy
 instead of one undifferentiated wall of buttons. */}
 <div className="flex items-center gap-2 flex-wrap mt-5">
 <Button
 size="sm"
 variant="primary"
 className="min-h-11 min-w-11"
 onClick={() => setAssignOpen(true)}
 disabled={!candidate}
 >
 <UserPlus className="h-4 w-4" />
 Przypisz do oferty
 </Button>
 {/* Utility cluster — secondary actions collapse into "Więcej" so only the
 primary "Przypisz do oferty" task stays visible in the strip. */}
 <div className="mx-0.5 hidden h-5 w-px bg-border sm:block" />
 {candidate && (
 <PinButton
 candidateId={candidate.id}
 iconOnly
 className="min-h-11 min-w-11"
 />
 )}
 {/* modal={false} is load-bearing: a default (modal) dropdown leaves
 body pointer-events locked while it closes, so a Radix Dialog opened
 from a menu item (Email / interview / CV) is dismissed on the same
 tick when the panel is nested in the drawer Sheet — the exact failure
 issue 533 hit. Dropping the lock lets those dialogs open reliably from the
 menu, so all three can live here instead of crowding the action row. */}
 <DropdownMenu modal={false}>
 <DropdownMenuTrigger asChild>
 <Button size="sm" variant="outline" className="min-h-11 min-w-11">
 Więcej
 <ChevronDown className="h-3.5 w-3.5 opacity-60" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end" className="w-52">
 <DropdownMenuItem
 className="min-h-11"
 disabled={!candidate.email}
 onSelect={() => openFromMenu(() => setEmailOpen(true))}
 >
 <Mail className="h-4 w-4" />
 Email
 </DropdownMenuItem>
 <DropdownMenuItem
 className="min-h-11"
 disabled={!candidate.email}
 title={candidate.email ?"Zaplanuj interview w Outlook (M365)" :"Kandydat nie ma adresu email"}
 onSelect={() => openFromMenu(() => setScheduleOpen(true))}
 >
 <Calendar className="h-4 w-4" />
 Zaplanuj interview
 </DropdownMenuItem>
 <DropdownMenuItem
 className="min-h-11"
 onSelect={() => openFromMenu(() => setCvOpen(true))}
 >
 <FileText className="h-4 w-4" />
 Generuj CV
 </DropdownMenuItem>
 <DropdownMenuSeparator />
 <DropdownMenuItem
 className="min-h-11"
 onSelect={() => openFromMenu(() => setEditOpen(true))}
 >
 <PencilLine className="h-4 w-4" />
 Edytuj
 </DropdownMenuItem>
 <DropdownMenuItem
 className="min-h-11"
 onSelect={() => openFromMenu(() => setMarketplaceOpen(true))}
 >
 <Store className="h-4 w-4" />
 Wrzuć na targ
 </DropdownMenuItem>
 {/* „Usuń kandydata" usunięte (audyt M2 PR1) — hard delete wróci jako
 audytowalny privacy workflow w PR2; do tego czasu użyj blacklisty. */}
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 {/* Key stats moved into ProfilTab "Kluczowe fakty" grid for a single,
 scannable source — see ProfilTab FactTile grid. */}
 </div>
 </Card>

 <CandidateProfileFactsBar candidate={candidate} />

 {/* Only the summary uses a secondary rail. At narrower widths it naturally
 stacks below the main content instead of squeezing cards into a narrow strip. */}
 <div
 className={cn(
 "grid items-start gap-5",
 !embedded && activeTab === "summary" && "xl:grid-cols-[minmax(0,1fr)_320px]",
 )}
 >
 <div className="min-w-0 space-y-5">
 <Card variant="default" size="md" className="p-0! overflow-hidden">
 <TabbedNav
 value={activeTab}
 onValueChange={setActiveTab}
 ariaLabel="Sekcje profilu kandydata"
 overflow="scroll"
 listClassName="hidden max-w-full justify-start px-4 pt-2 md:flex *:shrink-0"
 tabs={[
 { value: "summary", label: "Podsumowanie", icon: User },
 {
 value: "recruitments",
 label: "Rekrutacje",
 icon: Calendar,
 count: history.length || undefined,
 },
 { value: "activity", label: "Aktywność", icon: MessageSquare },
 { value: "matching", label: "Dopasowanie", icon: Sparkles },
 { value: "documents", label: "Pliki i umowy", icon: Files },
 ]}
 >
 <div className="border-b border-border px-4 py-3 md:hidden">
 <label htmlFor="candidate-profile-section" className="sr-only">
 Sekcja profilu
 </label>
 <select
 id="candidate-profile-section"
 value={activeTab}
 onChange={(event) => setActiveTab(event.target.value)}
 className="h-11 w-full rounded-md border border-border bg-card px-3 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring"
 >
 {Object.entries(PROFILE_SECTION_LABELS).map(([value, label]) => (
 <option key={value} value={value}>
 {label}
 </option>
 ))}
 </select>
 </div>

 <div className="p-4 sm:p-5">
 <TabsContent value="summary" className="mt-0 space-y-5">
 <CandidateActivitySummaryCard candidateId={Number(id)} />
 <ProfilTab candidate={candidate} onOpenTab={setActiveTab} />
 <section aria-labelledby="candidate-commercial-data">
 <h2
 id="candidate-commercial-data"
 className="mb-3 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
 >
 Dane handlowe
 </h2>
 <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2">
 <DeferUntilVisible minHeight={44}>
 <RateHistoryWidget candidateId={Number(id)} hideWhenEmpty />
 </DeferUntilVisible>
 <DeferUntilVisible minHeight={44}>
 <ConflictsWidget candidateId={Number(id)} hideWhenEmpty />
 </DeferUntilVisible>
 <DeferUntilVisible minHeight={44}>
 <HiringManagerVetoesWidget candidateId={Number(id)} hideWhenEmpty />
 </DeferUntilVisible>
 </div>
 </section>
 </TabsContent>

 <TabsContent value="recruitments" className="mt-0">
 {historyQuery.isPending ? (
 <SectionLoading label="Ładowanie rekrutacji…" />
 ) : historyQuery.error ? (
 <SectionError
 title="Nie udało się pobrać rekrutacji"
 onRetry={() => historyQuery.refetch()}
 />
 ) : (
 <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
 <div className="lg:col-span-2">
 <RekrutacjeTab
 history={history}
 candidateId={Number(id)}
 candidateName={`${candidate.name} ${candidate.lastname}`}
 focusedJobId={visibleFocusJobId}
 />
 </div>
 <div className="space-y-4">
 <CandidatePipelinesWidget
 candidateId={Number(id)}
 employment={candidate.employment}
 />
 </div>
 </div>
 )}
 </TabsContent>

 <TabsContent value="activity" className="mt-0 space-y-4">
 <SubsectionNav
 label="Widok aktywności"
 items={ACTIVITY_VIEWS.map((value) => ({
 value,
 label: ACTIVITY_LABELS[value],
 }))}
 value={activityView}
 onChange={(value) => setActivityView(value as CandidateActivityView)}
 />
 {activityView === "timeline" && candidate.cv_filename ? (
 <div className="flex justify-end">
 <Button
 size="sm"
 variant="outline"
 aria-pressed={showActivityCv}
 onClick={() => setShowActivityCv((visible) => !visible)}
 >
 <FileText className="h-3.5 w-3.5" />
 {showActivityCv ? "Ukryj CV" : "Pokaż CV obok"}
 </Button>
 </div>
 ) : null}
 {activityView === "timeline" ? (
 timelineQuery.isPending || historyQuery.isPending ? (
 <SectionLoading label="Ładowanie historii aktywności…" />
 ) : timelineQuery.error || historyQuery.error ? (
 <SectionError
 title="Nie udało się pobrać historii aktywności"
 onRetry={() => {
 timelineQuery.refetch();
 historyQuery.refetch();
 }}
 />
 ) : showActivityCv ? (
 <PipelinePane
 candidateId={Number(id)}
 cvFilename={candidate.cv_filename ?? null}
 timeline={timeline ?? []}
 recruitments={history}
 defaultJobId={backJobId}
 noteText={noteText}
 setNoteText={setNoteText}
 onAdd={handleAddNote}
 saving={noteSaving}
 viewers={presenceViewers}
 currentUserId={currentUser?.id}
 setEditing={setPresenceEditing}
 candidateName={candidate.name ?? null}
 candidateLastname={candidate.lastname ?? null}
 />
 ) : (
 <TimelineTab items={timeline ?? []} />
 )
 ) : null}
 {activityView === "notes" ? (
 notesQuery.isPending || historyQuery.isPending ? (
 <SectionLoading label="Ładowanie notatek…" />
 ) : notesQuery.error || historyQuery.error ? (
 <SectionError
 title="Nie udało się pobrać notatek"
 onRetry={() => {
 notesQuery.refetch();
 historyQuery.refetch();
 }}
 />
 ) : (
 <NotatkiTab
 timeline={noteItems}
 recruitments={history}
 defaultJobId={backJobId}
 noteText={noteText}
 setNoteText={setNoteText}
 onAdd={handleAddNote}
 onEdit={handleEditNote}
 onDelete={handleDeleteNote}
 saving={noteSaving}
 viewers={presenceViewers}
 currentUserId={currentUser?.id}
 canModerate={hasRole(currentUser, "admin")}
 setEditing={setPresenceEditing}
 candidateName={candidate.name ?? null}
 candidateLastname={candidate.lastname ?? null}
 />
 )
 ) : null}
 {activityView === "calls" ? (
 callsQuery.error ? (
 <SectionError
 title="Nie udało się pobrać rozmów"
 onRetry={() => callsQuery.refetch()}
 />
 ) : callsQuery.isPending ? (
 <SectionLoading label="Ładowanie rozmów…" />
 ) : (
 <CallsTimeline calls={callsQuery.data ?? []} />
 )
 ) : null}
 {activityView === "chat" ? (
 <CandidateChatTab candidateId={Number(id)} />
 ) : null}
 </TabsContent>

 <TabsContent value="matching" className="mt-0">
 <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
 <div className="min-w-0">
 {historyQuery.isPending ? (
 <SectionLoading label="Ładowanie danych dopasowania…" />
 ) : historyQuery.error ? (
 <SectionError
 title="Nie udało się pobrać danych do dopasowania"
 onRetry={() => historyQuery.refetch()}
 />
 ) : (
 <DopasowanieTab
 candidateId={Number(id)}
 recruitments={history}
 defaultJobId={backJobId}
 />
 )}
 </div>
 <aside className="space-y-4 xl:sticky xl:top-4">
 <SuggestedJobsWidget candidateId={Number(id)} />
 <SuggestedPoolsWidget candidateId={Number(id)} />
 </aside>
 </div>
 </TabsContent>

 <TabsContent value="documents" className="mt-0 space-y-4">
 <SubsectionNav
 label="Pliki i umowy"
 items={DOCUMENT_VIEWS.map((value) => ({
 value,
 label: DOCUMENT_LABELS[value],
 }))}
 value={documentsView}
 onChange={(value) => setDocumentsView(value as CandidateDocumentView)}
 />
 {documentsView === "files" ? (
 <CandidateFilesTab candidateId={Number(id)} />
 ) : contractsQuery.error ? (
 <SectionError
 title="Nie udało się pobrać umów"
 onRetry={() => contractsQuery.refetch()}
 />
 ) : contractsQuery.isPending ? (
 <SectionLoading label="Ładowanie umów…" />
 ) : (
 <UmowaTab
 candidateId={Number(id)}
 candidateName={fullName}
 candidatePhone={candidate.phone ?? null}
 contracts={candidateContracts}
 jdgComplete={Boolean(candidate.legal_name && candidate.nip)}
 onJumpToProfile={() => setActiveTab("summary")}
 />
 )}
 </TabsContent>
 </div>
 </TabbedNav>
 </Card>
 </div>

 {activeTab === "summary" ? (
 <aside
 className={cn(
 "space-y-4",
 !embedded && "xl:sticky xl:top-4",
 )}
 aria-label="Kontekst profilu kandydata"
 >
 <CandidateRecentRecruitmentsCard candidateId={Number(id)} />
 {aiProfileQuery.error ? (
 <SectionError
 title="Podsumowanie screeningów jest niedostępne"
 onRetry={() => aiProfileQuery.refetch()}
 />
 ) : aiProfileQuery.isPending ? (
 <SectionLoading label="Ładowanie podsumowania screeningów…" />
 ) : aiProfile && aiProfile.screening_count > 0 ? (
 <ScreeningSummary aiProfile={aiProfile} />
 ) : null}
 </aside>
 ) : null}
 </div>

 {/* ── Modals ── */}
 <SendEmailV2
 open={emailOpen}
 onOpenChange={setEmailOpen}
 candidateId={Number(id)}
 candidateName={fullName}
 candidateEmail={candidate.email ??""}
 />
 <CVGeneratorV2
 open={cvOpen}
 onOpenChange={setCvOpen}
 candidateId={Number(id)}
 candidateName={fullName}
 />
 <QuickAssignV2
 open={assignOpen}
 onOpenChange={setAssignOpen}
 candidateId={Number(id)}
 candidateName={fullName}
 onAssigned={() => {
 invalidateCandidateMutation(queryClient, id, "assignment");
 }}
 />
 {editOpen && candidate && (
 <EditCandidateModal
 candidate={candidate}
 onClose={() => setEditOpen(false)}
 onSuccess={() => {
 invalidateCandidateMutation(queryClient, id, "edit");
 setEditOpen(false);
 }}
 />
 )}
 <ScreeningSheet
 open={screeningStage !== null}
 onOpenChange={(v) => !v && setScreeningStage(null)}
 stageId={screeningStage ?? 0}
 candidateName={fullName}
 onSubmitted={() => {
 queryClient.invalidateQueries({ queryKey: ["candidate-screenings", id] });
 setScreeningStage(null);
 }}
 />
 <ScheduleInterviewModal
 open={scheduleOpen}
 onOpenChange={setScheduleOpen}
 candidateId={Number(id)}
 candidateName={fullName}
 candidateEmail={candidate.email ?? null}
 />
 {/* Marketplace modal is parent-controlled so its overlay survives the
 "Więcej" dropdown unmounting (its trigger lives inside the menu). */}
 {candidate && (
 <AddToMarketplaceButton
 candidateId={candidate.id}
 candidateName={`${candidate.name} ${candidate.lastname}`}
 hideTrigger
 open={marketplaceOpen}
 onOpenChange={setMarketplaceOpen}
 />
 )}
 <ContactOutcomeSheet
 contactCase={contactCaseQuery.data ?? null}
 open={contactOutcomeOpen}
 onOpenChange={setContactOutcomeOpen}
 onSaved={() => void contactCaseQuery.refetch()}
 onConflict={() => void contactCaseQuery.refetch()}
 />

 </div>
 );
}

// ── Helpers ────────────────────────────────────────────────────────────

function SectionLoading({ label }: { label: string }) {
 return (
 <div
 className="flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-8 text-sm text-muted-foreground"
 aria-busy="true"
 >
 <Loader2 className="h-4 w-4 animate-spin" />
 {label}
 </div>
 );
}

function SectionError({
 title,
 onRetry,
}: {
 title: string;
 onRetry: () => void;
}) {
 return (
 <div
 role="alert"
 className="flex flex-col items-start justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive sm:flex-row sm:items-center"
 >
 <span>{title}</span>
 <Button size="sm" variant="outline" onClick={onRetry}>
 Ponów
 </Button>
 </div>
 );
}

function SubsectionNav({
 label,
 items,
 value,
 onChange,
}: {
 label: string;
 items: Array<{ value: string; label: string }>;
 value: string;
 onChange: (value: string) => void;
}) {
 return (
 <div
 role="tablist"
 aria-label={label}
 className="flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1"
 >
 {items.map((item) => {
 const active = item.value === value;
 return (
 <button
 key={item.value}
 type="button"
 role="tab"
 aria-selected={active}
 onClick={() => onChange(item.value)}
 className={cn(
 "shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
 active
 ? "bg-card text-foreground shadow-xs"
 : "text-muted-foreground hover:bg-accent hover:text-foreground",
 )}
 >
 {item.label}
 </button>
 );
 })}
 </div>
 );
}

function StatTile({ label, value }: { label: string; value: React.ReactNode }) {
 return (
 <div className="rounded-lg bg-background/60 border border-border px-3 py-2.5">
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 {label}
 </div>
 <div className="text-sm font-bold text-foreground mt-0.5">
 {value}
 </div>
 </div>
 );
}

// ─── Dane do umowy (JDG) ─────────────────────────────────────────────────

interface JDGPanelInitial {
 legal_name?: string | null;
 nip?: string | null;
 regon?: string | null;
 business_address?: string | null;
 business_form?: string | null;
}

const BUSINESS_FORM_OPTIONS: { value: string; label: string }[] = [
 { value: "jdg", label: "JDG (jednoosobowa)" },
 { value: "sp_zoo", label: "Sp. z o.o." },
 { value: "sa", label: "S.A." },
 { value: "sc", label: "Spółka cywilna" },
 { value: "osoba_fizyczna", label: "Osoba fizyczna (UoP/zlecenie)" },
];

function JDGPanel({
 candidateId,
 initial,
}: {
 candidateId: number;
 initial: JDGPanelInitial;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const [form, setForm] = useState({
 legal_name: initial.legal_name ??"",
 nip: initial.nip ??"",
 regon: initial.regon ??"",
 business_address: initial.business_address ??"",
 business_form: initial.business_form ??"",
 });

 const dirty =
 form.legal_name !== (initial.legal_name ??"") ||
 form.nip !== (initial.nip ??"") ||
 form.regon !== (initial.regon ??"") ||
 form.business_address !== (initial.business_address ??"") ||
 form.business_form !== (initial.business_form ??"");

 const save = useMutation({
 mutationFn: () =>
 api.patch(`/api/candidates/${candidateId}`, {
 legal_name: form.legal_name || null,
 nip: form.nip || null,
 regon: form.regon || null,
 business_address: form.business_address || null,
 business_form: form.business_form || null,
 }),
 onSuccess: () => {
 showSuccess("Zapisano dane do umowy");
 queryClient.invalidateQueries({ queryKey: candidateQueryKeys.detail(candidateId) });
 },
 onError: () => showError("Nie udało się zapisać danych JDG"),
 });

 return (
 <Card variant="default" size="md">
 <CardHeader className="pb-2!">
 <CardTitle className="text-sm font-semibold uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-2">
 <FileSignature className="h-3.5 w-3.5" />
 Dane do umowy (JDG / firma)
 </CardTitle>
 </CardHeader>
 <CardContent className="space-y-3">
 <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
 <div>
 <Label className="text-xs">Nazwa prawna</Label>
 <Input
 value={form.legal_name}
 onChange={(e) =>
 setForm((f) => ({ ...f, legal_name: e.target.value }))
 }
 placeholder="np. Jan Kowalski JDG"
 />
 </div>
 <div>
 <Label className="text-xs">Forma działalności</Label>
 <select
 className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
 value={form.business_form}
 onChange={(e) =>
 setForm((f) => ({ ...f, business_form: e.target.value }))
 }
 >
 <option value="">— wybierz —</option>
 {BUSINESS_FORM_OPTIONS.map((opt) => (
 <option key={opt.value} value={opt.value}>
 {opt.label}
 </option>
 ))}
 </select>
 </div>
 <div>
 <Label className="text-xs">NIP</Label>
 <Input
 value={form.nip}
 onChange={(e) => setForm((f) => ({ ...f, nip: e.target.value }))}
 placeholder="np. PL5252000000"
 />
 </div>
 <div>
 <Label className="text-xs">REGON</Label>
 <Input
 value={form.regon}
 onChange={(e) =>
 setForm((f) => ({ ...f, regon: e.target.value }))
 }
 />
 </div>
 </div>
 <div>
 <Label className="text-xs">Adres siedziby</Label>
 <Textarea
 value={form.business_address}
 onChange={(e) =>
 setForm((f) => ({ ...f, business_address: e.target.value }))
 }
 placeholder="ul. Marszałkowska 1, 00-001 Warszawa"
 rows={2}
 />
 </div>
 <div className="flex justify-end">
 <Button
 size="sm"
 disabled={!dirty || save.isPending}
 onClick={() => save.mutate()}
 >
 {save.isPending ?"Zapisuję…" :"Zapisz"}
 </Button>
 </div>
 </CardContent>
 </Card>
 );
}

// ─── Zakładka Umowa ──────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = {
 draft: "Draft",
 active: "Aktywna",
 ending: "Wygasa",
 ended: "Zakończona",
};

function formatRate(
 amount: number | null | undefined,
 currency: string | null | undefined,
 unit: string | null | undefined,
): string {
 if (amount == null) return"—";
 const unitLabel =
 unit === "hourly" ?"/h" : unit === "daily" ?"/d" :"/mies.";
 return `${amount.toLocaleString("pl-PL")} ${currency ??"PLN"}${unitLabel}`;
}

function UmowaTab({
 candidateId,
 candidateName,
 candidatePhone,
 contracts,
 jdgComplete,
 onJumpToProfile,
}: {
 candidateId: number;
 candidateName: string;
 candidatePhone: string | null;
 contracts: any[];
 jdgComplete: boolean;
 onJumpToProfile: () => void;
}) {
 const sorted = useMemo(() => {
 const order: Record<string, number> = {
 active: 0,
 ending: 1,
 draft: 2,
 ended: 3,
 };
 return [...contracts].sort((a, b) => {
 const so = (order[a.status] ?? 9) - (order[b.status] ?? 9);
 if (so !== 0) return so;
 return (b.start_date ??"").localeCompare(a.start_date ??"");
 });
 }, [contracts]);

 const current = sorted.find(
 (c) => c.status === "active" || c.status === "ending",
 );
 const draft = sorted.find((c) => c.status === "draft");
 const history = sorted.filter((c) => c.status === "ended");
 const [historyOpen, setHistoryOpen] = useState(false);

 return (
 <div className="space-y-5">
 {!jdgComplete && (
 <Card variant="default" size="md" className="border-l-4 border-l-warning">
 <CardContent className="py-3 flex items-center justify-between gap-3 flex-wrap">
 <div className="text-sm flex items-center gap-2 text-foreground">
 <AlertTriangle className="h-4 w-4 text-warning" />
 Brak danych do umowy (nazwa prawna / NIP). Bez nich szablon
 wyrenderuje puste pola.
 </div>
 <Button size="sm" variant="outline" onClick={onJumpToProfile}>
 Uzupełnij w Profilu
 </Button>
 </CardContent>
 </Card>
 )}

 {/* Aktualna umowa */}
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Aktualna umowa
 </h3>
 {current ? (
 <CurrentContractCard
 contract={current}
 candidateName={candidateName}
 candidatePhone={candidatePhone}
 />
 ) : (
 <Card variant="default" size="md">
 <CardContent className="py-6 text-center text-sm text-muted-foreground">
 Brak aktywnej umowy.
 </CardContent>
 </Card>
 )}
 </section>

 {/* Draft */}
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Draft do edycji
 </h3>
 {draft ? (
 <DraftEditor
 contractId={draft.id}
 candidateName={candidateName}
 contractMeta={draft}
 />
 ) : (
 <Card variant="default" size="md">
 <CardContent className="py-6 text-center text-sm text-muted-foreground">
 Brak draftu. Draft tworzy się automatycznie gdy kandydat
 przechodzi w pipeline na status <code>hired</code>, albo można
 utworzyć ręcznie umowę z poziomu listy{""}
 <Link
 href="/contracts"
 className="text-primary underline"
 >
 kontraktów
 </Link>
 .
 </CardContent>
 </Card>
 )}
 </section>

 {/* Historia */}
 {history.length > 0 && (
 <section>
 <button
 type="button"
 onClick={() => setHistoryOpen((v) => !v)}
 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground hover:text-primary flex items-center gap-1"
 >
 {historyOpen ? (
 <ChevronUp className="h-3 w-3" />
 ) : (
 <ChevronDown className="h-3 w-3" />
 )}
 Historia ({history.length})
 </button>
 {historyOpen && (
 <div className="mt-2 space-y-2">
 {history.map((c) => (
 <Card key={c.id} variant="default" size="md">
 <CardContent className="py-3 text-sm flex items-center justify-between gap-2">
 <div>
 <div className="font-medium">
 {c.client_name ?? `Klient #${c.client_id}`}
 </div>
 <div className="text-xs text-muted-foreground">
 {formatDate(c.start_date)} —{""}
 {c.end_date ? formatDate(c.end_date) : "?"} ·{""}
 {c.contract_type?.toUpperCase()}
 </div>
 </div>
 {c.termination_reason && (
 <Badge variant="neutral" size="sm">
 {c.termination_reason}
 </Badge>
 )}
 </CardContent>
 </Card>
 ))}
 </div>
 )}
 </section>
 )}
 </div>
 );
}

function CurrentContractCard({
 contract,
 candidateName,
 candidatePhone,
}: {
 contract: any;
 candidateName: string;
 candidatePhone: string | null;
}) {
 const { showError } = useToast();
 const { data: docs } = useQuery<any[]>({
 queryKey: ["contract-docs", contract.id],
 queryFn: () => contractsApi.documents(contract.id).then((r: any) => r.data),
 });
 const documents = docs ?? [];

 const handleDownload = async (d: any) => {
 try {
 await downloadContractDocument(contract.id, d);
 } catch {
 showError(`Nie udało się pobrać pliku "${d.filename}".`);
 }
 };

 return (
 <Card variant="default" size="md">
 <CardContent className="space-y-4">
 <div className="flex items-start justify-between gap-3 flex-wrap">
 <div>
 <div className="font-semibold text-foreground">
 {contract.client_name ?? `Klient #${contract.client_id}`}
 {contract.project_name ? ` · ${contract.project_name}` :""}
 </div>
 <div className="text-xs text-muted-foreground">
 {formatDate(contract.start_date)} —{""}
 {contract.end_date ? formatDate(contract.end_date) : "open-ended"}
 </div>
 </div>
 <div className="flex gap-2 items-center">
 <Badge
 variant={contract.status === "ending" ?"warning" :"success"}
 size="md"
 >
 {STATUS_LABEL[contract.status] ?? contract.status}
 </Badge>
 <Link
 href={`/contracts/${contract.id}`}
 className="text-xs text-primary underline"
 >
 Zarządzaj kontraktem →
 </Link>
 </div>
 </div>
 <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
 <StatTile
 label="Stawka kandydata"
 value={formatRate(
 contract.rate_candidate,
 contract.currency,
 contract.rate_unit,
 )}
 />
 <StatTile
 label="Stawka klienta"
 value={formatRate(
 contract.rate_client,
 contract.currency,
 contract.rate_unit,
 )}
 />
 <StatTile
 label="Marża"
 value={formatRate(
 contract.margin,
 contract.currency,
 contract.rate_unit,
 )}
 />
 <StatTile
 label="Tryb pracy"
 value={contract.work_mode ??"—"}
 />
 </div>
 <div>
 <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Dokumenty
 </div>
 {documents.length === 0 ? (
 <div className="text-xs text-muted-foreground">
 Brak załączników. Dodasz je z poziomu strony kontraktu.
 </div>
 ) : (
 <ul className="space-y-1">
 {documents.map((d: any) => (
 <li
 key={d.id}
 className="flex items-center justify-between text-sm"
 >
 <span className="flex items-center gap-2">
 <FileText className="h-3.5 w-3.5 text-muted-foreground" />
 {d.filename}
 <Badge variant="neutral" size="sm">
 {d.doc_type}
 </Badge>
 </span>
 <button
 type="button"
 onClick={() => handleDownload(d)}
 className="text-xs text-primary inline-flex items-center gap-1"
 >
 <Download className="h-3 w-3" /> pobierz
 </button>
 </li>
 ))}
 </ul>
 )}
 </div>
 <AutentiEnvelopeCard
 contractId={contract.id}
 candidateName={candidateName}
 candidatePhone={candidatePhone}
 />
 </CardContent>
 </Card>
 );
}

function DraftEditor({
 contractId,
 candidateName,
 contractMeta,
}: {
 contractId: number;
 candidateName: string;
 contractMeta: any;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const [confirmFinalize, setConfirmFinalize] = useState(false);
 const [confirmTemplateId, setConfirmTemplateId] = useState<number | null>(
 null,
 );

 const { data, isLoading } = useQuery<ContractDraftResponse>({
 queryKey: ["contract-draft", contractId],
 queryFn: () => contractsApi.draft.get(contractId).then((r) => r.data),
 });

 const editor = useEditor({
 extensions: [StarterKit],
 content: "",
 editorProps: {
 attributes: {
 class: "prose prose-sm max-w-none min-h-[400px] focus:outline-hidden border border-border rounded-lg bg-card p-4",
 },
 },
 });

 // Hydrate editor when draft is loaded the first time / after re-render swap.
 const lastLoadedSig = useRef<string | null>(null);
 useEffect(() => {
 if (!editor || !data) return;
 const sig = `${data.template_id ??""}:${data.updated_at ??""}`;
 if (sig === lastLoadedSig.current) return;
 lastLoadedSig.current = sig;
 editor.commands.setContent(data.content_html ??"<p></p>", false);
 }, [editor, data]);

 // Debounced autosave for manual edits.
 const dirtyRef = useRef(false);
 const saveMutation = useMutation({
 mutationFn: (html: string) =>
 contractsApi.draft.update(contractId, { content_html: html }),
 onSuccess: () => {
 showSuccess("Zapisano draft");
 queryClient.invalidateQueries({ queryKey: ["contract-draft", contractId] });
 },
 onError: () => showError("Nie udało się zapisać draftu"),
 });

 useEffect(() => {
 if (!editor) return;
 const handler = () => {
 dirtyRef.current = true;
 };
 editor.on("update", handler);
 return () => {
 editor.off("update", handler);
 };
 }, [editor]);

 useEffect(() => {
 if (!editor) return;
 const id = setInterval(() => {
 if (dirtyRef.current && !saveMutation.isPending) {
 dirtyRef.current = false;
 saveMutation.mutate(editor.getHTML());
 }
 }, 2000);
 return () => clearInterval(id);
 }, [editor, saveMutation]);

 const swapTemplate = useMutation({
 mutationFn: (templateId: number) =>
 contractsApi.draft.update(contractId, { template_id: templateId }),
 onSuccess: () => {
 showSuccess("Wczytano nowy szablon");
 lastLoadedSig.current = null; // force editor re-hydration
 queryClient.invalidateQueries({ queryKey: ["contract-draft", contractId] });
 },
 onError: () => showError("Nie udało się wczytać szablonu"),
 });

 const finalize = useMutation({
 mutationFn: () => contractsApi.draft.finalize(contractId),
 onSuccess: () => {
 showSuccess("Umowa sfinalizowana — status: aktywna");
 setConfirmFinalize(false);
 queryClient.invalidateQueries({
 queryKey: ["candidate-contracts"],
 });
 queryClient.invalidateQueries({
 queryKey: ["contract-draft", contractId],
 });
 },
 onError: (err: unknown) => {
 const detail =
 err && typeof err === "object" &&"response" in err
 ? (err as any).response?.data?.detail
 : null;
 if (detail && typeof detail === "object" && Array.isArray(detail.missing)) {
 showError(`Uzupełnij wymagane pola: ${detail.missing.join(",")}`);
 } else {
 showError("Nie udało się sfinalizować draftu");
 }
 },
 });

 if (isLoading || !data) {
 return (
 <Card variant="default" size="md">
 <CardContent className="py-6 text-center text-sm text-muted-foreground">
 Ładowanie draftu…
 </CardContent>
 </Card>
 );
 }

 const lastSaved = data.updated_at
 ? `zapisano ${formatRelativeTime(data.updated_at)}`
 :"jeszcze nie zapisano";

 return (
 <Card variant="default" size="md">
 <CardContent className="space-y-3">
 <div className="flex items-start justify-between gap-3 flex-wrap">
 <div className="min-w-0">
 <div className="text-sm text-muted-foreground">
 Draft umowy dla <strong>{candidateName}</strong> — kontrakt #
 {contractId}
 {contractMeta.client_name
 ? ` (${contractMeta.client_name})`
 :""}
 </div>
 <div className="text-xs text-muted-foreground">
 {lastSaved}
 {data.updated_by_name ? ` przez ${data.updated_by_name}` :""}
 </div>
 </div>
 <div className="flex items-center gap-2 flex-wrap">
 <select
 className="rounded-lg border border-border bg-card px-2 py-1 text-xs"
 value={data.template_id ??""}
 onChange={(e) => {
 const newId = Number(e.target.value);
 if (newId && newId !== data.template_id) {
 setConfirmTemplateId(newId);
 }
 }}
 >
 <option value="">— wybierz szablon —</option>
 {data.available_templates.map((t) => (
 <option key={t.id} value={t.id}>
 {t.name}
 {t.is_default ?"(domyślny)" :""}
 </option>
 ))}
 </select>
 <Button
 size="sm"
 variant="outline"
 onClick={async () => {
 // Print view is Bearer-guarded — raw window.open → white
 // "Not authenticated" page. Fetch HTML with auth → blob URL.
 try {
 await openAuthenticatedFile(
 `/api/contracts/${contractId}/draft/render-pdf`,
 "text/html",
 );
 } catch {
 showError("Nie udało się otworzyć umowy do druku.");
 }
 }}
 disabled={!data.content_html}
 title="Otwiera HTML w nowej karcie z auto-print → Save as PDF"
 >
 <Printer className="h-3.5 w-3.5" /> Drukuj / PDF
 </Button>
 <Button
 size="sm"
 onClick={() => setConfirmFinalize(true)}
 disabled={!data.content_html || finalize.isPending}
 >
 <CheckCircle2 className="h-3.5 w-3.5" /> Sfinalizuj umowę
 </Button>
 </div>
 </div>

 {data.available_templates.length === 0 && (
 <div className="flex items-center gap-1 text-xs text-warning-muted-foreground">
 <AlertTriangle className="h-3.5 w-3.5" />
 Brak szablonu dla typu <code>{contractMeta.contract_type}</code>.
 Dodaj szablon w panelu administracyjnym.
 </div>
 )}

 <EditorContent editor={editor} />

 {saveMutation.isPending && (
 <div className="text-xs text-muted-foreground flex items-center gap-1">
 <RefreshCcw className="h-3 w-3 animate-spin" /> Zapisywanie…
 </div>
 )}
 </CardContent>

 {/* Modal: confirm template swap (overwrites manual edits) */}
 {confirmTemplateId !== null && (
 <ConfirmModal
 title="Wczytać nowy szablon ? "
 message="Przełączenie szablonu nadpisze obecną treść draftu. Zapisane edycje zostaną stracone."
 confirmLabel="Wczytaj szablon"
 onConfirm={() => {
 swapTemplate.mutate(confirmTemplateId);
 setConfirmTemplateId(null);
 }}
 onCancel={() => setConfirmTemplateId(null)}
 />
 )}

 {/* Modal: confirm finalize */}
 {confirmFinalize && (
 <ConfirmModal
 title="Sfinalizować draft ? "
 message="Bieżąca treść zostanie zapisana jako dokument umowy, a status kontraktu zmieni się z draft na active. Edycja w tym widoku nie będzie już możliwa."
 confirmLabel={finalize.isPending ?"Finalizuję…" :"Tak, finalizuj"}
 onConfirm={() => finalize.mutate()}
 onCancel={() => setConfirmFinalize(false)}
 />
 )}
 </Card>
 );
}

function ConfirmModal({
 title,
 message,
 confirmLabel,
 onConfirm,
 onCancel,
}: {
 title: string;
 message: string;
 confirmLabel: string;
 onConfirm: () => void;
 onCancel: () => void;
}) {
 return (
 <div
 className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40"
 onClick={onCancel}
 >
 <Card
 variant="default"
 size="md"
 className="max-w-md w-full mx-4"
 onClick={(e: React.MouseEvent) => e.stopPropagation()}
 >
 <CardHeader>
 <CardTitle>{title}</CardTitle>
 </CardHeader>
 <CardContent className="space-y-4">
 <p className="text-sm text-foreground">{message}</p>
 <div className="flex justify-end gap-2">
 <Button variant="outline" size="sm" onClick={onCancel}>
 Anuluj
 </Button>
 <Button size="sm" onClick={onConfirm}>
 {confirmLabel}
 </Button>
 </div>
 </CardContent>
 </Card>
 </div>
 );
}

/** Compact "key facts" tile — variant of StatTile that accepts an icon and
 *  only renders when it has a value (keeps the facts grid free of "—" noise). */
function FactTile({
 icon,
 label,
 value,
}: {
 icon: React.ReactNode;
 label: string;
 value: React.ReactNode;
}) {
 return (
 <div className="rounded-lg bg-background/60 border border-border px-3 py-2.5">
 <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground flex items-center gap-1">
 {icon}
 {label}
 </div>
 <div className="text-sm font-bold text-foreground mt-0.5">{value}</div>
 </div>
 );
}

/** Coerce verified_tech (Optional[Any]) into a clean string list. */
function verifiedTechList(candidate: any): string[] {
 const raw = candidate.verified_tech;
 if (!Array.isArray(raw)) return [];
 const out: string[] = [];
 for (const item of raw) {
 if (typeof item === "string" && item.trim()) out.push(item.trim());
 else if (item && typeof item === "object") {
 const v = (item.name ?? item.tech ?? item.skill) as unknown;
 if (typeof v === "string" && v.trim()) out.push(v.trim());
 }
 }
 return out;
}

// „Stawka do klienta" (cena, za jaką kandydat został/zostanie wysłany do
// klienta) — wyniesiona na zakładkę Profil (domyślny widok kandydata).
// Wcześniej kontrolka żyła wyłącznie w podzakładce Rekrutacje jako mały link
// „Uzupełnij", więc użytkownicy jej nie znajdowali. Pokazujemy ją jako wyraźną
// sekcję per rekrutacja. Współdzieli cache historii z zakładką Rekrutacje
// (ten sam queryKey ["candidate-history", String(id)]) — bez podwójnego fetcha.
function SellRatePanel({
 candidateId,
 onOpenTab,
}: {
 candidateId: number;
 onOpenTab?: (tab: string) => void;
}) {
 const { visibleData: historyRaw } = useCandidateHistoryQuery(
 candidateId,
 !!candidateId,
 );
 const jobs: any[] = Array.isArray(historyRaw)
 ? historyRaw
 : (historyRaw?.jobs ?? []);
 // Brak rekrutacji = nie ma do kogo wysyłać, więc panel się nie pokazuje
 // (kandydat luzem w bazie sourcingowej nie zaśmieca profilu pustą kartą).
 if (jobs.length === 0) return null;

 // Aktywne rekrutacje (otwarta oferta) na górze; w grupie najświeższe pierwsze.
 const sorted = [...jobs].sort((a, b) => {
 const aOpen = a.job_status === "open" ? 0 : 1;
 const bOpen = b.job_status === "open" ? 0 : 1;
 if (aOpen !== bOpen) return aOpen - bOpen;
 return String(b.last_seen ?? "").localeCompare(String(a.last_seen ?? ""));
 });

 return (
 <Card variant="default" size="md">
 <div>
 <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5">
 <Wallet className="h-4 w-4 text-primary" />
 Stawka do klienta
 </h3>
 <p className="text-xs text-muted-foreground mt-0.5">
 Cena, za jaką proponujesz kandydata klientowi — osobno dla każdej
 rekrutacji. Uzupełnij ją przy wysyłce CV do klienta.
 </p>
 </div>
 <div className="mt-2 divide-y divide-border">
 {sorted.map((job) => (
 <div key={job.job_id} className="pt-2 first:pt-0">
 <div className="flex items-center gap-2 flex-wrap">
 <span className="text-sm font-medium text-foreground">
 {job.job_title ?? "Rekrutacja"}
 </span>
 {job.latest_stage && (
 <Badge size="sm" variant="soft">
 {job.latest_stage}
 </Badge>
 )}
 </div>
 <RecruitmentRateRow
 candidateId={candidateId}
 jobId={job.job_id}
 clientRate={job.client_rate ?? null}
 expectedRate={job.expected_rate ?? null}
 />
 </div>
 ))}
 </div>
 {onOpenTab && (
 <button
 type="button"
 onClick={() => onOpenTab("rekrutacje")}
 className="mt-3 text-xs text-primary hover:underline"
 >
 Otwórz zakładkę Rekrutacje →
 </button>
 )}
 </Card>
 );
}

function ProfilTab({
 candidate,
 onOpenTab,
}: {
 candidate: any;
 onOpenTab?: (tab: string) => void;
}) {
 // Defensive: legacy/imported candidates may have these as string/object
 // instead of array (e.g. Traffit-imported with raw text). Array.isArray
 // guard prevents `string.map is not a function` crash.
 const skills: any[] = Array.isArray(candidate.skills) ? candidate.skills : [];
 // Backfill (May 2026) injects a NULL placeholder at experience[0] for
 // Traffit candidates with only past employers — keeps `experience[0].company`
 // out of the "obecna firma" filter. The placeholder has all fields null, so
 // drop it from UI display (no empty card).
 const experience: any[] = (
 Array.isArray(candidate.experience) ? candidate.experience : []
 ).filter((e: any) => {
 if (!e || typeof e !== "object") return false;
 return Boolean(
 e.role || e.title || e.company || e.start || e.start_date ||
 e.end || e.end_date || e.desc || e.description,
 );
 });
 const aiSummary: string | null = candidate.ai_summary ?? null;
 const aiCompanies: string[] = Array.isArray(candidate.cv_extracted_data?.companies)
 ? candidate.cv_extracted_data.companies
 : [];
 const aiSource: string = candidate.cv_extracted_data?._source ??"";
 const aiBadge = aiSource.startsWith("claude") || aiSource.startsWith("ollama");
 const education = getEducationList(candidate);
 const verifiedTech = verifiedTechList(candidate);
 const verifiedSet = new Set(verifiedTech.map((t) => t.toLowerCase()));
 const title = getCurrentTitle(candidate);
 const expLabel = getExperienceLabel(candidate.years_it_experience);

 // Mini activity feed — last 5 events, so the recruiter sees recent history
 // without switching to the Timeline tab (Traffit's Podsumowanie centerpiece).
 const { data: feedRaw } = useQuery<{ timeline?: any[] } | any[]>({
 queryKey: candidateQueryKeys.timeline(candidate.id, 5),
 queryFn: () =>
 api
 .get(`/api/candidates/${candidate.id}/timeline?limit=5`)
 .then((r) => r.data),
 enabled: !!candidate.id,
 staleTime: 30_000,
 });
 const feed: any[] = Array.isArray(feedRaw)
 ? feedRaw
 : (feedRaw?.timeline ?? []);

 // CV quick-open — otwiera podgląd w modalu (PDF/DOCX/obraz) zamiast pobierać.
 // Browser nie renderuje DOCX inline, więc dawny `window.open` na blobie DOCX
 // wymuszał download (ten sam bug co „Podgląd" w zakładce Pliki). Reużywamy
 // FilePreviewModal dla głównego dokumentu kandydata.
 const { showError } = useToast();
 const { data: cvDocs } = useQuery<CandidateDocument[]>({
 queryKey: candidateQueryKeys.cvDocuments(candidate.id),
 queryFn: async () => {
 const res = await api.get<CandidateDocument[]>(
 `/api/candidates/${candidate.id}/documents?kind=cv`,
 );
 return res.data;
 },
 enabled: !!candidate.id,
 staleTime: 30_000,
 });
 const [previewDoc, setPreviewDoc] = useState<CandidateDocument | null>(null);
 const openCv = () => {
 const docs = cvDocs ?? [];
 const primary =
 docs.find((d) => d.is_primary) ??
 docs.find((d) => d.filename === candidate.cv_filename) ??
 docs[0];
 if (primary) {
 setPreviewDoc(primary);
 } else {
 // Brak rekordu dokumentu — przełącz na zakładkę Pliki.
 onOpenTab?.("pliki");
 }
 };

 const [adminOpen, setAdminOpen] = useState(false);
 const hasJdg =
 candidate.legal_name ||
 candidate.nip ||
 candidate.regon ||
 candidate.business_address ||
 candidate.business_form;

 const facts: Array<{ icon: React.ReactNode; label: string; value: React.ReactNode }> = [];
 if (title) facts.push({ icon: <User className="h-3 w-3" />, label: "Stanowisko", value: title });
 if (expLabel)
 facts.push({
 icon: <Gauge className="h-3 w-3" />,
 label: "Doświadczenie",
 value: <Badge size="sm" variant={expLabel.variant}>{expLabel.label}</Badge>,
 });

 return (
 <>
 <div className="space-y-6">
 {/* 1. Key facts — scannable grid (only tiles with data) */}
 {facts.length > 0 && (
 <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
 {facts.map((f) => (
 <FactTile key={f.label} icon={f.icon} label={f.label} value={f.value} />
 ))}
 </div>
 )}

 {/* 1.5 Stawka do klienta — cena wysłania kandydata do klienta (per
 rekrutacja). Wyniesione z zakładki Rekrutacje, bo użytkownik nie
 zaglądał do podzakładki i nie znajdował kontrolki „Uzupełnij". */}
 <SellRatePanel candidateId={candidate.id} onOpenTab={onOpenTab} />

 {/* 2. Ostatnia aktywność — mini feed (last 5) */}
 {feed.length > 0 && (
 <section>
 <div className="flex items-center justify-between mb-2">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 Ostatnia aktywność
 </h3>
 <button
 type="button"
 onClick={() => onOpenTab?.("timeline")}
 className="text-xs font-medium text-primary hover:underline"
 >
 Cała historia →
 </button>
 </div>
 <div className="space-y-0 rounded-lg bg-background/40 border border-border px-3">
 {feed.slice(0, 5).map((item: any, i: number) => (
 <div
 key={`${item.type}-${item.id}-${i}`}
 className="flex gap-2.5 py-2 border-b border-border/40 last:border-0"
 >
 <MessageSquare className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
 <div className="flex-1 min-w-0">
 <div className="flex items-baseline gap-2">
 <span className="text-xs font-medium text-foreground truncate">
 {timelineItemLabel(item)}
 </span>
 <span className="ml-auto text-[11px] text-muted-foreground shrink-0">
 {item.timestamp ? formatRelativeTime(item.timestamp) : ""}
 </span>
 </div>
 {item.content && (
 <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
 {unwrapNoteContent(item.content_rendered ?? item.content)}
 </p>
 )}
 </div>
 </div>
 ))}
 </div>
 </section>
 )}

 {/* 3. CV — quick access card */}
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 CV
 </h3>
 <div className="flex items-center gap-3 rounded-lg bg-background/40 border border-border p-3">
 <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
 <div className="flex-1 min-w-0">
 {candidate.cv_filename ? (
 <>
 <div className="text-sm font-medium text-foreground truncate">
 {candidate.cv_filename}
 </div>
 {candidate.cv_parsed_at && (
 <div className="text-[11px] text-muted-foreground">
 Sparsowane {formatRelativeTime(candidate.cv_parsed_at)}
 </div>
 )}
 </>
 ) : (
 <span className="text-sm text-muted-foreground">Brak CV w profilu</span>
 )}
 </div>
 {candidate.cv_filename ? (
 <Button size="sm" variant="outline" onClick={openCv}>
 <FileText className="h-3.5 w-3.5" />
 Otwórz
 </Button>
 ) : (
 <Button size="sm" variant="ghost" onClick={() => onOpenTab?.("pliki")}>
 Pliki →
 </Button>
 )}
 </div>
 </section>

 {/* 4. Podsumowanie AI — truncated */}
 {aiSummary && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2">
 Podsumowanie AI
 {aiBadge && (
 <Badge size="sm" variant="info">
 AI
 </Badge>
 )}
 </h3>
 <ExpandableText text={aiSummary} maxLines={3} />
 </section>
 )}

 {/* 5. O sobie — truncated */}
 {candidate.about && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 O sobie
 </h3>
 <ExpandableText text={candidate.about} maxLines={3} />
 </section>
 )}

 {/* 6. Umiejętności — grouped (verified vs declared) */}
 {skills.length > 0 && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Umiejętności
 </h3>
 {verifiedTech.length > 0 && (
 <div className="mb-2">
 <div className="mb-1 text-[11px] font-medium text-success-muted-foreground">
 Zweryfikowane
 </div>
 <div className="flex flex-wrap gap-2">
 {verifiedTech.map((t, i) => (
 <Badge key={i} size="sm" variant="success" className="gap-1">
 <CheckCircle2 className="h-3 w-3" />
 {t}
 </Badge>
 ))}
 </div>
 </div>
 )}
 <div className="flex flex-wrap gap-2">
 {skills.map((s: any, i: number) => (
 <div
 key={i}
 className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card border border-border"
 >
 <span className="text-sm font-medium text-foreground">
 {s.name}
 </span>
 {s.level && (
 <Badge size="sm" variant={SKILL_LEVEL_VARIANT[s.level] ??"neutral"}>
 {s.level}
 </Badge>
 )}
 {s.name && verifiedSet.has(String(s.name).toLowerCase()) && (
 <CheckCircle2 className="h-3 w-3 text-success" />
 )}
 {s.years && (
 <span className="text-[10px] text-muted-foreground">{s.years}l</span>
 )}
 </div>
 ))}
 </div>
 </section>
 )}

 {/* 7. Doświadczenie zawodowe — desc truncated */}
 {experience.length > 0 && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-3 flex items-center gap-2">
 Doświadczenie zawodowe
 {aiBadge && (
 <Badge size="sm" variant="info">
 AI
 </Badge>
 )}
 </h3>
 <div className="space-y-3">
 {experience.map((exp: any, i: number) => {
 const role = exp.role ?? exp.title ??"";
 const company = exp.company ??"";
 const start = exp.start ?? exp.start_date ??"";
 const end = exp.end ?? exp.end_date ??"";
 const desc = exp.desc ?? exp.description ??"";
 const expLoc = exp.location ??"";
 return (
 <div
 key={i}
 className="rounded-lg bg-background/40 border border-border p-3"
 >
 <div className="flex items-start justify-between gap-2 flex-wrap">
 <div className="min-w-0">
 {role && <div className="font-medium text-foreground">{role}</div>}
 <div className="text-xs text-muted-foreground">
 {company}
 {expLoc ? ` · ${expLoc}` :""}
 </div>
 </div>
 {(start || end) && (
 <div className="text-xs text-muted-foreground whitespace-nowrap">
 {start ? formatDate(start) : ""} —{""}
 {end ? formatDate(end) : "obecnie"}
 </div>
 )}
 </div>
 {desc && <ExpandableText text={desc} maxLines={2} className="mt-2" />}
 </div>
 );
 })}
 </div>
 </section>
 )}

 {/* 8. Wykształcenie (NOWE) */}
 {education.length > 0 && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2">
 <GraduationCap className="h-3.5 w-3.5" />
 Wykształcenie
 </h3>
 <div className="space-y-2">
 {education.map((edu, i) => (
 <div
 key={i}
 className="rounded-lg bg-background/40 border border-border p-3"
 >
 <div className="font-medium text-foreground text-sm">
 {edu.degree || edu.field || "—"}
 {edu.field && edu.degree ? ` · ${edu.field}` :""}
 </div>
 <div className="text-xs text-muted-foreground">
 {edu.school}
 {edu.year ? ` · ${edu.year}` :""}
 </div>
 </div>
 ))}
 </div>
 </section>
 )}

 {/* Firmy z CV — kept (AI-parsed), only when present */}
 {aiCompanies.length > 0 && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2">
 Firmy z CV
 {aiBadge && (
 <Badge size="sm" variant="info">
 AI
 </Badge>
 )}
 </h3>
 <div className="flex flex-wrap gap-2">
 {aiCompanies.map((name: string, i: number) => (
 <div
 key={i}
 className="inline-flex items-center px-3 py-1.5 rounded-lg bg-card border border-border"
 >
 <span className="text-sm font-medium text-foreground">{name}</span>
 </div>
 ))}
 </div>
 </section>
 )}

 {/* 10. Szczegóły administracyjne — collapsible, panels render only if relevant */}
 <section className="rounded-lg border border-border">
 <button
 type="button"
 onClick={() => setAdminOpen((v) => !v)}
 className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground hover:bg-background/40"
 aria-expanded={adminOpen}
 >
 Szczegóły administracyjne
 {adminOpen ? (
 <ChevronUp className="h-4 w-4" />
 ) : (
 <ChevronDown className="h-4 w-4" />
 )}
 </button>
 {adminOpen && (
 <div className="p-3 space-y-4 border-t border-border">
 <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
 <CandidateEngagementPanel
 candidateId={candidate.id}
 initial={{
 is_ambassador: candidate.is_ambassador,
 wants_to_verify_candidates: candidate.wants_to_verify_candidates,
 open_to_side_projects: candidate.open_to_side_projects,
 open_to_sales_support: candidate.open_to_sales_support,
 open_to_expert_consult: candidate.open_to_expert_consult,
 open_to_side_projects_updated_at:
 candidate.open_to_side_projects_updated_at,
 open_to_sales_support_updated_at:
 candidate.open_to_sales_support_updated_at,
 open_to_expert_consult_updated_at:
 candidate.open_to_expert_consult_updated_at,
 engagement_notes: candidate.engagement_notes,
 }}
 />
 <CandidateLocationPanel
 candidateId={candidate.id}
 initial={{
 city: candidate.city,
 country: candidate.country,
 region: candidate.region,
 hub_city: candidate.hub_city,
 }}
 />
 </div>
 <div className="rounded-xl bg-card border border-border p-4">
 <CandidateSourcesPanel candidateId={candidate.id} />
 </div>
 {hasJdg && (
 <JDGPanel
 candidateId={candidate.id}
 initial={{
 legal_name: candidate.legal_name,
 nip: candidate.nip,
 regon: candidate.regon,
 business_address: candidate.business_address,
 business_form: candidate.business_form,
 }}
 />
 )}
 <LinkedinSyncPanel candidate={candidate} />
 </div>
 )}
 </section>
 </div>
 <FilePreviewModal
 documents={cvDocs ?? []}
 initialDocumentId={previewDoc?.id ?? null}
 candidateId={candidate.id}
 onClose={() => setPreviewDoc(null)}
 onDownload={(d) =>
 downloadDocumentBlob(candidate.id, d).catch(() =>
 showError("Nie udało się pobrać pliku."),
 )
 }
 />
 </>
 );
}

const TIMELINE_LABEL: Record<string, string> = {
 note: "Notatka",
 stage_change: "Zmiana etapu",
 activity: "Aktywność",
 user_activity: "Akcja użytkownika",
};

// 0045_rejection_emails — map scheduler activity actions to Polish labels.
const REJECTION_EMAIL_ACTION_LABELS: Record<string, string> = {
 rejection_email_scheduled: "Zaplanowano email odrzucenia (wyśle się za 15 min)",
 rejection_email_sent: "Wysłano email odrzucenia do kandydata",
 rejection_email_cancelled: "Anulowano wysyłkę email odrzucenia",
 rejection_email_skipped: "Email odrzucenia pominięty — brak skrzynki MS365",
 rejection_email_failed: "Email odrzucenia — błąd wysyłki",
};

// Traffit-imported "Plik - dodany"/"Plik - usunięty" activities carry the file
// name inside a double-encoded `details.content` JSON blob
// ({"file":{"name":...},"type":{"name":...}}). Pull the name so the timeline can
// render 'Plik "<nazwa>" dodany' instead of the raw 'traffit:Plik - dodany'.
function traffitFileName(details: unknown): string | null {
 if (!details || typeof details !== "object") return null;
 const content = (details as { content?: unknown }).content;
 if (typeof content !== "string") return null;
 try {
 const parsed = JSON.parse(content);
 const name = parsed?.file?.name;
 return typeof name === "string" && name.trim() ? name : null;
 } catch {
 return null;
 }
}

function timelineItemLabel(item: any): string {
 if (item.type === "note")
 return `Notatka${item.note_type ? ` — ${item.note_type}` :""}${item.job_title ? ` (${item.job_title})` :""}`;
 if (item.type === "stage_change")
 return `Etap: ${item.stage}${item.job_title ? ` (${item.job_title})` :""}`;
 if (item.type === "activity") {
 if (item.action === "applied_via_invite") {
 const owner = item.user_name ??"rekruter";
 const prev = item.previous_created_by_name;
 return prev
 ? `Przejęto opiekę: ${prev} → ${owner} (apply przez link)`
 : `Aplikacja przez link (${owner})`;
 }
 if (
 item.action === "traffit:Plik - dodany" ||
 item.action === "traffit:Plik - usunięty"
 ) {
 const verb = item.action.endsWith("usunięty") ? "usunięty" : "dodany";
 const name = traffitFileName(item.details);
 return name ? `Plik "${name}" ${verb}` : `Plik ${verb}`;
 }
 const rejectionLabel = REJECTION_EMAIL_ACTION_LABELS[item.action];
 if (rejectionLabel) return rejectionLabel;
 return item.action ??"Aktywność";
 }
 if (item.type === "user_activity") return item.action_type ??"Akcja";
 return TIMELINE_LABEL[item.type] ?? item.type ??"Zdarzenie";
}

// ── Timeline (kandydat) — zgrupowany po dniach, czytelne karty zdarzeń ───────
// Wcześniej był to płaski strumień jednakowych wierszy (każdy z tą samą ikoną
// MessageSquare i surową etykietą typu „Etap: rejected") — nieczytelny przy
// kilkudziesięciu zdarzeniach. Teraz: nagłówek dnia + karta na zdarzenie z
// awatarem autora, czytelnym „kto co zrobił" i kolorowymi badge'ami etapów
// (Nowy → Screening), wzorem osi czasu z Traffita.

// Etap → wariant Badge, żeby przejście „Nowy → Screening" czytało się kolorem:
// info (wczesny lejek) → soft (środek) → success/danger (stany końcowe).
const STAGE_BADGE_VARIANT: Record<
  string,
  React.ComponentProps<typeof Badge>["variant"]
> = {
  new: "info",
  contacted: "info",
  prep_call: "info",
  screening: "soft",
  verified: "soft",
  interview: "soft",
  cv_sent: "soft",
  client_review: "soft",
  client_interview: "soft",
  acceptance: "success",
  negotiation: "warning",
  onboarding: "success",
  active: "success",
  hired: "success",
  rejected: "danger",
  withdrawn: "neutral",
  on_hold: "warning",
};

function StageBadge({ stage }: { stage: string }) {
  return (
    <Badge
      size="lg"
      variant={STAGE_BADGE_VARIANT[stage] ?? "neutral"}
      className="font-semibold"
    >
      {stageLabel(stage)}
    </Badge>
  );
}

// Pełna etykieta dnia dla nagłówka grupy — „Środa, 24 czerwca 2026".
const TIMELINE_DAY_FMT = new Intl.DateTimeFormat("pl-PL", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});
// Na karcie pokazujemy godzinę (HH:MM) — w obrębie dnia „Xh temu" to szum.
const TIMELINE_TIME_FMT = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
});

function timelineDayKey(ts?: string | null): string {
  if (!ts) return "no-date";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "no-date";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function timelineDayLabel(ts?: string | null): string {
  if (!ts) return "Bez daty";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "Bez daty";
  const now = new Date();
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const full = TIMELINE_DAY_FMT.format(d);
  const cap = full.charAt(0).toUpperCase() + full.slice(1);
  if (sameDay(d, now)) return `Dziś · ${cap}`;
  if (sameDay(d, yesterday)) return `Wczoraj · ${cap}`;
  return cap;
}

function timelineTime(ts?: string | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : TIMELINE_TIME_FMT.format(d);
}

// Autor zdarzenia — napędza inicjały awatara i pogrubione imię w nagłówku.
function timelineActor(item: any): string | null {
  if (item.type === "stage_change") return item.moved_by_name ?? null;
  if (item.type === "note") return item.author_name ?? null;
  if (item.type === "activity") return item.user_name ?? null;
  return null;
}

function timelineInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Ikona w kółku dla zdarzeń systemowych/importu (bez ludzkiego autora) —
// utrzymuje skanowalność wiersza wg rodzaju zdarzenia.
function TimelineIcon({ item }: { item: any }) {
  let Icon = MessageSquare;
  if (item.type === "stage_change") Icon = ArrowRight;
  else if (item.type === "activity") {
    const action = typeof item.action === "string" ? item.action : "";
    if (action.includes("Plik")) Icon = FileText;
    else if (action.startsWith("rejection_email")) Icon = Mail;
    else if (action === "applied_via_invite") Icon = UserPlus;
  }
  return <Icon className="h-3.5 w-3.5" />;
}

// Dla każdej zmiany etapu — etap, Z którego nastąpiło przejście, wyliczony z
// chronologicznie wcześniejszej zmiany na TEJ SAMEJ rekrutacji (backend wysyła
// tylko etap docelowy). Pozwala renderować „Nowy → Screening" jak w Traffit.
function buildStageFromMap(items: any[]): Map<number, string> {
  const byJob = new Map<number | string, any[]>();
  for (const it of items) {
    if (it.type !== "stage_change") continue;
    const key = it.job_id ?? "—";
    const arr = byJob.get(key);
    if (arr) arr.push(it);
    else byJob.set(key, [it]);
  }
  const fromMap = new Map<number, string>();
  for (const group of byJob.values()) {
    const asc = [...group].sort((a, b) =>
      String(a.timestamp ?? "").localeCompare(String(b.timestamp ?? "")),
    );
    for (let i = 1; i < asc.length; i++) {
      if (asc[i].id != null) fromMap.set(asc[i].id, asc[i - 1].stage);
    }
  }
  return fromMap;
}

// Nagłówek karty: pogrubiony autor + co zrobił. Dla zmian etapu kolorowe
// badge'y „z → do" renderuje TimelineCard w osobnym wierszu.
function TimelineHeadline({
  item,
  fromStage,
}: {
  item: any;
  fromStage?: string;
}) {
  const actor = timelineActor(item);
  if (item.type === "stage_change") {
    return (
      <span className="text-sm text-foreground">
        <span className="font-semibold">{actor ?? "System"}</span>{" "}
        <span className="text-muted-foreground">
          {fromStage ? "zmienił etap" : "przypisał do etapu"}
        </span>
      </span>
    );
  }
  if (item.type === "note") {
    return (
      <span className="text-sm text-foreground">
        <span className="font-semibold">{actor ?? "Notatka"}</span>{" "}
        <span className="text-muted-foreground">dodał notatkę</span>
      </span>
    );
  }
  return (
    <span className="text-sm font-medium text-foreground">
      {timelineItemLabel(item)}
    </span>
  );
}

function TimelineCard({ item, fromStage }: { item: any; fromStage?: string }) {
  const actor = timelineActor(item);
  const useAvatar =
    !!actor && (item.type === "stage_change" || item.type === "note");
  const content = item.content
    ? unwrapNoteContent(item.content_rendered ?? item.content)
    : null;
  const isStage = item.type === "stage_change";
  return (
    <div className="flex gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-xs transition-shadow hover:shadow-md">
      {useAvatar ? (
        <Avatar className="h-8 w-8 shrink-0">
          <AvatarFallback className="bg-primary/10 text-[11px] font-semibold text-primary">
            {timelineInitials(actor as string)}
          </AvatarFallback>
        </Avatar>
      ) : (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <TimelineIcon item={item} />
        </div>
      )}

      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <TimelineHeadline item={item} fromStage={fromStage} />
          </div>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {timelineTime(item.timestamp)}
          </span>
        </div>

        {isStage && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {fromStage ? (
              <>
                <StageBadge stage={fromStage} />
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                <StageBadge stage={item.stage} />
              </>
            ) : (
              <StageBadge stage={item.stage} />
            )}
          </div>
        )}

        {item.job_title && (
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {item.job_title}
          </p>
        )}

        {content && (
          <p className="mt-1.5 whitespace-pre-line text-sm text-foreground">
            {content}
          </p>
        )}

        {item.notes && (
          <p className="mt-1.5 whitespace-pre-line rounded-md bg-muted/50 px-2.5 py-1.5 text-sm italic text-muted-foreground">
            {item.notes}
          </p>
        )}

        {item.rating ? (
          <div className="mt-1.5 flex gap-0.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <Star
                key={n}
                className={cn(
                  "h-3.5 w-3.5",
                  n <= item.rating
                    ? "fill-warning text-warning"
                    : "fill-[hsl(var(--border))] text-[hsl(var(--border))]",
                )}
              />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TimelineTab({ items }: { items: any[] }) {
  const { groups, fromMap } = useMemo(() => {
    const list = Array.isArray(items) ? items : [];
    const stageFrom = buildStageFromMap(list);
    const grouped: { key: string; label: string; items: any[] }[] = [];
    let cur: { key: string; label: string; items: any[] } | null = null;
    for (const item of list) {
      const key = timelineDayKey(item.timestamp);
      if (!cur || cur.key !== key) {
        cur = { key, label: timelineDayLabel(item.timestamp), items: [] };
        grouped.push(cur);
      }
      cur.items.push(item);
    }
    return { groups: grouped, fromMap: stageFrom };
  }, [items]);

  if (!Array.isArray(items) || items.length === 0) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        Brak zdarzeń w timeline.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <section key={group.key} className="space-y-2">
          <div className="flex items-center gap-2">
            <Calendar className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <h4 className="text-xs font-semibold text-muted-foreground">
              {group.label}
            </h4>
            <div className="h-px flex-1 bg-border" />
          </div>
          {group.items.map((item: any, i: number) => (
            <TimelineCard
              key={`${item.type}-${item.id}-${i}`}
              item={item}
              fromStage={
                item.type === "stage_change" && item.id != null
                  ? fromMap.get(item.id)
                  : undefined
              }
            />
          ))}
        </section>
      ))}
    </div>
  );
}

type RecruitmentRate = {
 value: number;
 unit: string | null;
 currency: string | null;
} | null;

type RatePayload = {
 rate_value: number | null;
 rate_unit?: RateUnit;
 rate_currency?: string;
};

// Pojedyncza, edytowalna komórka stawki (wartość + jednostka). Współdzielona
// przez „Stawkę kandydata" (expected_rate) i „Stawkę do klienta" (client_rate).
// Zarządza własnym stanem edycji + mutacją; po zapisie prefix-invalidate
// odświeża historię (skąd parent czyta wartości i liczy marżę).
function EditableRateCell({
 candidateId,
 label,
 rate,
 mutationFn,
 successMessage,
 testIdPrefix,
}: {
 candidateId: number;
 label: string;
 rate: RecruitmentRate;
 mutationFn: (payload: RatePayload) => Promise<unknown>;
 successMessage: string;
 testIdPrefix: string;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const [editing, setEditing] = useState(false);
 const [value, setValue] = useState(
 rate?.value != null ? String(rate.value) :"",
 );
 const [unit, setUnit] = useState<RateUnit>(
 (rate?.unit as RateUnit) ??"monthly",
 );

 const mut = useMutation({
 mutationFn,
 onSuccess: () => {
 showSuccess(successMessage);
 invalidateCandidateMutation(queryClient, candidateId, "rate");
 setEditing(false);
 },
 onError: (e) =>
 showError(
 (e as { response?: { data?: { detail?: string } } })?.response?.data
 ?.detail ??"Nie udało się zapisać stawki",
 ),
 });

 const save = () => {
 const trimmed = value.trim();
 const v = trimmed === "" ? null : Number(trimmed.replace(",","."));
 if (v !== null && (!Number.isFinite(v) || v < 0)) {
 showError("Podaj poprawną kwotę");
 return;
 }
 mut.mutate({ rate_value: v, rate_unit: unit, rate_currency:"PLN" });
 };

 return (
 <div>
 <div className="flex items-center justify-between gap-2">
 <span className="text-muted-foreground">{label}</span>
 {!editing && (
 <button
 type="button"
 onClick={() => setEditing(true)}
 className="text-primary hover:underline"
 data-testid={`${testIdPrefix}-edit`}
 >
 {rate ?"Edytuj" :"Uzupełnij"}
 </button>
 )}
 </div>
 {editing ? (
 <div className="flex items-center gap-1 mt-1 flex-wrap">
 <input
 type="number"
 inputMode="decimal"
 step="0.01"
 min="0"
 value={value}
 onChange={(e) => setValue(e.target.value)}
 placeholder="np. 22000"
 className="w-24 h-8 px-2 rounded border border-border bg-card text-sm focus:outline-hidden focus:ring-2 focus:ring-primary"
 autoFocus
 data-testid={`${testIdPrefix}-input`}
 />
 <select
 value={unit}
 onChange={(e) => setUnit(e.target.value as RateUnit)}
 className="h-8 px-1 rounded border border-border bg-card text-xs"
 >
 <option value="monthly">/mies.</option>
 <option value="daily">/d</option>
 <option value="hourly">/h</option>
 </select>
 <Button
 size="sm"
 disabled={mut.isPending}
 onClick={save}
 data-testid={`${testIdPrefix}-save`}
 >
 Zapisz
 </Button>
 <Button
 size="sm"
 variant="ghost"
 onClick={() => {
 setEditing(false);
 setValue(rate?.value != null ? String(rate.value) :"");
 setUnit((rate?.unit as RateUnit) ??"monthly");
 }}
 >
 Anuluj
 </Button>
 </div>
 ) : (
 <div className="font-medium text-foreground">
 {rate ? formatRate(rate.value, rate.currency, rate.unit) :"—"}
 </div>
 )}
 </div>
 );
}

// Edytowalne stawki per rekrutacja: „Stawka kandydata" (expected_rate,
// oczekiwania kandydata) + „Stawka do klienta" (client_rate, cena wysłania do
// klienta). Obie przez `EditableRateCell`. Marża liczona z wartości z serwera.
function RecruitmentRateRow({
 candidateId,
 jobId,
 clientRate,
 expectedRate,
}: {
 candidateId: number;
 jobId: number;
 clientRate: RecruitmentRate;
 expectedRate: RecruitmentRate;
}) {
 const sameUnit =
 clientRate != null &&
 expectedRate != null &&
 clientRate.unit === expectedRate.unit;
 const margin =
 sameUnit && clientRate != null && expectedRate != null
 ? clientRate.value - expectedRate.value
 : null;

 return (
 <div className="mt-3 pt-3 border-t border-border">
 <div className="grid grid-cols-2 gap-3 text-xs">
 <EditableRateCell
 candidateId={candidateId}
 label="Stawka kandydata"
 rate={expectedRate}
 testIdPrefix="expected-rate"
 successMessage="Zapisano stawkę kandydata"
 mutationFn={(payload) =>
 candidatesApi.setRecruitmentExpectedRate(candidateId, jobId, payload)
 }
 />
 <EditableRateCell
 candidateId={candidateId}
 label="Stawka do klienta"
 rate={clientRate}
 testIdPrefix="client-rate"
 successMessage="Zapisano stawkę do klienta"
 mutationFn={(payload) =>
 candidatesApi.setRecruitmentClientRate(candidateId, jobId, payload)
 }
 />
 </div>
 {margin != null && (
 <div className="mt-2 text-xs text-muted-foreground">
 Marża:{""}
 <span
 className={
 margin >= 0
 ?"font-medium text-success"
 :"font-medium text-destructive"
 }
 >
 {formatRate(margin, clientRate?.currency, clientRate?.unit)}
 </span>
 </div>
 )}
 </div>
 );
}

function RekrutacjeTab({
 history,
 candidateId,
 candidateName,
 focusedJobId,
}: {
 history: any[];
 candidateId: number;
 candidateName: string;
 focusedJobId: number | null;
}) {
 if (!Array.isArray(history) || history.length === 0) {
 return (
 <div className="py-10 text-center text-sm text-muted-foreground">
 Kandydat nie ma aktywnych rekrutacji.
 </div>
 );
 }
 return (
 <div className="space-y-2">
 {history.map((job: any, i: number) => (
 <RekrutacjaCard
 key={job.job_id ?? job.id ?? i}
 job={job}
 candidateId={candidateId}
 candidateName={candidateName}
 focusedJobId={focusedJobId}
 />
 ))}
 </div>
 );
}

function RekrutacjaCard({
 job,
 candidateId,
 candidateName,
 focusedJobId,
}: {
 job: any;
 candidateId: number;
 candidateName: string;
 focusedJobId: number | null;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const stageId: number | null = job.latest_stage_id ?? null;
 const jobId: number = job.job_id ?? job.id;
 const isFocused = focusedJobId === jobId;
 const recruitmentTitleId = `candidate-recruitment-${jobId}-title`;
 const [openOriginal, setOpenOriginal] = useState(false);
 const [openBranded, setOpenBranded] = useState(false);
 const [openShare, setOpenShare] = useState(false);
 const [confirmRefresh, setConfirmRefresh] = useState(false);
 const [confirmRemove, setConfirmRemove] = useState(false);

 const { data: original } = useQuery<CVOriginalSnapshot>({
 queryKey: ["cv-original", stageId],
 queryFn: () =>
 candidateStageCvApi.original.get(stageId as number).then((r) => r.data),
 enabled: stageId != null,
 });

 const { data: branded } = useQuery<CVBrandedState>({
 queryKey: ["cv-branded", stageId],
 queryFn: () =>
 candidateStageCvApi.branded.get(stageId as number).then((r) => r.data),
 enabled: stageId != null && (openBranded || openShare),
 });

 const refreshMut = useMutation({
 mutationFn: () =>
 candidateStageCvApi.original.refresh(stageId as number),
 onSuccess: () => {
 showSuccess("Snapshot CV oryginalnego zaktualizowany");
 queryClient.invalidateQueries({ queryKey: ["cv-original", stageId] });
 setConfirmRefresh(false);
 },
 onError: (e) =>
 showError(
 (e as { response?: { data?: { detail?: string } } })?.response?.data
 ?.detail ??"Błąd podczas odświeżania snapshotu",
 ),
 });

 const removeMut = useMutation({
 mutationFn: () => candidatesApi.removeFromRecruitment(candidateId, jobId),
 onSuccess: () => {
 showSuccess(
 job.job_title
 ? `Kandydat usunięty z rekrutacji „${job.job_title}"`
 :"Kandydat usunięty z rekrutacji",
 );
 // Lista po lewej (zakładka Rekrutacje + badge) oraz panel po prawej
 // („W jakich pipeline'ach…") — oba muszą się odświeżyć.
 queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.historyRoot(candidateId),
 });
 queryClient.invalidateQueries({
 queryKey: candidateQueryKeys.recommendationsRoot(candidateId),
 });
 queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 queryClient.invalidateQueries({
 queryKey: candidatePipelinesQueryKey(candidateId),
 });
 setConfirmRemove(false);
 },
 onError: (e) =>
 showError(
 (e as { response?: { data?: { detail?: string } } })?.response?.data
 ?.detail ??"Błąd podczas usuwania z rekrutacji",
 ),
 });

 const brandedStatus =
 (branded?.status as"none" |"draft" |"finalized" | undefined) ??"none";

 return (
 <div
 id={`candidate-recruitment-${jobId}`}
 role="group"
 aria-labelledby={recruitmentTitleId}
 tabIndex={isFocused ? -1 : undefined}
 aria-current={isFocused ? "true" : undefined}
 data-focused-recruitment={isFocused ? "true" : undefined}
 className={cn(
 "rounded-lg border border-border p-3 transition-colors hover:border-primary/40",
 isFocused && "border-primary ring-2 ring-ring ring-offset-2",
 )}
 >
 <div className="flex items-start justify-between gap-3 flex-wrap">
 <div className="min-w-0 flex-1">
 <Link
 id={recruitmentTitleId}
 href={`/jobs/${job.job_id ?? job.id}`}
 className="font-medium text-foreground hover:underline"
 >
 {job.job_title ?? `Oferta #${job.job_id ?? job.id}`}
 </Link>
 <div className="text-xs text-muted-foreground">
 {job.latest_stage ??"—"}
 {job.first_seen
 ? ` · dodano ${formatDate(job.first_seen)}`
 :""}
 </div>
 {Array.isArray(job.stages) && job.stages.length > 0 && (
 <div className="flex items-center gap-1.5 flex-wrap mt-1.5">
 {job.stages.slice(0, 6).map((s: any, si: number) => (
 <Badge key={si} size="sm" variant="soft">
 {s.stage}
 </Badge>
 ))}
 </div>
 )}
 {/* Powód odrzucenia — tylko gdy rekrutacja ZAKOŃCZYŁA się odrzuceniem
 (latest_stage === "rejected"). Kandydat dodany ponownie po odrzuceniu
 (latest_stage inny) świadomie nie pokazuje tego baneru. */}
 {job.latest_stage === "rejected" && job.rejection_reason && (
 <div className="mt-2 flex items-start gap-1.5 rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
 <Ban className="h-3.5 w-3.5 mt-px shrink-0" />
 <span className="min-w-0">
 <span className="font-medium">Powód odrzucenia:</span>{" "}
 {job.rejection_reason}
 </span>
 </div>
 )}
 <div className="flex items-center gap-1.5 flex-wrap mt-2">
 {original ? (
 original.has_snapshot ? (
 <Badge size="sm" variant="success">
 CV oryginalne
 </Badge>
 ) : (
 <Badge size="sm" variant="warning">
 Brak CV w momencie zgłoszenia
 </Badge>
 )
 ) : null}
 {brandedStatus === "finalized" ? (
 <Badge size="sm" variant="success">
 Brandowane: gotowe
 </Badge>
 ) : brandedStatus === "draft" ? (
 <Badge size="sm" variant="info">
 Brandowane: draft
 </Badge>
 ) : (
 <Badge size="sm" variant="neutral">
 Brandowane: brak
 </Badge>
 )}
 </div>
 </div>
 </div>

 <RecruitmentRateRow
 candidateId={candidateId}
 jobId={job.job_id ?? job.id}
 clientRate={job.client_rate ?? null}
 expectedRate={job.expected_rate ?? null}
 />

 <div className="flex items-center gap-1.5 flex-wrap mt-3 pt-3 border-t border-border">
 {stageId != null ? (
 <>
 <Button
 size="sm"
 variant="outline"
 onClick={() => setOpenOriginal(true)}
 disabled={!original?.has_snapshot}
 >
 Pokaż CV oryginalne
 </Button>
 <Button
 size="sm"
 variant="outline"
 onClick={() => setOpenBranded(true)}
 >
 {brandedStatus === "none"
 ?"Stwórz brandowane"
 :"Edytuj brandowane"}
 </Button>
 <Button
 size="sm"
 disabled={brandedStatus !== "finalized"}
 onClick={() => setOpenShare(true)}
 title={
 brandedStatus !== "finalized"
 ?"Najpierw sfinalizuj brandowane CV"
 : undefined
 }
 >
 Wyślij klientowi
 </Button>
 <Button
 size="sm"
 variant="ghost"
 onClick={() => setConfirmRefresh(true)}
 title="Aktualizuj snapshot oryginalnego z bieżącym CV kandydata"
 >
 <RefreshCcw className="h-3.5 w-3.5" />
 </Button>
 </>
 ) : null}
 <Button
 size="sm"
 variant="ghost"
 onClick={() => setConfirmRemove(true)}
 className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
 title="Usuń kandydata z tej rekrutacji"
 >
 <Trash2 className="h-3.5 w-3.5 mr-1" />
 Usuń z rekrutacji
 </Button>
 </div>

 {openOriginal && stageId != null ? (
 <CVOriginalPreviewModal
 open
 onOpenChange={setOpenOriginal}
 stageId={stageId}
 jobTitle={job.job_title}
 candidateName={candidateName}
 />
 ) : null}
 {openBranded && stageId != null ? (
 <CVBrandedEditModal
 open
 onOpenChange={setOpenBranded}
 stageId={stageId}
 jobTitle={job.job_title}
 candidateName={candidateName}
 />
 ) : null}
 {openShare && stageId != null ? (
 <CVShareLinkModal
 open
 onOpenChange={setOpenShare}
 stageId={stageId}
 candidateName={candidateName}
 />
 ) : null}

 {confirmRefresh ? (
 <Dialog open onOpenChange={() => setConfirmRefresh(false)}>
 <DialogContent size="md">
 <div className="p-5 space-y-3">
 <h3 className="font-medium">Aktualizować snapshot oryginalny?</h3>
 <p className="text-sm text-muted-foreground">
 Zostanie nadpisany aktualną zawartością CV kandydata. Stary
 snapshot przepadnie. Operacja jest logowana w aktywnościach.
 </p>
 <div className="flex justify-end gap-2 pt-2">
 <Button
 variant="ghost"
 size="sm"
 onClick={() => setConfirmRefresh(false)}
 >
 Anuluj
 </Button>
 <Button
 size="sm"
 onClick={() => refreshMut.mutate()}
 disabled={refreshMut.isPending}
 >
 Aktualizuj
 </Button>
 </div>
 </div>
 </DialogContent>
 </Dialog>
 ) : null}

 {confirmRemove ? (
 <Dialog open onOpenChange={() => setConfirmRemove(false)}>
 <DialogContent size="md">
 <div className="p-5 space-y-3">
 <h3 className="font-medium">
 Usunąć kandydata z tej rekrutacji?
 </h3>
 <p className="text-sm text-muted-foreground">
 Kandydat zostanie zdjęty z pipeline'u oferty{" "}
 <span className="font-medium text-foreground">
 {job.job_title ?? `#${jobId}`}
 </span>
 . Usunięta zostanie cała historia jego etapów na tej
 rekrutacji wraz z powiązanymi snapshotami CV
 (oryginalne/brandowane) i linkami do udostępnień. Tej operacji
 nie można cofnąć — kandydata można jednak dodać do rekrutacji
 ponownie. Sam profil kandydata oraz jego umowy pozostają bez
 zmian.
 </p>
 <p className="text-xs text-muted-foreground">
 To nie to samo co odrzucenie — jeśli kandydat brał udział w
 procesie, użyj „Odrzuć" na kanbanie, by zachować historię.
 </p>
 <div className="flex justify-end gap-2 pt-2">
 <Button
 variant="ghost"
 size="sm"
 onClick={() => setConfirmRemove(false)}
 disabled={removeMut.isPending}
 >
 Anuluj
 </Button>
 <Button
 variant="destructive"
 size="sm"
 onClick={() => removeMut.mutate()}
 disabled={removeMut.isPending}
 loading={removeMut.isPending}
 >
 Usuń z rekrutacji
 </Button>
 </div>
 </div>
 </DialogContent>
 </Dialog>
 ) : null}
 </div>
 );
}

/**
 * Unwrap Traffit-imported note content. Some notes have nested
 * `{"content":"<html>"}` (Traffit"Notatka" type with HTML body) or
 * `{"content":{"content":"<html>","state":{...}}}` (state-change notes).
 * Plus strips HTML tags for plain-text rendering in NotatkiTab.
 */
function unwrapNoteContent(raw: unknown): string {
 if (!raw) return"";
 let s = String(raw);
 // Try unwrap up to 2 levels of {content: ...} nesting
 for (let i = 0; i < 2; i++) {
 if (!s.startsWith("{")) break;
 try {
 const parsed = JSON.parse(s);
 if (parsed && typeof parsed === "object" &&"content" in parsed) {
 const inner = (parsed as { content?: unknown }).content;
 if (typeof inner === "string") {
 s = inner;
 continue;
 }
 if (inner && typeof inner === "object" &&"content" in inner) {
 const innerStr = (inner as { content?: unknown }).content;
 if (typeof innerStr === "string") {
 s = innerStr;
 continue;
 }
 }
 }
 break;
 } catch {
 break;
 }
 }
 // Strip HTML tags + normalize whitespace
 return s
 .replace(/<br\s*\/?>/gi, "\n")
 .replace(/<\/p>/gi, "\n\n")
 .replace(/<\/li>/gi, "\n")
 .replace(/<[^>]+>/g, "")
 .replace(/&nbsp;/g, "")
 .replace(/&amp;/g, "&")
 .replace(/&lt;/g, "<")
 .replace(/&gt;/g, ">")
 .replace(/&quot;/g, '"')
 .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) =>
 String.fromCharCode(parseInt(hex, 16)),
 )
 .replace(/\\\//g, "/")
 .replace(/\\n/g, "\n")
 .replace(/\n{3,}/g, "\n\n")
 .trim();
}

// Kompozytor notatki — selektor rekrutacji + pole z @mentions + przycisk.
// Wydzielony z `NotatkiTab`, by ten sam kompozytor działał też w widoku
// „Podgląd" (pipeline) obok timeline'u. Stan wyboru rekrutacji + auto-preset
// z `defaultJobId` żyją tutaj; listę notatek (jeśli jest) renderuje rodzic.
function NoteComposer({
 recruitments = [],
 defaultJobId = null,
 noteText,
 setNoteText,
 onAdd,
 saving,
 viewers = [],
 currentUserId,
 setEditing,
 candidateName,
 candidateLastname,
}: {
 recruitments?: any[];
 defaultJobId?: number | null;
 noteText: string;
 setNoteText: (v: string) => void;
 onAdd: (jobId?: number | null) => void;
 saving: boolean;
 viewers?: PresenceViewer[];
 currentUserId?: number;
 setEditing?: (field: string, active: boolean) => void;
 candidateName?: string | null;
 candidateLastname?: string | null;
}) {
 const recList = useMemo(
 () =>
 Array.isArray(recruitments)
 ? recruitments.filter((r: any) => r && r.job_id != null)
 : [],
 [recruitments],
 );
 const jobTitleById = useMemo(() => {
 const m = new Map<number, string>();
 for (const r of recList) {
 if (r.job_id != null)
 m.set(Number(r.job_id), r.job_title ?? `Oferta #${r.job_id}`);
 }
 return m;
 }, [recList]);

 // Wybrana rekrutacja (null = notatka ogólna). Gdy ustawiona, @mention scope
 // zawęża się do członków joba — spójnie z backendem.
 const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

 // Gdy profil otwarto z pipeline'u (`?from=job&jobId=N`), domyślnie przypnij
 // nową notatkę do tej rekrutacji. Czekamy aż lista rekrutacji się załaduje;
 // aplikujemy raz, żeby nie nadpisywać ręcznego wyboru użytkownika.
 const defaultJobApplied = useRef(false);
 useEffect(() => {
 if (defaultJobApplied.current) return;
 if (defaultJobId == null) return;
 if (recList.length === 0) return;
 defaultJobApplied.current = true;
 if (recList.some((r: any) => Number(r.job_id) === Number(defaultJobId))) {
 setSelectedJobId(Number(defaultJobId));
 }
 }, [defaultJobId, recList]);

 const othersEditingNotes = viewers.filter(
 (v) => v.user_id !== currentUserId && v.editing.includes("notes"),
 );

 const mentionScope: MentionScope =
 selectedJobId != null
 ? { kind: "job", jobId: selectedJobId }
 : { kind: "global" };

 // Bezpiecznik: wklejka formularza z polem "Imię i nazwisko:" wskazującym
 // inną osobę niż otwarty profil (incydent 29.07.2026 — notatka o Marku
 // Szczegodzińskim na profilu Tomasza Jarząba). Tylko ostrzeżenie — zapis
 // nie jest blokowany, bo notatka MOŻE świadomie dotyczyć osoby poleconej.
 const personMismatch = useMemo(
 () => detectNotePersonMismatch(noteText, candidateName, candidateLastname),
 [noteText, candidateName, candidateLastname],
 );

 return (
 <div className="space-y-2">
 {recList.length > 0 && (
 <div className="flex items-center gap-2 flex-wrap">
 <label
 htmlFor="note-recruitment-select"
 className="text-xs text-muted-foreground flex items-center gap-1.5"
 >
 <Target className="h-3.5 w-3.5" />
 Przypisz do rekrutacji:
 </label>
 <select
 id="note-recruitment-select"
 className="rounded-lg border border-border bg-card px-2 py-1 text-xs max-w-88 truncate"
 value={selectedJobId ?? ""}
 onChange={(e) => {
 const v = e.target.value;
 setSelectedJobId(v ? Number(v) : null);
 }}
 aria-label="Przypisz notatkę do rekrutacji"
 >
 <option value="">Notatka ogólna (bez rekrutacji)</option>
 {recList.map((r: any) => (
 <option key={r.job_id} value={r.job_id}>
 {r.job_title ?? `Oferta #${r.job_id}`}
 </option>
 ))}
 </select>
 </div>
 )}
 <MentionTextarea
 value={noteText}
 onChange={setNoteText}
 scope={mentionScope}
 onFocus={() => setEditing?.("notes", true)}
 onBlur={() => setEditing?.("notes", false)}
 placeholder="Nowa notatka… (@email aby oznaczyć osobę)"
 rows={3}
 ariaLabel="Treść nowej notatki"
 />
 {personMismatch ? (
 <div
 role="alert"
 className="flex items-start gap-1.5 rounded-lg border border-warning/40 bg-warning/10 px-2.5 py-2 text-xs text-warning-muted-foreground"
 >
 <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
 <span>
 Notatka wygląda na opis innej osoby („{personMismatch}") niż otwarty
 profil. Upewnij się, że dodajesz ją na właściwym kandydacie.
 </span>
 </div>
 ) : null}
 {othersEditingNotes.length > 0 ? (
 <div className="flex items-center gap-1.5 text-xs text-warning-muted-foreground">
 <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
 {othersEditingNotes.length === 1
 ? `${othersEditingNotes[0].name} edytuje notatki`
 : `${othersEditingNotes.map((v) => v.name).join(",")} edytują notatki`}
 </div>
 ) : null}
 <div className="flex items-center justify-end gap-2">
 {selectedJobId != null && (
 <span className="text-xs text-muted-foreground mr-auto truncate max-w-[60%]">
 Notatka trafi do: {jobTitleById.get(selectedJobId) ?? "rekrutacji"}
 </span>
 )}
 <Button
 size="sm"
 variant="primary"
 onClick={() => onAdd(selectedJobId)}
 loading={saving}
 disabled={!noteText.trim()}
 >
 <Plus className="h-3.5 w-3.5" />
 Dodaj notatkę
 </Button>
 </div>
 </div>
 );
}

// Widok „Podgląd" (pipeline) — domyślny po wejściu z rekrutacji. Lewa kolumna:
// inline podgląd głównego CV; prawa: kompozytor notatki (przypięty do tej
// rekrutacji) + timeline aktywności. Odwzorowuje ekran kandydata z Traffita.
function PipelinePane({
 candidateId,
 cvFilename,
 timeline,
 recruitments = [],
 defaultJobId = null,
 noteText,
 setNoteText,
 onAdd,
 saving,
 viewers = [],
 currentUserId,
 setEditing,
 candidateName,
 candidateLastname,
}: {
 candidateId: number;
 cvFilename?: string | null;
 timeline: any[];
 recruitments?: any[];
 defaultJobId?: number | null;
 noteText: string;
 setNoteText: (v: string) => void;
 onAdd: (jobId?: number | null) => void;
 saving: boolean;
 viewers?: PresenceViewer[];
 currentUserId?: number;
 setEditing?: (field: string, active: boolean) => void;
 candidateName?: string | null;
 candidateLastname?: string | null;
}) {
 const { showError } = useToast();
 const { data: documents } = useQuery<CandidateDocument[]>({
 queryKey: candidateQueryKeys.cvDocuments(candidateId),
 queryFn: async () => {
 const res = await api.get<CandidateDocument[]>(
 `/api/candidates/${candidateId}/documents?kind=cv`,
 );
 return res.data;
 },
 enabled: !!candidateId,
 staleTime: 30_000,
 });

 // Główny dokument: primary → dopasowany po cv_filename → pierwszy z listy.
 const primaryDoc = useMemo<CandidateDocument | null>(() => {
 const docs = documents ?? [];
 return (
 docs.find((d) => d.is_primary) ??
 docs.find((d) => d.filename === cvFilename) ??
 docs[0] ??
 null
 );
 }, [documents, cvFilename]);

 async function handleDownload(doc: CandidateDocument) {
 try {
 await downloadDocumentBlob(candidateId, doc);
 } catch {
 showError("Nie udało się pobrać pliku.");
 }
 }

 return (
 <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-4 items-start">
 {/* Lewa kolumna — CV inline. minmax(0,…) + min-w-0 — bez nich szeroka
 treść timeline'u rozpychała kolumny i CV zwężało się do paru pikseli. */}
 <div className="min-w-0 rounded-lg border border-border overflow-hidden bg-muted/30">
 {primaryDoc ? (
 <div className="flex flex-col h-[78vh]">
 <div className="flex items-center justify-between gap-2 border-b border-border bg-card px-3 py-2">
 <span className="min-w-0 truncate text-sm font-medium text-foreground">
 {primaryDoc.filename}
 </span>
 <button
 type="button"
 onClick={() => handleDownload(primaryDoc)}
 className="inline-flex shrink-0 items-center gap-1 text-sm text-[hsl(var(--accent-primary))] hover:underline"
 title="Pobierz plik na dysk"
 >
 <Download className="h-3.5 w-3.5" />
 Pobierz
 </button>
 </div>
 <FilePreviewContent
 doc={primaryDoc}
 candidateId={candidateId}
 onDownload={handleDownload}
 hidePdfSidebar
 className="flex-1 min-h-0"
 />
 </div>
 ) : (
 <div className="flex h-[40vh] flex-col items-center justify-center gap-2 p-6 text-center">
 <FileText className="h-8 w-8 text-muted-foreground" />
 <p className="text-sm text-muted-foreground">
 Brak CV w profilu kandydata.
 </p>
 </div>
 )}
 </div>

 {/* Prawa kolumna — notatka + timeline */}
 <div className="space-y-4 min-w-0">
 <NoteComposer
 recruitments={recruitments}
 defaultJobId={defaultJobId}
 noteText={noteText}
 setNoteText={setNoteText}
 onAdd={onAdd}
 saving={saving}
 viewers={viewers}
 currentUserId={currentUserId}
 setEditing={setEditing}
 candidateName={candidateName}
 candidateLastname={candidateLastname}
 />
 <Separator />
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Aktywność
 </h3>
 <div className="max-h-[52vh] overflow-y-auto pr-1">
 <TimelineTab items={timeline ?? []} />
 </div>
 </div>
 </div>
 </div>
 );
}

function NotatkiTab({
 timeline,
 recruitments = [],
 defaultJobId = null,
 noteText,
 setNoteText,
 onAdd,
 onEdit,
 onDelete,
 saving,
 viewers = [],
 currentUserId,
 canModerate = false,
 setEditing,
 candidateName,
 candidateLastname,
}: {
 timeline: any[];
 recruitments?: any[];
 defaultJobId?: number | null;
 noteText: string;
 setNoteText: (v: string) => void;
 onAdd: (jobId?: number | null) => void;
 onEdit: (noteId: number, content: string) => Promise<boolean>;
 onDelete: (noteId: number) => Promise<boolean>;
 saving: boolean;
 viewers?: PresenceViewer[];
 currentUserId?: number;
 canModerate?: boolean;
 setEditing?: (field: string, active: boolean) => void;
 candidateName?: string | null;
 candidateLastname?: string | null;
}) {
 const items = Array.isArray(timeline) ? timeline : [];
 const notes = items.filter((t: any) => t.type === "note");

 // Lista rekrutacji kandydata (z /history) — do selektora "przypisz notatkę
 // do rekrutacji". `recruitments` jest już posortowane most-recent-first.
 // Memo, by referencja była stabilna (deps useMemo/useEffect poniżej).
 const recList = useMemo(
 () =>
 Array.isArray(recruitments)
 ? recruitments.filter((r: any) => r && r.job_id != null)
 : [],
 [recruitments],
 );
 const jobTitleById = useMemo(() => {
 const m = new Map<number, string>();
 for (const r of recList) {
 if (r.job_id != null) m.set(Number(r.job_id), r.job_title ?? `Oferta #${r.job_id}`);
 }
 return m;
 }, [recList]);

 // Edycja/usuwanie istniejących notatek (inline). editingId = notatka w
 // trybie edycji, busyId = trwa zapis/usuwanie, confirmDeleteId = modal.
 const [editingId, setEditingId] = useState<number | null>(null);
 const [editText, setEditText] = useState("");
 const [busyId, setBusyId] = useState<number | null>(null);
 const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

 // Notatkę może zmienić jej autor albo admin (moderacja) — zgodne z
 // _can_modify_note na backendzie. author_id bywa null dla importów Traffit:
 // wtedy tylko admin (canModerate) widzi akcje, autor-match jest niemożliwy.
 const canModifyNote = (n: any): boolean =>
 currentUserId != null &&
 (canModerate ||
 (n.author_id != null && Number(n.author_id) === Number(currentUserId)));

 // Mentionable users dla render badge'y w liście notatek (zawsze global —
 // lista notatek miesza notatki z różnych rekrutacji). Autocomplete w
 // textarea używa osobnego, kontekstowego scope (job gdy wybrany).
 const { data: users = [] } = useMentionableUsers({ kind: "global" });
 const usersByEmail = useMemo(() => buildUsersByEmail(users), [users]);

 return (
 <div className="space-y-4">
 <NoteComposer
 recruitments={recruitments}
 defaultJobId={defaultJobId}
 noteText={noteText}
 setNoteText={setNoteText}
 onAdd={onAdd}
 saving={saving}
 viewers={viewers}
 currentUserId={currentUserId}
 setEditing={setEditing}
 candidateName={candidateName}
 candidateLastname={candidateLastname}
 />

 <Separator />

 {notes.length === 0 ? (
 <div className="py-6 text-center text-sm text-muted-foreground">
 Brak notatek.
 </div>
 ) : (
 <div className="space-y-2">
 {notes.map((n: any, i: number) => {
 const editable = canModifyNote(n);
 const isEditing = editingId != null && editingId === n.id;
 const isBusy = busyId != null && busyId === n.id;
 return (
 <div
 key={n.id ?? i}
 className="rounded-lg bg-background/40 border border-border p-3"
 >
 <div className="flex items-baseline gap-2 text-xs text-muted-foreground flex-wrap">
 <span className="font-medium text-foreground">
 {n.note_type ? `Notatka — ${n.note_type}` :"Notatka"}
 </span>
 {(n.job_title ?? jobTitleById.get(Number(n.job_id))) && (
 <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary px-2 py-0.5 text-[11px] font-medium">
 <Target className="h-3 w-3" />
 {n.job_title ?? jobTitleById.get(Number(n.job_id))}
 </span>
 )}
 {n.author_name && (
 <>
 <span>·</span>
 <span title={n.author_email ?? undefined}>
 {n.author_name}
 </span>
 </>
 )}
 <span>·</span>
 <span>{n.timestamp ? formatRelativeTime(n.timestamp) : ""}</span>
 {editable && !isEditing && (
 <span className="ml-auto inline-flex items-center gap-1">
 <button
 type="button"
 onClick={() => {
 setEditingId(n.id);
 setEditText(unwrapNoteContent(n.content));
 }}
 className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
 title="Edytuj notatkę"
 aria-label="Edytuj notatkę"
 >
 <PencilLine className="h-3.5 w-3.5" />
 </button>
 <button
 type="button"
 onClick={() => setConfirmDeleteId(n.id)}
 className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
 title="Usuń notatkę"
 aria-label="Usuń notatkę"
 >
 <Trash2 className="h-3.5 w-3.5" />
 </button>
 </span>
 )}
 </div>
 {isEditing ? (
 <div className="mt-2 space-y-2">
 <MentionTextarea
 value={editText}
 onChange={setEditText}
 scope={
 n.job_id != null
 ? { kind: "job", jobId: Number(n.job_id) }
 : { kind: "global" }
 }
 placeholder="Treść notatki… (@email aby oznaczyć osobę)"
 rows={3}
 ariaLabel="Edytuj treść notatki"
 />
 <div className="flex items-center justify-end gap-2">
 <Button
 size="sm"
 variant="outline"
 disabled={isBusy}
 onClick={() => {
 setEditingId(null);
 setEditText("");
 }}
 >
 <X className="h-3.5 w-3.5" />
 Anuluj
 </Button>
 <Button
 size="sm"
 variant="primary"
 loading={isBusy}
 disabled={!editText.trim() || isBusy}
 onClick={async () => {
 setBusyId(n.id);
 const ok = await onEdit(n.id, editText.trim());
 setBusyId(null);
 if (ok) {
 setEditingId(null);
 setEditText("");
 }
 }}
 >
 Zapisz
 </Button>
 </div>
 </div>
 ) : (
 <p className="text-sm text-foreground mt-1 whitespace-pre-line">
 {renderWithMentions(unwrapNoteContent(n.content_rendered ?? n.content), usersByEmail)}
 </p>
 )}
 </div>
 );
 })}
 </div>
 )}

 {confirmDeleteId != null && (
 <ConfirmModal
 title="Usunąć notatkę?"
 message="Tej operacji nie można cofnąć. Notatka zostanie trwale usunięta."
 confirmLabel="Usuń"
 onCancel={() => setConfirmDeleteId(null)}
 onConfirm={async () => {
 const noteId = confirmDeleteId;
 setConfirmDeleteId(null);
 setBusyId(noteId);
 const ok = await onDelete(noteId);
 setBusyId(null);
 if (ok && editingId === noteId) {
 setEditingId(null);
 setEditText("");
 }
 }}
 />
 )}
 </div>
 );
}


// ── Screening summary (sticky, always visible across tabs) ─────────────

const MOTIVATION_LABEL_PL: Record<string, string> = {
 money: "Pieniądze",
 growth: "Rozwój",
 project: "Projekt",
 team: "Zespół",
 work_mode: "Tryb pracy",
 stability: "Stabilność",
 technology: "Technologia",
 location: "Lokalizacja",
};

const RISK_LABEL_PL: Record<string, string> = {
 low: "Niskie",
 medium: "Średnie",
 high: "Wysokie",
};

const RISK_VARIANT: Record<string, "success" |"warning" |"danger"> = {
 low: "success",
 medium: "warning",
 high: "danger",
};

interface VerifiedSkillAgg {
 skill: string;
 level: string;
 notes?: string;
}

interface LastScreeningMeta {
 id: number;
 created_at: string;
 screening_type?: string | null;
 overall_impression?: number | null;
}

interface AiProfile {
 screening_count: number;
 motivation_top?: string | null;
 readiness_avg?: number | null;
 overall_impression_avg?: number | null;
 counteroffer_risk_dominant?: string | null;
 counteroffer_risk_distribution?: Record<string, number>;
 red_flags_unique?: string[];
 verified_skills_aggregate?: VerifiedSkillAgg[];
 motivation_trend?: Array<{
 date: string;
 primary?: string | null;
 secondary?: string | null;
 type?: string | null;
 }>;
 last_screening?: LastScreeningMeta | null;
}

function pluralScreenings(n: number): string {
 if (n === 1) return"rozmowa";
 const mod10 = n % 10;
 const mod100 = n % 100;
 if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return"rozmowy";
 return"rozmów";
}

function ScreeningSummary({
 aiProfile,
}: {
 aiProfile: AiProfile;
}) {
 const [expanded, setExpanded] = useState(false);

 const {
 screening_count,
 motivation_top,
 readiness_avg,
 overall_impression_avg,
 counteroffer_risk_dominant,
 red_flags_unique = [],
 verified_skills_aggregate = [],
 motivation_trend = [],
 last_screening,
 } = aiProfile;

 const lastRelative = last_screening?.created_at
 ? formatRelativeTime(last_screening.created_at)
 : null;
 const topSkills = verified_skills_aggregate.slice(0, 5);

 return (
 <div className="sticky top-0 z-20">
 <Card
 variant="default"
 size="md"
 className={cn("py-3! shadow-smd","bg-card/95 backdrop-blur-xs"
 )}
 >
 {/* Header */}
 <div className="flex items-center gap-2 flex-wrap">
 <MessageSquare className="h-4 w-4 text-primary shrink-0" />
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">
 Podsumowanie screeningów
 </h3>
 <span className="text-xs text-muted-foreground">
 · {screening_count} {pluralScreenings(screening_count)}
 </span>
 {lastRelative && (
 <span className="text-xs text-muted-foreground">
 · ostatnia {lastRelative}
 </span>
 )}
 <button
 type="button"
 onClick={() => setExpanded((e) => !e)}
 className="ml-auto inline-flex min-h-11 min-w-11 items-center justify-center gap-1 px-2 text-xs text-muted-foreground hover:text-primary transition-colors"
 aria-expanded={expanded}
 >
 {expanded ?"Zwiń" :"Rozwiń"}
 {expanded ? (
 <ChevronUp className="h-3 w-3" />
 ) : (
 <ChevronDown className="h-3 w-3" />
 )}
 </button>
 </div>

 {/* Badges row */}
 <div className="flex items-center gap-2 flex-wrap mt-2.5">
 {motivation_top && (
 <Badge variant="soft" size="md">
 <Target className="h-3 w-3" />
 Motywacja: {MOTIVATION_LABEL_PL[motivation_top] ?? motivation_top}
 </Badge>
 )}
 {readiness_avg != null && (
 <Badge variant="soft" size="md">
 <Gauge className="h-3 w-3" />
 Gotowość: {readiness_avg}/5
 </Badge>
 )}
 {counteroffer_risk_dominant && (
 <Badge
 variant={RISK_VARIANT[counteroffer_risk_dominant] ??"neutral"}
 size="md"
 >
 <ShieldAlert className="h-3 w-3" />
 Counteroffer:{""}
 {RISK_LABEL_PL[counteroffer_risk_dominant] ??
 counteroffer_risk_dominant}
 </Badge>
 )}
 {overall_impression_avg != null && (
 <Badge variant="burgundy" size="md">
 <Star className="h-3 w-3" />
 Wrażenie: {overall_impression_avg}/5
 </Badge>
 )}
 {red_flags_unique.length > 0 && (
 <Badge variant="danger" size="md">
 <AlertTriangle className="h-3 w-3" />
 {red_flags_unique.length}{""}
 {red_flags_unique.length === 1 ?"red flag" :"red flags"}
 </Badge>
 )}
 </div>

 {/* Expanded content */}
 {expanded && (
 <div className="mt-3.5 pt-3.5 border-t border-border space-y-3">
 {red_flags_unique.length > 0 && (
 <div>
 <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-primary">
 <AlertTriangle className="h-3 w-3" />
 Red flags
 </div>
 <div className="flex flex-wrap gap-1.5">
 {red_flags_unique.map((rf, i) => (
 <Badge key={i} variant="danger" size="sm">
 {rf}
 </Badge>
 ))}
 </div>
 </div>
 )}
 {topSkills.length > 0 && (
 <div>
 <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
 Potwierdzone umiejętności
 </div>
 <div className="flex flex-wrap gap-1.5">
 {topSkills.map((sk, i) => (
 <Badge
 key={i}
 variant={sk.level === "confirmed" ?"success" :"soft"}
 size="sm"
 >
 {sk.skill}
 </Badge>
 ))}
 </div>
 </div>
 )}
 {motivation_trend.length > 1 && (
 <div>
 <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
 Trend motywacji
 </div>
 <div className="flex flex-wrap gap-1.5">
 {motivation_trend.map((m, i) => (
 <Badge key={i} variant="outline" size="sm">
 {MOTIVATION_LABEL_PL[m.primary ??""] ??
 m.primary ??"—"}
 </Badge>
 ))}
 </div>
 </div>
 )}
 </div>
 )}
 </Card>
 </div>
 );
}
