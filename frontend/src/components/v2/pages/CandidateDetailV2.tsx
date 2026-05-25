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
 Mail,
 MapPin,
 MessageSquare,
 PencilLine,
 PhoneCall,
 Plus,
 Printer,
 RefreshCcw,
 ShieldAlert,
 Sparkles,
 Star,
 Target,
 User,
 UserPlus,
 Wallet,
 X,
} from"lucide-react";
import api, {
 contractsApi,
 type ContractDraftResponse,
 candidateStageCvApi,
 type CVOriginalSnapshot,
 type CVBrandedState,
} from"@/lib/api";
import CallButton from"@/components/calls/CallButton";
import CallsTimeline from"@/components/calls/CallsTimeline";
import { useToast } from"@/components/Toast";
import { Input } from"@/components/ui/input";
import { Label } from"@/components/ui/label";
import { PinButton } from"@/components/v2/PinButton";
import { ExpandableText } from"@/components/v2/ExpandableText";
import {
 getCandidateSummaryLine,
 getEducationList,
 getLanguageList,
} from"@/components/v2/pages/candidate-profile-helpers";
import { getCurrentTitle, getExperienceLabel } from"@/components/v2/pages/candidate-list-helpers";
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
import { Textarea } from"@/components/ui/textarea";
import { MentionTextarea } from"@/components/v2/forms/MentionTextarea";
import { useMentionableUsers } from"@/hooks/useMentionableUsers";
import {
 buildUsersByEmail,
 renderWithMentions,
} from"@/lib/renderMentions";
import { EditCandidateModal } from"@/components/AppShell";
import { ScreeningSheet } from"@/components/v2/modals/ScreeningSheet";
import { SendEmailV2 } from"@/components/v2/modals/SendEmailV2";
import { AutentiEnvelopeCard } from"@/components/v2/contract/AutentiEnvelopeCard";
import { CVGeneratorV2 } from"@/components/v2/modals/CVGeneratorV2";
import { CVOriginalPreviewModal } from"@/components/v2/modals/CVOriginalPreviewModal";
import { CVBrandedEditModal } from"@/components/v2/modals/CVBrandedEditModal";
import { CVShareLinkModal } from"@/components/v2/modals/CVShareLinkModal";
import { Dialog, DialogContent } from"@/components/ui/dialog";
import { QuickAssignV2 } from"@/components/v2/modals/QuickAssignV2";
import { RISK_QUERY_KEY, RiskBadge } from"@/components/v2/RiskBadge";
import type { CandidateRiskProfile } from"@/types/candidate-risk";
import { SuggestedJobsWidget } from"@/components/SuggestedJobsWidget";
import { SuggestedPoolsWidget } from"@/components/candidates/SuggestedPoolsWidget";
import EmailThreadList from"@/components/emails/EmailThreadList";
import ScheduleInterviewModal from"@/components/calendar/ScheduleInterviewModal";
import { CandidatePipelinesWidget } from"@/components/CandidatePipelinesWidget";
import { RateHistoryWidget } from"@/components/RateHistoryWidget";
import { ConflictsWidget } from"@/components/ConflictsWidget";
import { FirefliesTranscriptsWidget } from"@/components/FirefliesTranscriptsWidget";
import { AddToMarketplaceButton } from"@/components/marketplace/AddToMarketplaceButton";
import {
 AtOurClientBanner,
 CandidateHighlights,
} from"@/components/v2/CandidateHighlights";
import { LinkedinSyncPanel } from"@/components/v2/LinkedinSyncPanel";
import { ActiveViewers } from"@/components/v2/presence/ActiveViewers";
import { usePresence, type PresenceViewer } from"@/hooks/usePresence";
import { useAuthStore } from"@/store/auth";
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

 // History API returns `{ jobs: [...], contracts: [...] }` — flatten jobs.
 const { data: historyRaw } = useQuery<{ jobs?: any[]; contracts?: any[] } | any[]>({
 queryKey: ["candidate-history", id],
 queryFn: () => api.get(`/api/candidates/${id}/history`).then((r) => r.data),
 enabled: !!id && activeTab === "rekrutacje",
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

 // Screenings & calls may come as array or { items: [...] } — normalize both.
 const { data: screeningsRaw } = useQuery<{ items?: any[] } | any[]>({
 queryKey: ["candidate-screenings", id],
 queryFn: () => api.get(`/api/candidates/${id}/screenings`).then((r) => r.data),
 enabled: !!id && activeTab === "screeningi",
 });
 const screenings: any[] = Array.isArray(screeningsRaw)
 ? screeningsRaw
 : (screeningsRaw?.items ?? []);

 const { data: callsRaw } = useQuery<{ items?: any[] } | any[]>({
 queryKey: ["candidate-calls", id],
 queryFn: () => api.get(`/api/candidates/${id}/calls`).then((r) => r.data),
 enabled: !!id && activeTab === "rozmowy",
 });
 const calls: any[] = Array.isArray(callsRaw) ? callsRaw : (callsRaw?.items ?? []);

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

 const handleAddNote = async () => {
 if (!noteText.trim()) return;
 setNoteSaving(true);
 try {
 await api.post("/api/notes/", {
 candidate_id: Number(id),
 content: noteText.trim(),
 note_type: "general",
 });
 setNoteText("");
 queryClient.invalidateQueries({ queryKey: ["candidate-timeline", id] });
 } finally {
 setNoteSaving(false);
 }
 };

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
 <Link
 href="/candidates"
 className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-primary"
 >
 <ArrowLeft className="h-4 w-4" /> Wróć do kandydatów
 </Link>
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
 {candidate.location && (
 <span className="inline-flex items-center gap-1.5">
 <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
 {candidate.location}
 </span>
 )}
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
 {Array.isArray(candidate.tags) && candidate.tags.length > 0 && (
 <div className="flex flex-wrap gap-1 mt-3">
 {candidate.tags.map((t: any, i: number) => (
 <span
 key={i}
 className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary"
 >
 #{typeof t === "string" ? t : t.name}
 </span>
 ))}
 </div>
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

 {/* Action row */}
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
 <Button
 size="sm"
 variant="secondary"
 onClick={() => setCvOpen(true)}
 >
 <FileText className="h-4 w-4" />
 Generuj CV
 </Button>
 <Button
 size="sm"
 variant="outline"
 onClick={() => setEmailOpen(true)}
 disabled={!candidate.email}
 >
 <Mail className="h-4 w-4" />
 Email
 </Button>
 <Button
 size="sm"
 variant="outline"
 onClick={() => setScheduleOpen(true)}
 disabled={!candidate.email}
 title={candidate.email ?"Zaplanuj interview w Outlook (M365)" :"Kandydat nie ma adresu email"}
 >
 <Calendar className="h-4 w-4" />
 Zaplanuj interview
 </Button>
 <Button size="sm" variant="ghost" onClick={() => setEditOpen(true)}>
 <PencilLine className="h-4 w-4" />
 Edytuj
 </Button>
 {candidate && (
 <AddToMarketplaceButton
 candidateId={candidate.id}
 candidateName={`${candidate.name} ${candidate.lastname}`}
 />
 )}
 {candidate && <PinButton candidateId={candidate.id} />}
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
 onOpenScreenings={() => setActiveTab("screeningi")}
 />
 )}

 {/* Suggested jobs (reuse v1 widget) */}
 <SuggestedJobsWidget candidateId={Number(id)} />

 {/* AI-suggested talent pools (migracja 0041) */}
 <SuggestedPoolsWidget candidateId={Number(id)} />
 </aside>

 {/* Main column — tabs */}
 <div className={cn("space-y-5 min-w-0", !embedded && "lg:order-1")}>
 {/* Tabs */}
 <Card variant="default" size="md" className="!p-0">
 <Tabs value={activeTab} onValueChange={setActiveTab}>
 {/* max-w-full + overflow-x-auto so the 10-tab list scrolls instead of
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
 <TabsTrigger value="screeningi">
 <Star className="h-3.5 w-3.5" />
 Screeningi
 {screenings.length > 0 && (
 <Badge size="sm" variant="soft">
 {screenings.length}
 </Badge>
 )}
 </TabsTrigger>
 <TabsTrigger value="rozmowy">
 <PhoneCall className="h-3.5 w-3.5" />
 Rozmowy
 </TabsTrigger>
 <TabsTrigger value="email">
 <Mail className="h-3.5 w-3.5" />
 Email
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
 <TabsContent value="screeningi" className="mt-0">
 <ScreeningsTab screenings={screenings} />
 </TabsContent>
 <TabsContent value="rozmowy" className="mt-0">
 <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
 <CallsTimeline calls={calls as any} />
 <FirefliesTranscriptsWidget candidateId={Number(id)} />
 </div>
 </TabsContent>
 <TabsContent value="email" className="mt-0">
 <EmailThreadList
 candidateId={Number(id)}
 candidateName={fullName}
 candidateEmail={candidate.email ?? null}
 />
 </TabsContent>
 <TabsContent value="notatki" className="mt-0">
 <NotatkiTab
 timeline={timeline ?? []}
 noteText={noteText}
 setNoteText={setNoteText}
 onAdd={handleAddNote}
 saving={noteSaving}
 viewers={presenceViewers}
 currentUserId={currentUser?.id}
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

 {/* Side widgets (below tabs) — full width under the grid */}
 <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
 <RateHistoryWidget candidateId={Number(id)} />
 <ConflictsWidget candidateId={Number(id)} />
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
 const experience: any[] = Array.isArray(candidate.experience)
 ? candidate.experience
 : [];
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
 const location = candidate.city ?? candidate.location ?? null;
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

 // CV quick-open — authenticated blob fetch via the shared axios instance
 // (Bearer interceptor) so it works cross-origin. cv_filename is candidate-level.
 const [cvOpening, setCvOpening] = useState(false);
 const openCv = async () => {
 setCvOpening(true);
 try {
 const res = await api.get(`/api/candidates/${candidate.id}/cv-download`, {
 responseType: "blob",
 });
 const url = URL.createObjectURL(res.data as Blob);
 window.open(url, "_blank", "noopener,noreferrer");
 setTimeout(() => URL.revokeObjectURL(url), 60_000);
 } catch {
 // Fall back to the Pliki tab when the candidate-level CV isn't available.
 onOpenTab?.("pliki");
 } finally {
 setCvOpening(false);
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
 <div className="space-y-6">
 {/* 1. Key facts — scannable grid (only tiles with data) */}
 {facts.length > 0 && (
 <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
 {facts.map((f) => (
 <FactTile key={f.label} icon={f.icon} label={f.label} value={f.value} />
 ))}
 </div>
 )}

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
 {item.content}
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
 <Button size="sm" variant="outline" onClick={openCv} disabled={cvOpening}>
 <FileText className="h-3.5 w-3.5" />
 {cvOpening ? "Otwieram…" : "Otwórz"}
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

function timelineItemLabel(item: any): string {
 if (item.type === "note") return `Notatka${item.note_type ? ` — ${item.note_type}` :""}`;
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
 {item.content && (
 <p className="text-sm text-foreground mt-1 whitespace-pre-line">
 {item.content}
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

function RekrutacjeTab({
 history,
 candidateName,
}: {
 history: any[];
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
 candidateName={candidateName}
 />
 ))}
 </div>
 );
}

function RekrutacjaCard({
 job,
 candidateName,
}: {
 job: any;
 candidateName: string;
}) {
 const queryClient = useQueryClient();
 const { showSuccess, showError } = useToast();
 const stageId: number | null = job.latest_stage_id ?? null;
 const [openOriginal, setOpenOriginal] = useState(false);
 const [openBranded, setOpenBranded] = useState(false);
 const [openShare, setOpenShare] = useState(false);
 const [confirmRefresh, setConfirmRefresh] = useState(false);

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

 {stageId != null ? (
 <div className="flex items-center gap-1.5 flex-wrap mt-3 pt-3 border-t border-border">
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
 </div>
 ) : null}

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
 </div>
 );
}

const SCREENING_TYPE_LABELS: Record<string, string> = {
 first_contact: "Pierwszy kontakt",
 technical: "Techniczny",
 soft_skills: "Soft skills",
 offer_negotiation: "Negocjacja oferty",
 general: "Ogólny",
};

function ScreeningsTab({ screenings }: { screenings: any[] }) {
 if (!Array.isArray(screenings) || screenings.length === 0) {
 return (
 <div className="py-10 text-center text-sm text-muted-foreground">
 Kandydat nie ma jeszcze żadnych screeningów.
 </div>
 );
 }
 return (
 <div className="space-y-2">
 {screenings.map((s: any) => (
 <div
 key={s.id}
 className="rounded-lg border border-border p-3 hover:border-primary/40 transition-colors"
 >
 <div className="flex items-center justify-between gap-2 flex-wrap">
 <div className="min-w-0 flex-1">
 <div className="flex items-center gap-2 flex-wrap">
 <span className="font-medium text-foreground">
 {SCREENING_TYPE_LABELS[s.screening_type] ?? s.screening_type ??"Screening"}
 </span>
 {s.overall_impression && (
 <div className="flex gap-0.5">
 {[1, 2, 3, 4, 5].map((n) => (
 <Star
 key={n}
 className={cn("h-3 w-3",
 n <= s.overall_impression
 ?"text-amber-500 fill-amber-500"
 :"text-[hsl(var(--border))] fill-[hsl(var(--border))]"
 )}
 />
 ))}
 </div>
 )}
 </div>
 <div className="text-xs text-muted-foreground mt-1">
 {s.created_at ? formatDate(s.created_at) : "brak daty"}
 {s.salary_expectation && (
 <>
 {" ·"}
 {s.salary_expectation.toLocaleString("pl-PL")}{""}
 {s.salary_currency ??"PLN"}
 {s.salary_negotiable ?"(neg.)" :""}
 </>
 )}
 </div>
 </div>
 {s.counteroffer_risk && (
 <Badge
 size="sm"
 variant={
 s.counteroffer_risk === "low"
 ?"success"
 : s.counteroffer_risk === "medium"
 ?"warning"
 :"danger"
 }
 >
 Counteroffer:{""}
 {s.counteroffer_risk === "low"
 ?"Niskie"
 : s.counteroffer_risk === "medium"
 ?"Średnie"
 :"Wysokie"}
 </Badge>
 )}
 </div>
 {s.notes && (
 <p className="text-sm text-foreground mt-2 whitespace-pre-line">
 {s.notes}
 </p>
 )}
 </div>
 ))}
 </div>
 );
}

function RozmowyTab({ calls }: { calls: any[] }) {
 if (!Array.isArray(calls) || calls.length === 0) {
 return (
 <div className="py-6 text-center text-sm text-muted-foreground">
 Brak zarejestrowanych rozmów.
 </div>
 );
 }
 return (
 <div className="space-y-2">
 {calls.map((c: any) => {
 const dur = c.duration_seconds;
 const mins = dur != null ? Math.floor(dur / 60) : null;
 const secs = dur != null ? dur % 60 : null;
 const durationLabel =
 mins != null ? `${mins}:${String(secs).padStart(2, "0")}` : null;
 return (
 <div
 key={c.id}
 className="rounded-lg border border-border p-3"
 >
 <div className="flex items-center gap-2 flex-wrap">
 <PhoneCall className="h-3.5 w-3.5 text-primary" />
 <span className="text-sm font-medium text-foreground">
 {c.direction === "outbound" ?"↗ Wychodząca" :"↙ Przychodząca"}
 </span>
 {durationLabel && (
 <Badge size="sm" variant="soft">
 {durationLabel}
 </Badge>
 )}
 <span className="ml-auto text-xs text-muted-foreground">
 {c.created_at ? formatRelativeTime(c.created_at) : ""}
 </span>
 </div>
 {c.summary && (
 <p className="text-sm text-foreground mt-2 whitespace-pre-line">
 {c.summary}
 </p>
 )}
 </div>
 );
 })}
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
 noteText,
 setNoteText,
 onAdd,
 saving,
 viewers = [],
 currentUserId,
 setEditing,
}: {
 timeline: any[];
 noteText: string;
 setNoteText: (v: string) => void;
 onAdd: () => void;
 saving: boolean;
 viewers?: PresenceViewer[];
 currentUserId?: number;
 setEditing?: (field: string, active: boolean) => void;
}) {
 const items = Array.isArray(timeline) ? timeline : [];
 const notes = items.filter((t: any) => t.type === "note");

 const othersEditingNotes = viewers.filter(
 (v) => v.user_id !== currentUserId && v.editing.includes("notes"),
 );

 // Mentionable users dla autocomplete + render badge'y w liście notatek.
 // Reużywamy jednego query — staleTime 60s w hooku.
 const { data: users = [] } = useMentionableUsers({ kind: "global" });
 const usersByEmail = useMemo(() => buildUsersByEmail(users), [users]);

 return (
 <div className="space-y-4">
 <div className="space-y-2">
 <MentionTextarea
 value={noteText}
 onChange={setNoteText}
 scope={{ kind: "global" }}
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
 <div className="flex justify-end">
 <Button
 size="sm"
 variant="primary"
 onClick={onAdd}
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
 {notes.map((n: any, i: number) => (
 <div
 key={n.id ?? i}
 className="rounded-lg bg-background/40 border border-border p-3"
 >
 <div className="flex items-baseline gap-2 text-xs text-muted-foreground flex-wrap">
 <span className="font-medium text-foreground">
 {n.note_type ? `Notatka — ${n.note_type}` :"Notatka"}
 </span>
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
 </div>
 <p className="text-sm text-foreground mt-1 whitespace-pre-line">
 {renderWithMentions(unwrapNoteContent(n.content), usersByEmail)}
 </p>
 </div>
 ))}
 </div>
 )}
 </div>
 );
}

// ── Pliki (multi-file CV — Faza A migracji Traffit) ────────────────────

interface CandidateDocument {
 id: number;
 filename: string;
 content_type: string | null;
 size_bytes: number | null;
 is_primary: boolean;
 uploaded_at: string | null;
 external_source: string | null;
 created_at: string;
}

function formatFileSize(bytes: number | null): string {
 if (!bytes) return"—";
 if (bytes < 1024) return `${bytes} B`;
 if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
 return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(contentType: string | null): React.ReactNode {
 // Visual hint by mime type
 return <FileText className="h-4 w-4 text-muted-foreground" />;
}

function PlikiTab({ candidateId }: { candidateId: number }) {
 const { showError } = useToast();
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

 // Backend `/content` proxy-stream'uje bytes z Object Storage (po Phase 3
 // migracji) lub z BYTEA (legacy). UŻYWAMY natywnego `fetch` zamiast axios
 // bo axios z `responseType: "blob"` cross-origin daje status 0 (XHR cancel
 // mid-stream) — testowane na prod 25.05.2026. Bare XHR i fetch z tymi
 // samymi nagłówkami zwracają 200. Workaround: pomijamy axios dla tego
 // jednego endpointu, jego interceptor 401-auto-redirect i tak by się tu
 // nie przydał bo Bearer JWT w localStorage jest zawsze dołączany ręcznie.
 async function fetchBlob(
 docId: number,
 disposition: "attachment" | "inline",
 ): Promise<Blob> {
 const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
 const token =
 typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
 const url = `${apiBase}/api/candidates/${candidateId}/documents/${docId}/content?disposition=${disposition}`;
 const res = await fetch(url, {
 method: "GET",
 headers: token ? { Authorization: `Bearer ${token}` } : {},
 });
 if (!res.ok) {
 throw new Error(`HTTP ${res.status}`);
 }
 return await res.blob();
 }

 async function handlePreview(doc: CandidateDocument) {
 try {
 const blob = await fetchBlob(doc.id, "inline");
 // Reuse content_type z DB — Blob default `application/octet-stream`
 // wymusiłby download zamiast preview.
 const typed = doc.content_type
 ? new Blob([blob], { type: doc.content_type })
 : blob;
 const url = URL.createObjectURL(typed);
 const win = window.open(url, "_blank", "noopener,noreferrer");
 if (!win) {
 showError("Nie udało się otworzyć podglądu — sprawdź blokadę popupów.");
 }
 setTimeout(() => URL.revokeObjectURL(url), 60_000);
 } catch {
 showError("Nie udało się otworzyć podglądu pliku.");
 }
 }

 async function handleDownload(doc: CandidateDocument) {
 try {
 const blob = await fetchBlob(doc.id, "attachment");
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url;
 a.download = doc.filename ?? `document-${doc.id}`;
 document.body.appendChild(a);
 a.click();
 document.body.removeChild(a);
 URL.revokeObjectURL(url);
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
 title="Otwórz podgląd w nowej karcie"
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
 onOpenScreenings,
}: {
 aiProfile: AiProfile;
 onOpenScreenings: () => void;
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
 <div className="flex justify-end pt-1">
 <Button size="sm" variant="ghost" onClick={onOpenScreenings}>
 Zobacz wszystkie screeningi →
 </Button>
 </div>
 </div>
 )}
 </Card>
 </div>
 );
}
