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
 Ban,
 Calendar,
 CheckCircle2,
 ChevronDown,
 ChevronUp,
 Download,
 Eye,
 FileSignature,
 FileText,
 Files,
 Gauge,
 GraduationCap,
 Languages as LanguagesIcon,
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
} from"@/lib/api";
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
 getLanguageList,
} from"@/components/v2/pages/candidate-profile-helpers";
import {
 formatCandidateLocation,
 getCurrentTitle,
 getExperienceLabel,
 getTagName,
} from"@/components/v2/pages/candidate-list-helpers";
import { CandidateEngagementPanel } from"@/components/candidates/CandidateEngagementPanel";
import { CandidateLocationPanel } from"@/components/candidates/CandidateLocationPanel";
import { CandidateSourcesPanel } from"@/components/candidates/CandidateSourcesPanel";
import { cn, formatDate, formatRelativeTime } from"@/lib/utils";
import { useTabsStore } from"@/store/tabs";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from"@/components/ui/card";
import { Separator } from"@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from"@/components/ui/tabs";
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuSeparator,
 DropdownMenuTrigger,
} from"@/components/ui/dropdown-menu";
import { Textarea } from"@/components/ui/textarea";
import { MentionTextarea } from"@/components/v2/forms/MentionTextarea";
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
import { CVBrandedEditModal } from"@/components/v2/modals/CVBrandedEditModal";
import { CVShareLinkModal } from"@/components/v2/modals/CVShareLinkModal";
import {
  FilePreviewModal,
  previewKind,
  downloadDocumentBlob,
  formatFileSize,
  fileIcon,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import {
 Dialog,
 DialogContent,
 DialogFooter,
 DialogHeader,
 DialogTitle,
} from"@/components/ui/dialog";
import { QuickAssignV2 } from"@/components/v2/modals/QuickAssignV2";
import { ConfirmV2 } from"@/components/v2/modals/ConfirmV2";
import { RISK_QUERY_KEY, RiskBadge } from"@/components/v2/RiskBadge";
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

interface CandidateDetailV2Props {
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
 const { showError, showSuccess } = useToast();
 const openTab = useTabsStore((s) => s.openTab);

 // ── Prev/Next candidate navigation context ─────────────────────────────
 // Embedded mode receives `navigation` from parent (CandidatesListV2).
 // Full-page mode reads it from URL search params (?nav=search&pos=N&...).
 // Use `useSearchParams` so the value re-evaluates after client hydration
 // and on every push() — `window.location` inside useMemo wouldn't.
 const searchParamsForNav = useSearchParams();
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
 const sp = encodeNavContext(urlNav.filters, next.position);
 router.push(`/candidates/${next.candidateId}?${sp.toString()}`);
 // Next.js caches the dynamic `[id]` segment, so `useSearchParams`
 // can lag a render. Refresh server data so subsequent navigations
 // see the up-to-date URL params.
 router.refresh();
 }
 },
 [navContext, urlNav, router],
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

 const [activeTab, setActiveTab] = useState("profil");
 const [emailOpen, setEmailOpen] = useState(false);
 const [cvOpen, setCvOpen] = useState(false);
 const [assignOpen, setAssignOpen] = useState(false);
 const [scheduleOpen, setScheduleOpen] = useState(false);
 const [editOpen, setEditOpen] = useState(false);
 // Inline edycja tożsamości/kontaktu (imię, nazwisko, email, telefon) wprost
 // w nagłówku — szybka korekta np. kandydatów zaimportowanych jako "?".
 const [editingIdentity, setEditingIdentity] = useState(false);
 const [marketplaceOpen, setMarketplaceOpen] = useState(false);
 const [deleteOpen, setDeleteOpen] = useState(false);
 const [screeningStage, setScreeningStage] = useState<number | null>(null);
 const [noteText, setNoteText] = useState("");
 const [noteSaving, setNoteSaving] = useState(false);

 // Presence: one subscription per candidate page; viewers + setEditing are
 // passed into children so the NotatkiTab can emit edit signals without
 // mounting a second hook instance.
 const currentUser = useAuthStore((s) => s.user);
 const { viewers: presenceViewers, setEditing: setPresenceEditing } =
 usePresence("candidate", Number.isFinite(Number(id)) ? Number(id) : null);

 const { data: candidate, isLoading } = useQuery({
 queryKey: ["candidate", id],
 queryFn: () => api.get(`/api/candidates/${id}`).then((r) => r.data),
 enabled: !!id,
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
 const { data: timelineRaw } = useQuery<{ timeline?: any[] } | any[]>({
 queryKey: ["candidate-timeline", id],
 queryFn: () =>
 api.get(`/api/candidates/${id}/timeline?limit=50`).then((r) => r.data),
 enabled: !!id && (activeTab === "timeline" || activeTab === "notatki"),
 });
 const timeline: any[] = Array.isArray(timelineRaw)
 ? timelineRaw
 : (timelineRaw?.timeline ?? []);

 // Notatki tab — dedykowane, NIEUCINANE źródło notatek. Feed `/timeline`
 // miesza notatki z etapami/aktywnościami i ucina do limitu (50), więc przy
 // bogatej historii (np. import Traffit) starsze notatki znikały z zakładki.
 // `/api/notes` zwraca komplet, wzbogacony o author_name + content_rendered.
 const { data: notesRaw } = useQuery<{ items?: any[] }>({
 queryKey: ["candidate-notes", id],
 queryFn: () =>
 api.get(`/api/notes?candidate_id=${id}`).then((r) => r.data),
 enabled: !!id && activeTab === "notatki",
 });
 const noteItems: any[] = (notesRaw?.items ?? []).map((n: any) => ({
 ...n,
 type: "note",
 timestamp: n.created_at,
 }));

 // History API returns `{ jobs: [...], contracts: [...] }` — flatten jobs.
 const { data: historyRaw } = useQuery<{ jobs?: any[]; contracts?: any[] } | any[]>({
 queryKey: ["candidate-history", id],
 queryFn: () => api.get(`/api/candidates/${id}/history`).then((r) => r.data),
 // Także na zakładce "notatki" — potrzebujemy listy rekrutacji do selektora
 // "przypisz notatkę do rekrutacji".
 enabled: !!id && (activeTab === "rekrutacje" || activeTab === "notatki"),
 });

 // Phase 17 (migracja 0068): risk profile — pokazujemy badge w nagłówku.
 // Recompute następuje event-driven po każdej tranzycji + TTL 24h, więc
 // staleTime 5 min jest tu bezpieczny.
 const { data: riskProfile } = useQuery<CandidateRiskProfile>({
 queryKey: RISK_QUERY_KEY(id),
 queryFn: () => api.get(`/api/candidates/${id}/risk`).then((r) => r.data),
 enabled: !!id,
 staleTime: 5 * 60 * 1000,
 });
 const history: any[] = Array.isArray(historyRaw)
 ? historyRaw
 : (historyRaw?.jobs ?? []);
 const historyContracts: any[] = Array.isArray(historyRaw)
 ? []
 : (historyRaw?.contracts ?? []);

 const { data: aiProfile } = useQuery<any>({
 queryKey: ["candidate-ai-profile", id],
 queryFn: () => api.get(`/api/candidates/${id}/ai-profile`).then((r) => r.data),
 enabled: !!id,
 });

 // Lista umów kandydata — dla zakładki"Umowa". Backend już akceptuje
 // ?candidate_id w GET /api/contracts; zwraca paginowaną kopertę.
 const { data: candidateContractsRaw } = useQuery<{ items?: any[] } | any[]>({
 queryKey: ["candidate-contracts", id],
 queryFn: () =>
 contractsApi.byCandidate(Number(id)).then((r: any) => r.data),
 enabled: !!id && activeTab === "umowa",
 });
 const candidateContracts: any[] = Array.isArray(candidateContractsRaw)
 ? candidateContractsRaw
 : (candidateContractsRaw?.items ?? []);

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
 queryClient.invalidateQueries({ queryKey: ["candidate-timeline", id] });
 queryClient.invalidateQueries({ queryKey: ["candidate-notes", id] });
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
 queryClient.invalidateQueries({ queryKey: ["candidate-timeline", id] });
 queryClient.invalidateQueries({ queryKey: ["candidate-notes", id] });
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
 queryClient.invalidateQueries({ queryKey: ["candidate-timeline", id] });
 queryClient.invalidateQueries({ queryKey: ["candidate-notes", id] });
 return true;
 } catch (e) {
 showError(extractErrorMsg(e) || "Nie udało się usunąć notatki");
 return false;
 }
 };

 // Hard-delete the candidate from the DB. Backend cascades all related rows
 // (notes, contracts, pipeline, calls, …) and drops the Qdrant vector; guard is
 // admin/delivery_lead. After success leave the detail view — close the drawer
 // in embedded mode, otherwise navigate back to the candidate list.
 const deleteCandidate = useMutation({
 mutationFn: () => candidatesApi.delete(id),
 onSuccess: () => {
 showSuccess("Kandydat usunięty z bazy");
 queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
 setDeleteOpen(false);
 if (embedded) onClose?.();
 else router.push("/candidates");
 },
 onError: (e) =>
 showError(extractErrorMsg(e) || "Nie udało się usunąć kandydata"),
 });

 // Open a "Więcej" menu action on the next tick, after Radix finishes closing
 // the dropdown, so the opened overlay isn't disturbed by the menu's dismiss.
 // Radix Dialogs (Email / interview / Generuj CV) only open reliably from a
 // menu item nested in the drawer Sheet because the dropdown is modal={false}
 // (see the DropdownMenu below) — without that, the menu's body pointer-events
 // lock swallows the dialog open, which is what regressed in #533.
 const openFromMenu = (fn: () => void) => setTimeout(fn, 0);

 if (isLoading || !candidate) {
 return (
 <div className="flex items-center justify-center py-16 text-muted-foreground">
 <div className="text-sm">Ładowanie kandydata…</div>
 </div>
 );
 }

 const fullName = `${candidate.name ??""} ${candidate.lastname ??""}`.trim();
 const initials = fullName
 .split(/\s+/)
 .map((w: string) => w[0])
 .slice(0, 2)
 .join("")
 .toUpperCase();

 const rootClass = embedded
 ?"space-y-4"
 :"max-w-6xl mx-auto space-y-5";

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
 onClose={onClose}
 onExpand={
 navContext
 ? () => {
 const sp = encodeNavContext(
 navContext.filters,
 candidateNav.position,
 );
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
 className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary min-w-0 max-w-[22rem]"
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
 className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
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
 className="ml-auto"
 />
 )}
 </div>
 )}

 {candidate.employment && (
 <AtOurClientBanner employment={candidate.employment} />
 )}

 {/* ── HERO CARD ── */}
 <Card variant="default" size="md" className="!p-0 overflow-hidden">
 {/* Top accent bar */}
 <div className="h-1 bg-gradient-to-r from-[hsl(var(--primary))] to-[hsl(var(--card))]" />
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
 <h1 className="font-semibold text-2xl md:text-3xl font-extrabold tracking-[-0.02em] text-foreground">
 {fullName}
 </h1>
 {candidate.status && STATUS_LABELS[candidate.status] && (
 <Badge variant={STATUS_VARIANT[candidate.status] ??"neutral"} size="md">
 {STATUS_LABELS[candidate.status]}
 </Badge>
 )}
 {riskProfile && <RiskBadge profile={riskProfile} />}
 <CandidateHighlights candidate={candidate} variant="full" />
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
 className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
 title="Edytuj imię, nazwisko, e-mail i telefon"
 >
 <PencilLine className="h-3.5 w-3.5" />
 Edytuj dane
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
 className="inline-flex items-center gap-1.5 hover:text-primary"
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
 />
 )}
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
 className="inline-flex items-center gap-1.5 hover:text-primary"
 >
 <Linkedin className="h-3.5 w-3.5 text-[#0A66C2]" />
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
 onClick={onClose}
 aria-label="Zamknij"
 className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-primary/10"
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
 onClick={() => setAssignOpen(true)}
 disabled={!candidate}
 >
 <UserPlus className="h-4 w-4" />
 Przypisz do oferty
 </Button>
 {/* Utility cluster — secondary actions collapse into "Więcej" so only the
 primary "Przypisz do oferty" task stays visible in the strip. */}
 <div className="mx-0.5 hidden h-5 w-px bg-border sm:block" />
 {candidate && <PinButton candidateId={candidate.id} iconOnly />}
 {/* modal={false} is load-bearing: a default (modal) dropdown leaves
 body pointer-events locked while it closes, so a Radix Dialog opened
 from a menu item (Email / interview / CV) is dismissed on the same
 tick when the panel is nested in the drawer Sheet — the exact failure
 #533 hit. Dropping the lock lets those dialogs open reliably from the
 menu, so all three can live here instead of crowding the action row. */}
 <DropdownMenu modal={false}>
 <DropdownMenuTrigger asChild>
 <Button size="sm" variant="outline">
 Więcej
 <ChevronDown className="h-3.5 w-3.5 opacity-60" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end" className="w-52">
 <DropdownMenuItem
 disabled={!candidate.email}
 onSelect={() => openFromMenu(() => setEmailOpen(true))}
 >
 <Mail className="h-4 w-4" />
 Email
 </DropdownMenuItem>
 <DropdownMenuItem
 disabled={!candidate.email}
 title={candidate.email ?"Zaplanuj interview w Outlook (M365)" :"Kandydat nie ma adresu email"}
 onSelect={() => openFromMenu(() => setScheduleOpen(true))}
 >
 <Calendar className="h-4 w-4" />
 Zaplanuj interview
 </DropdownMenuItem>
 <DropdownMenuItem onSelect={() => openFromMenu(() => setCvOpen(true))}>
 <FileText className="h-4 w-4" />
 Generuj CV
 </DropdownMenuItem>
 <DropdownMenuSeparator />
 <DropdownMenuItem onSelect={() => openFromMenu(() => setEditOpen(true))}>
 <PencilLine className="h-4 w-4" />
 Edytuj
 </DropdownMenuItem>
 <DropdownMenuItem onSelect={() => openFromMenu(() => setMarketplaceOpen(true))}>
 <Store className="h-4 w-4" />
 Wrzuć na targ
 </DropdownMenuItem>
 {hasRole(currentUser, "admin", "delivery_lead") && (
 <>
 <DropdownMenuSeparator />
 <DropdownMenuItem
 onSelect={() => openFromMenu(() => setDeleteOpen(true))}
 className="text-destructive focus:text-destructive"
 >
 <Trash2 className="h-4 w-4" />
 Usuń kandydata
 </DropdownMenuItem>
 </>
 )}
 </DropdownMenuContent>
 </DropdownMenu>
 </div>
 {/* Key stats moved into ProfilTab "Kluczowe fakty" grid for a single,
 scannable source — see ProfilTab FactTile grid. */}
 </div>
 </Card>

 {/* 2-column layout on full-page (lg+): tabs left, sticky rail right.
 Drawer (embedded) never gets lg:grid-cols → stays single column at any
 viewport. */}
 <div
 className={cn(
 "grid gap-5 items-start",
 !embedded && "lg:grid-cols-[1fr_340px]",
 )}
 >
 {/* Side rail — AI screening + suggestions (right column on full-page) */}
 <aside
 className={cn(
 "space-y-4",
 !embedded && "lg:order-2 lg:sticky lg:top-4",
 )}
 >
 {/* AI screening summary (from /ai-profile — distinct from the CV-derived
 candidate.ai_summary shown in the Profil tab). Truncated for scanability. */}
 {aiProfile?.summary && (
 <Card variant="default" size="md" className="!py-4">
 <div className="flex items-start gap-2">
 <Sparkles className="h-4 w-4 text-primary shrink-0 mt-0.5" />
 <div className="flex-1">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-primary mb-1">
 AI Screening
 </h3>
 <ExpandableText text={aiProfile.summary} maxLines={3} className="italic" />
 </div>
 </div>
 </Card>
 )}

 {/* Sticky screening summary — always visible across tabs */}
 {aiProfile && aiProfile.screening_count > 0 && (
 <ScreeningSummary
 aiProfile={aiProfile}
 />
 )}

 {/* Suggested jobs (reuse v1 widget) */}
 <SuggestedJobsWidget candidateId={Number(id)} hideWhenEmpty />

 {/* AI-suggested talent pools (migracja 0041) */}
 <SuggestedPoolsWidget candidateId={Number(id)} />
 </aside>

 {/* Main column — tabs */}
 <div className={cn("space-y-5 min-w-0", !embedded && "lg:order-1")}>
 {/* Tabs */}
 <Card variant="default" size="md" className="!p-0">
 <Tabs value={activeTab} onValueChange={setActiveTab}>
 {/* max-w-full + overflow-x-auto so the 7-tab list scrolls instead of
 spilling over the right rail in the narrower 2-col main column. */}
 <TabsList className="px-4 pt-2 max-w-full overflow-x-auto justify-start [&>*]:shrink-0">
 <TabsTrigger value="profil">
 <User className="h-3.5 w-3.5" />
 Profil
 </TabsTrigger>
 <TabsTrigger value="timeline">
 <MessageSquare className="h-3.5 w-3.5" />
 Timeline
 </TabsTrigger>
 <TabsTrigger value="rekrutacje">
 <Calendar className="h-3.5 w-3.5" />
 Rekrutacje
 {history.length > 0 && (
 <Badge size="sm" variant="soft">
 {history.length}
 </Badge>
 )}
 </TabsTrigger>
 <TabsTrigger value="notatki">
 <MessageSquare className="h-3.5 w-3.5" />
 Notatki
 </TabsTrigger>
 <TabsTrigger value="pliki">
 <Files className="h-3.5 w-3.5" />
 Pliki
 </TabsTrigger>
 <TabsTrigger value="umowa">
 <FileSignature className="h-3.5 w-3.5" />
 Umowa
 {candidateContracts.some(
 (c: any) => c.status === "draft",
 ) && (
 <Badge size="sm" variant="warning">
 draft
 </Badge>
 )}
 </TabsTrigger>
 <TabsTrigger value="chat">
 <MessageSquare className="h-3.5 w-3.5" />
 Chat
 </TabsTrigger>
 </TabsList>

 <div className="p-5">
 <TabsContent value="profil" className="mt-0">
 <ProfilTab candidate={candidate} onOpenTab={setActiveTab} />
 </TabsContent>
 <TabsContent value="timeline" className="mt-0">
 <TimelineTab items={timeline ?? []} />
 </TabsContent>
 <TabsContent value="rekrutacje" className="mt-0">
 <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
 <div className="lg:col-span-2">
 <RekrutacjeTab
 history={history}
 candidateId={Number(id)}
 candidateName={`${candidate.name} ${candidate.lastname}`}
 />
 </div>
 <div className="space-y-4">
 <CandidatePipelinesWidget
 candidateId={Number(id)}
 employment={candidate.employment}
 />
 </div>
 </div>
 </TabsContent>
 <TabsContent value="notatki" className="mt-0">
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
 />
 </TabsContent>
 <TabsContent value="pliki" className="mt-0">
 <PlikiTab candidateId={Number(id)} />
 </TabsContent>
 <TabsContent value="umowa" className="mt-0">
 <UmowaTab
 candidateId={Number(id)}
 candidateName={fullName}
 candidatePhone={candidate.phone ?? null}
 contracts={candidateContracts}
 jdgComplete={Boolean(
 candidate.legal_name && candidate.nip,
 )}
 onJumpToProfile={() => setActiveTab("profil")}
 />
 </TabsContent>
 <TabsContent value="chat" className="mt-0">
 <CandidateChatTab candidateId={Number(id)} />
 </TabsContent>
 </div>
 </Tabs>
 </Card>
 </div>
 {/* /Main column */}
 </div>
 {/* /2-column grid */}

 {/* Side widgets (below tabs). hideWhenEmpty keeps the footer quiet: an empty
 rate/conflict widget collapses to a single "Dodaj" link instead of an empty
 card (items-start so a lone link doesn't stretch to a sibling card's height). */}
 <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
 <DeferUntilVisible minHeight={44}>
 <RateHistoryWidget candidateId={Number(id)} hideWhenEmpty />
 </DeferUntilVisible>
 <DeferUntilVisible minHeight={44}>
 <ConflictsWidget candidateId={Number(id)} hideWhenEmpty />
 </DeferUntilVisible>
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
 queryClient.invalidateQueries({ queryKey: ["candidate-history", id] });
 queryClient.invalidateQueries({ queryKey: ["suggested-jobs", id] });
 }}
 />
 {editOpen && candidate && (
 <EditCandidateModal
 candidate={candidate}
 onClose={() => setEditOpen(false)}
 onSuccess={() => {
 queryClient.invalidateQueries({ queryKey: ["candidate", id] });
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

 {/* Hard-delete confirmation. Destructive + explicit "cannot be undone" copy
 because the candidate and all related data are permanently removed. */}
 <ConfirmV2
 open={deleteOpen}
 onOpenChange={setDeleteOpen}
 variant="destructive"
 title="Usunąć kandydata z bazy?"
 description={`${candidate.name} ${candidate.lastname} oraz wszystkie powiązane dane (notatki, rozmowy, pipeline, kontrakty) zostaną trwale usunięte. Tej operacji nie można cofnąć.`}
 confirmLabel="Usuń trwale"
 cancelLabel="Anuluj"
 loading={deleteCandidate.isPending}
 onConfirm={() => deleteCandidate.mutate()}
 />
 </div>
 );
}

// ── Helpers ────────────────────────────────────────────────────────────

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
 queryClient.invalidateQueries({ queryKey: ["candidate", candidateId] });
 },
 onError: () => showError("Nie udało się zapisać danych JDG"),
 });

 return (
 <Card variant="default" size="md">
 <CardHeader className="!pb-2">
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
 <Card variant="default" size="md" className="border-l-4 border-l-amber-500">
 <CardContent className="py-3 flex items-center justify-between gap-3 flex-wrap">
 <div className="text-sm flex items-center gap-2 text-foreground">
 <AlertTriangle className="h-4 w-4 text-amber-600" />
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
 const { data: docs } = useQuery<any[]>({
 queryKey: ["contract-docs", contract.id],
 queryFn: () => contractsApi.documents(contract.id).then((r: any) => r.data),
 });
 const documents = docs ?? [];

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
 <a
 href={contractsApi.documentDownloadUrl(contract.id, d.id)}
 target="_blank"
 rel="noopener noreferrer"
 className="text-xs text-primary inline-flex items-center gap-1"
 >
 <Download className="h-3 w-3" /> pobierz
 </a>
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
 class: "prose prose-sm max-w-none min-h-[400px] focus:outline-none border border-border rounded-lg bg-card p-4",
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
 onClick={() =>
 window.open(
 contractsApi.draft.printableUrl(contractId), "_blank",
 )
 }
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
 <div className="text-xs text-amber-600 flex items-center gap-1">
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
 className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
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
 const { data: historyRaw } = useQuery<{ jobs?: any[] } | any[]>({
 queryKey: ["candidate-history", String(candidateId)],
 queryFn: () =>
 api.get(`/api/candidates/${candidateId}/history`).then((r) => r.data),
 enabled: !!candidateId,
 staleTime: 30_000,
 });
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
 const languages = getLanguageList(candidate);
 const verifiedTech = verifiedTechList(candidate);
 const verifiedSet = new Set(verifiedTech.map((t) => t.toLowerCase()));
 const title = getCurrentTitle(candidate);
 const expLabel = getExperienceLabel(candidate.years_it_experience);
 const location = formatCandidateLocation(candidate.city ?? candidate.location ?? null);
 const salary =
 candidate.expected_salary != null
 ? `${candidate.expected_salary.toLocaleString("pl-PL")} ${candidate.currency ??"PLN"}`
 : null;
 const availability = candidate.available_from
 ? formatDate(candidate.available_from)
 : null;
 const notice = candidate.notice_period_weeks
 ? `${candidate.notice_period_weeks * 7} dni`
 : null;

 // Mini activity feed — last 5 events, so the recruiter sees recent history
 // without switching to the Timeline tab (Traffit's Podsumowanie centerpiece).
 const { data: feedRaw } = useQuery<{ timeline?: any[] } | any[]>({
 queryKey: ["candidate-timeline-mini", candidate.id],
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
 queryKey: ["candidate-documents", candidate.id],
 queryFn: async () => {
 const res = await api.get<CandidateDocument[]>(
 `/api/candidates/${candidate.id}/documents`,
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
 if (location) facts.push({ icon: <MapPin className="h-3 w-3" />, label: "Lokalizacja", value: location });
 if (salary) facts.push({ icon: <Wallet className="h-3 w-3" />, label: "Oczekiwania", value: salary });
 if (notice) facts.push({ icon: <Calendar className="h-3 w-3" />, label: "Wypowiedzenie", value: notice });
 if (availability) facts.push({ icon: <Calendar className="h-3 w-3" />, label: "Dostępność", value: availability });
 if (candidate.competence_category)
 facts.push({ icon: <Target className="h-3 w-3" />, label: "Kategoria", value: candidate.competence_category });

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
 <div className="text-[11px] font-medium text-emerald-700 dark:text-emerald-300 mb-1">
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
 <CheckCircle2 className="h-3 w-3 text-emerald-600" />
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

 {/* 9. Języki (NOWE) */}
 {languages.length > 0 && (
 <section>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2 flex items-center gap-2">
 <LanguagesIcon className="h-3.5 w-3.5" />
 Języki
 </h3>
 <div className="flex flex-wrap gap-2">
 {languages.map((l, i) => (
 <div
 key={i}
 className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-card border border-border"
 >
 <span className="text-sm font-medium text-foreground">{l.lang}</span>
 {l.level && (
 <Badge size="sm" variant="soft">
 {l.level}
 </Badge>
 )}
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
 doc={previewDoc}
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

function TimelineTab({ items }: { items: any[] }) {
 if (!Array.isArray(items) || items.length === 0) {
 return (
 <div className="py-10 text-center text-sm text-muted-foreground">
 Brak zdarzeń w timeline.
 </div>
 );
 }
 return (
 <div className="space-y-0">
 {items.map((item: any, i: number) => (
 <div
 key={`${item.type}-${item.id}-${i}`}
 className="flex gap-3 py-2.5 border-b border-border/50 last:border-0"
 >
 <div className="w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
 <MessageSquare className="h-3.5 w-3.5" />
 </div>
 <div className="flex-1 min-w-0">
 <div className="flex items-baseline gap-2 flex-wrap">
 <span className="text-sm font-medium text-foreground">
 {timelineItemLabel(item)}
 </span>
 <span className="ml-auto text-xs text-muted-foreground">
 {item.timestamp ? formatRelativeTime(item.timestamp) : ""}
 </span>
 </div>
 {item.type === "stage_change" && item.moved_by_name && (
 <p className="text-xs text-muted-foreground mt-0.5">
 Przeniósł: {item.moved_by_name}
 </p>
 )}
 {item.content && (
 <p className="text-sm text-foreground mt-1 whitespace-pre-line">
 {unwrapNoteContent(item.content_rendered ?? item.content)}
 </p>
 )}
 {item.notes && (
 <p className="text-sm text-muted-foreground mt-1 italic whitespace-pre-line">
 {item.notes}
 </p>
 )}
 {item.rating && (
 <div className="flex gap-0.5 mt-1">
 {[1, 2, 3, 4, 5].map((n) => (
 <Star
 key={n}
 className={cn("h-3.5 w-3.5",
 n <= item.rating
 ?"text-amber-500 fill-amber-500"
 :"text-[hsl(var(--border))] fill-[hsl(var(--border))]"
 )}
 />
 ))}
 </div>
 )}
 </div>
 </div>
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
 label,
 rate,
 mutationFn,
 successMessage,
 testIdPrefix,
}: {
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
 // Prefix-invalidate — queryKey to ["candidate-history", id(string)], a tu
 // mamy id jako number; prefix match odświeży niezależnie od typu drugiego klucza.
 queryClient.invalidateQueries({ queryKey: ["candidate-history"] });
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
 className="w-24 h-8 px-2 rounded border border-border bg-card text-sm focus:outline-none focus:ring-2 focus:ring-primary"
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
 label="Stawka kandydata"
 rate={expectedRate}
 testIdPrefix="expected-rate"
 successMessage="Zapisano stawkę kandydata"
 mutationFn={(payload) =>
 candidatesApi.setRecruitmentExpectedRate(candidateId, jobId, payload)
 }
 />
 <EditableRateCell
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
 ?"font-medium text-emerald-600"
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
}: {
 history: any[];
 candidateId: number;
 candidateName: string;
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
 />
 ))}
 </div>
 );
}

function RekrutacjaCard({
 job,
 candidateId,
 candidateName,
}: {
 job: any;
 candidateId: number;
 candidateName: string;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const stageId: number | null = job.latest_stage_id ?? null;
 const jobId: number = job.job_id ?? job.id;
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
 queryClient.invalidateQueries({ queryKey: ["candidate-history"] });
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
 <div className="rounded-lg border border-border p-3 hover:border-primary/40 transition-colors">
 <div className="flex items-start justify-between gap-3 flex-wrap">
 <div className="min-w-0 flex-1">
 <Link
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

 // Wybrana rekrutacja (null = notatka ogólna, bez przypięcia). Gdy ustawiona,
 // @mention scope zawęża się do członków joba — spójnie z backendem.
 const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

 // Gdy profil otwarto z pipeline'u rekrutacji (`?from=job&jobId=N`), domyślnie
 // przypnij nową notatkę do tej rekrutacji zamiast „ogólnej". Czekamy aż lista
 // rekrutacji (`/history`) się załaduje i zawiera ten job; aplikujemy raz, żeby
 // nie nadpisywać ręcznego wyboru użytkownika.
 const defaultJobApplied = useRef(false);
 useEffect(() => {
 if (defaultJobApplied.current) return;
 if (defaultJobId == null) return;
 if (recList.length === 0) return; // lista jeszcze niezaładowana
 defaultJobApplied.current = true;
 if (recList.some((r: any) => Number(r.job_id) === Number(defaultJobId))) {
 setSelectedJobId(Number(defaultJobId));
 }
 }, [defaultJobId, recList]);

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

 const othersEditingNotes = viewers.filter(
 (v) => v.user_id !== currentUserId && v.editing.includes("notes"),
 );

 // Mentionable users dla render badge'y w liście notatek (zawsze global —
 // lista notatek miesza notatki z różnych rekrutacji). Autocomplete w
 // textarea używa osobnego, kontekstowego scope (job gdy wybrany).
 const { data: users = [] } = useMentionableUsers({ kind: "global" });
 const usersByEmail = useMemo(() => buildUsersByEmail(users), [users]);

 const mentionScope: MentionScope =
 selectedJobId != null
 ? { kind: "job", jobId: selectedJobId }
 : { kind: "global" };

 return (
 <div className="space-y-4">
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
 className="rounded-lg border border-border bg-card px-2 py-1 text-xs max-w-[22rem] truncate"
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
 {othersEditingNotes.length > 0 ? (
 <div className="text-xs text-[#F59E0B] flex items-center gap-1.5">
 <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#F59E0B] animate-pulse" />
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

// ── Pliki (multi-file CV — Faza A migracji Traffit) ────────────────────

function PlikiTab({ candidateId }: { candidateId: number }) {
 const { showError, showToast } = useToast();
 const [previewDoc, setPreviewDoc] = useState<CandidateDocument | null>(null);
 const { data: documents, isLoading, error } = useQuery<CandidateDocument[]>({
 queryKey: ["candidate-documents", candidateId],
 queryFn: async () => {
 const res = await api.get<CandidateDocument[]>(
 `/api/candidates/${candidateId}/documents`,
 );
 return res.data;
 },
 staleTime: 30_000,
 });

 function handlePreview(doc: CandidateDocument) {
 // DOCX nie renderuje się natywnie w przeglądarce — `window.open` na blobie
 // DOCX wymusza download (to był zgłoszony bug: „Podgląd" pobierał CV).
 // Otwieramy in-app modal (PDF/obraz/DOCX). Formaty bez podglądu (legacy
 // .doc, xlsx, odt, pages…) pobieramy od razu.
 if (previewKind(doc) === "unsupported") {
 showToast(
 "Podgląd niedostępny dla tego formatu — pobieram plik.",
 "success",
 );
 handleDownload(doc);
 return;
 }
 setPreviewDoc(doc);
 }

 async function handleDownload(doc: CandidateDocument) {
 try {
 await downloadDocumentBlob(candidateId, doc);
 } catch {
 showError("Nie udało się pobrać pliku.");
 }
 }

 if (isLoading) {
 return (
 <div className="text-sm text-muted-foreground py-6 text-center">
 Ładowanie plików…
 </div>
 );
 }

 if (error) {
 return (
 <div className="text-sm text-[hsl(var(--accent-error))] py-6 text-center">
 Błąd ładowania plików.
 </div>
 );
 }

 const docs = documents ?? [];
 if (docs.length === 0) {
 return (
 <div className="text-sm text-muted-foreground py-6 text-center">
 Brak plików. Dodaj CV lub inne dokumenty przez profil.
 </div>
 );
 }

 return (
 <>
 <div className="space-y-2">
 {docs.map((doc) => (
 <div
 key={doc.id}
 className="flex items-center gap-3 rounded-lg bg-background/40 border border-border p-3 hover:bg-background/60 transition-colors"
 >
 {fileIcon(doc.content_type)}
 <div className="flex-1 min-w-0">
 <div className="flex items-baseline gap-2 flex-wrap">
 <span className="font-medium text-sm text-foreground truncate">
 {doc.filename}
 </span>
 {doc.is_primary && (
 <Badge size="sm" variant="success">
 primary
 </Badge>
 )}
 {doc.external_source === "traffit" && (
 <Badge size="sm" variant="info">
 z Traffita
 </Badge>
 )}
 </div>
 <div className="text-xs text-muted-foreground mt-0.5">
 {formatFileSize(doc.size_bytes)}
 {doc.uploaded_at && (
 <>
 <span className="mx-1.5">·</span>
 <span>
 {new Date(doc.uploaded_at).toLocaleDateString("pl-PL")}
 </span>
 </>
 )}
 {doc.content_type && (
 <>
 <span className="mx-1.5">·</span>
 <span>{doc.content_type}</span>
 </>
 )}
 </div>
 </div>
 <div className="flex items-center gap-3 shrink-0">
 <button
 type="button"
 onClick={() => handlePreview(doc)}
 className="inline-flex items-center gap-1 text-sm text-[hsl(var(--accent-primary))] hover:underline"
 title="Otwórz podgląd pliku"
 >
 <Eye className="h-3.5 w-3.5" />
 Podgląd
 </button>
 <button
 type="button"
 onClick={() => handleDownload(doc)}
 className="inline-flex items-center gap-1 text-sm text-[hsl(var(--accent-primary))] hover:underline"
 title="Pobierz plik na dysk"
 >
 <Download className="h-3.5 w-3.5" />
 Pobierz
 </button>
 </div>
 </div>
 ))}
 </div>
 <FilePreviewModal
 doc={previewDoc}
 candidateId={candidateId}
 onClose={() => setPreviewDoc(null)}
 onDownload={handleDownload}
 />
 </>
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

interface SalarySummary {
 min: number;
 max: number;
 latest: number;
 currency: string;
 negotiable: boolean;
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
 salary_summary?: SalarySummary | null;
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
 salary_summary,
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
 className={cn("!py-3 shadow-smd","bg-card/95 backdrop-blur-sm"
 )}
 >
 {/* Header */}
 <div className="flex items-center gap-2 flex-wrap">
 <Sparkles className="h-4 w-4 text-primary shrink-0" />
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
 className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
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
 {salary_summary && (
 <Badge variant="plum" size="md">
 <Wallet className="h-3 w-3" />
 {salary_summary.min === salary_summary.max
 ? salary_summary.latest.toLocaleString("pl-PL")
 : `${salary_summary.min.toLocaleString("pl-PL")}–${salary_summary.max.toLocaleString("pl-PL")}`}{""}
 {salary_summary.currency}
 {salary_summary.negotiable ?"(neg.)" :""}
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
 <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-[#6b1120] mb-1.5">
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
