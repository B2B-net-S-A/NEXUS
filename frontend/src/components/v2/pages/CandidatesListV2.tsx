"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from"react";
import Link from"next/link";
import { useRouter, useSearchParams } from"next/navigation";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { useVirtualizer } from"@tanstack/react-virtual";
import {
 Banknote,
 Briefcase,
 Building2,
 ChevronRight,
 Columns3,
 Copy,
 Download,
 ExternalLink,
 FileArchive,
 FileText,
 Filter,
 GitCompare,
 Globe,
 LayoutGrid,
 Link as LinkIcon,
 Linkedin,
 Loader2,
 Mail,
 MapPin,
 MessageSquare,
 Phone,
 Plus,
 Rows3,
 Search,
 Sparkles,
 Table2,
 Target,
 Upload,
 Users,
 XCircle,
 X,
} from"lucide-react";
import api from"@/lib/api";
import {
 BulkCvDownloadError,
 downloadBulkCvs,
} from"@/lib/bulk-cv-download";
import { cn, formatRelativeTime } from"@/lib/utils";
import { AddCandidateModal } from"@/components/AppShell";
import { ImportCandidatesV2 } from"@/components/v2/modals/ImportCandidatesV2";
import { AddCandidateFromCVModal } from"@/components/v2/modals/AddCandidateFromCVModal";
import { QuickAssignV2 } from"@/components/v2/modals/QuickAssignV2";
import { GenerateInviteLinkV2 } from"@/components/v2/modals/GenerateInviteLinkV2";
import { CandidateDetailV2 } from"@/components/v2/pages/CandidateDetailV2";
import { Sheet, SheetContent } from"@/components/ui/sheet";
import { useUiStore } from"@/store/ui";
import { Avatar, AvatarFallback } from"@/components/ui/avatar";
import { Badge } from"@/components/ui/badge";
import { Button, buttonVariants } from"@/components/ui/button";
import { Checkbox } from"@/components/ui/checkbox";
import { Input } from"@/components/ui/input";
import {
 Popover,
 PopoverContent,
 PopoverTrigger,
} from"@/components/ui/popover";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { Kbd } from"@/components/ui/kbd";
import {
 CandidateHighlights,
 type AvailabilityStatus,
 type EmploymentInfo,
} from"@/components/v2/CandidateHighlights";
import { useAuthStore } from"@/store/auth";
import { LocationInput } from"@/components/v2/filters/LocationInput";
import { TalentPoolMultiSelect } from"@/components/v2/filters/TalentPoolMultiSelect";
import { AddedByMultiSelect } from"@/components/v2/filters/AddedByMultiSelect";
import { CompanyAutocomplete } from"@/components/v2/filters/CompanyAutocomplete";
import { FilterChipPopover } from"@/components/v2/filters/FilterChipPopover";
import { ClientMultiSelect } from"@/components/v2/filters/ClientMultiSelect";
import { ActiveFilterChips } from"@/components/v2/filters/ActiveFilterChips";
import { MultiSelectFilter } from"@/components/v2/filters/MultiSelectFilter";
import {
 AVAILABILITY_OPTIONS,
 CANDIDATE_STATUS_OPTIONS,
 EMPLOYMENT_OPTIONS,
 OPEN_TO_OPTIONS,
 PIPELINE_STAGE_OPTIONS,
 type AvailabilityValue,
 type CandidateStatusValue,
 type EmploymentValue,
 type OpenToValue,
 type PipelineStageValue,
} from"@/lib/filter-options";
import {
 decodeFilters,
 encodeFilters,
 type AvailabilityFilter,
 type CandidateFilters,
 type CandidateStatusFilter,
 type EmploymentFilter,
 type PipelineStageFilter,
} from"@/lib/url-filters";
import { CandidatesTiles } from"@/components/v2/pages/CandidatesTiles";
import {
 getCurrentCompany,
 getCurrentTitle,
 getExperienceLabel,
 getSkillList,
} from"@/components/v2/pages/candidate-list-helpers";
import { PinnedCandidatesBar } from"@/components/v2/filters/PinnedCandidatesBar";
import { MatchSnippet } from"@/components/v2/MatchSnippet";
import { RequireRole } from"@/components/RequireRole";
import { SavedSearchesMenu } from"@/components/v2/filters/SavedSearchesMenu";
import { AdvancedSearchPopover } from"@/components/v2/filters/AdvancedSearchPopover";
import { ROLE_LABELS, type UserRole } from"@/store/auth";

const STATUS_LABELS: Record<string, string> = {
 active: "Aktywny",
 passive: "Pasywny",
 blacklisted: "Zablokowany",
};

const STATUS_VARIANT: Record<string, "success" |"warning" |"danger"> = {
 active: "success",
 passive: "warning",
 blacklisted: "danger",
};

const SORT_OPTIONS = [
 { value: "newest", label: "Najnowsi" },
 { value: "oldest", label: "Najstarsi" },
 { value: "name", label: "Nazwisko (A-Z)" },
 { value: "relevance", label: "Trafność" },
];

function parseEnumCsv<T extends string>(
 raw: string | null | undefined,
 allowed: ReadonlyArray<T>,
): T[] {
 if (!raw) return [];
 const set = new Set<string>(allowed);
 return raw
 .split(",")
 .map((s) => s.trim())
 .filter((s): s is T => s.length > 0 && set.has(s));
}

interface Candidate {
 id: number;
 name?: string;
 lastname?: string;
 email?: string;
 phone?: string | null;
 position?: string;
 current_role?: string;
 source?: string;
 status?:"active" |"passive" |"blacklisted";
 availability_status?: AvailabilityStatus;
 employment?: EmploymentInfo;
 location?: string;
 city?: string | null;
 country?: string | null;
 years_it_experience?: number | null;
 skills?: unknown;
 experience?: unknown;
 linkedin_current_company?: string | null;
 linkedin_current_title?: string | null;
 created_at?: string;
 created_by_user?: { id: number; name: string } | null;
 match_stats?: { open_count: number; total_open: number; top_score: number };
 match_snippet?: string | null;
 talent_pools?: Array<{ id: number; name: string }>;
 linkedin_employment_changed_at?: string | null;
 open_to_side_projects?: boolean;
 open_to_sales_support?: boolean;
 open_to_expert_consult?: boolean;
 cv_filename?: string | null;
 active_recruitments?: Array<{
 job_id: number;
 job_title: string;
 client_name?: string | null;
 stage: string;
 }> | null;
 // Quick-glance triage fields — populated when API called with
 // include_last_activity=true. Backend already strips HTML + truncates
 // last_note_preview to 120 chars; rejection reason includes job + client
 // context; rate is formatted "150 PLN/h".
 last_note_preview?: string | null;
 last_rejection_reason?: string | null;
 last_rate?: string | null;
}

/** Polskie etykiety pipeline'u — używamy w kolumnie "Rekrutacje" tooltipach. */
const STAGE_LABELS: Record<string, string> = {
 new: "Nowy",
 prep_call: "Prep call",
 screening: "Screening",
 verified: "Zweryfikowany",
 interview: "Interview",
 cv_sent: "CV wysłane",
 client_interview: "Rozmowa u klienta",
 acceptance: "Akceptacja",
 negotiation: "Negocjacje",
 onboarding: "Onboarding",
 hired: "Zatrudniony",
 rejected: "Odrzucony",
 withdrawn: "Wycofany",
};

function stageLabel(stage: string): string {
 return STAGE_LABELS[stage] ?? stage;
}

// Role scopes the admin can target when saving candidates-columns as default.
// Order matches the user hierarchy (admin → user).
const SAVE_ROLE_OPTIONS: Array<{ value: UserRole |"_global"; label: string }> = [
 { value: "_global", label: "Dla wszystkich (domyślne)" },
 { value: "admin", label: `Dla: ${ROLE_LABELS.admin}` },
 { value: "head_of_recruitment", label: `Dla: ${ROLE_LABELS.head_of_recruitment}` },
 { value: "delivery_lead", label: `Dla: ${ROLE_LABELS.delivery_lead}` },
 { value: "tac", label: `Dla: ${ROLE_LABELS.tac}` },
 { value: "recruiter", label: `Dla: ${ROLE_LABELS.recruiter}` },
 { value: "sourcer", label: `Dla: ${ROLE_LABELS.sourcer}` },
 { value: "user", label: `Dla: ${ROLE_LABELS.user}` },
];

function sourceIcon(source?: string) {
 if (source === "linkedin")
 return <Linkedin className="h-3.5 w-3.5" style={{ color: "#0A66C2" }} />;
 if (source === "pracuj")
 return (
 <span className="text-[10px] font-bold leading-none" style={{ color: "#FF6600" }}>
 P
 </span>
 );
 return <Globe className="h-3 w-3 text-muted-foreground" />;
}

function matchBadgeVariant(
 topScore: number
): "success" |"soft" |"neutral" |"outline" {
 if (topScore >= 75) return"success";
 if (topScore >= 50) return"soft";
 return"neutral";
}

// All columns that can be shown/hidden via the"Kolumny" popover.
// Order in this array = visual order in the table.
const ALL_COLUMNS = [
 { id: "candidate", label: "Kandydat", required: true, width: "minmax(220px, 1.6fr)" },
 { id: "phone", label: "Telefon", required: false, width: "minmax(140px, 0.9fr)" },
 { id: "email", label: "Email", required: false, width: "minmax(180px, 1.2fr)" },
 { id: "cv", label: "CV", required: false, width: "minmax(80px, 0.5fr)" },
 { id: "recruitments", label: "Rekrutacje", required: false, width: "minmax(120px, 0.8fr)" },
 { id: "title", label: "Stanowisko", required: false, width: "minmax(160px, 1.1fr)" },
 { id: "company", label: "Firma", required: false, width: "minmax(140px, 1fr)" },
 { id: "location", label: "Lokalizacja", required: false, width: "minmax(120px, 0.7fr)" },
 { id: "experience", label: "Doświadczenie", required: false, width: "minmax(110px, 0.6fr)" },
 { id: "skills", label: "Skills", required: false, width: "minmax(180px, 1.3fr)" },
 { id: "rate", label: "Stawka", required: false, width: "minmax(110px, 0.7fr)" },
 { id: "last_note", label: "Ostatnia notatka", required: false, width: "minmax(200px, 1.4fr)" },
 { id: "rejection_reason", label: "Powód odrzucenia", required: false, width: "minmax(180px, 1.2fr)" },
 { id: "position", label: "Pozycja", required: false, width: "minmax(160px, 1fr)" },
 { id: "status", label: "Status", required: false, width: "minmax(120px, 0.8fr)" },
 { id: "match", label: "Match", required: false, width: "minmax(110px, 0.7fr)" },
 { id: "created", label: "Dodano", required: false, width: "minmax(120px, 0.7fr)" },
 { id: "added_by", label: "Dodał", required: false, width: "minmax(110px, 0.6fr)" },
] as const;
type ColumnId = (typeof ALL_COLUMNS)[number]["id"];

// Default columns shown to a new user (no global override, no per-user override).
// Triage-first set: dokładnie te kolumny, których rekruter potrzebuje BEZ
// klikania w kandydata po boolean searchu — identity + telefon + email + CV
// + status w innych rekrutacjach + stawka + ostatnia notatka + powód
// odrzucenia + data dodania. Title/Company/Skills/Status/Match/Position/
// Added-by są opt-in via "Kolumny" popover (recruiter który chce stanowisko/
// firmę z CV wciska Kolumny → Stanowisko / Firma).
const HARD_DEFAULT_COLUMNS: ColumnId[] = [
 "candidate",
 "phone",
 "email",
 "cv",
 "recruitments",
 "rate",
 "last_note",
 "rejection_reason",
 "created",
];

/** Otwiera CV w nowej karcie z auth-blob (Bearer JWT). Pipeline:
 *    1) GET /api/candidates/{id}/documents  → znajdź primary doc.
 *    2) GET /documents/{doc_id}/content?disposition=inline → backend
 *       proxy-streamuje bytes z Object Storage (Hetzner) lub BYTEA.
 *  Stary endpoint `/cv-download` jest broken dla rows zmigrowanych do
 *  Object Storage (2026-05-07) — szukał w lokalnym UPLOAD_DIR. Tutaj
 *  użyty endpoint ma już proxy-mode (patrz PlikiTab.fetchBlob, ta sama
 *  notatka o axios+responseType:blob cancelled cross-origin). */
function CandidateCvCell({ candidate }: { candidate: Candidate }) {
 const [opening, setOpening] = useState(false);
 if (!candidate.cv_filename) {
 return <span className="text-xs text-muted-foreground" aria-label="Brak CV">—</span>;
 }
 const openCv = async (e: React.MouseEvent) => {
 e.stopPropagation();
 if (opening) return;
 setOpening(true);
 try {
 const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "";
 const token =
 typeof window !== "undefined"
 ? localStorage.getItem("access_token")
 : null;
 const authHeaders: HeadersInit = token
 ? { Authorization: `Bearer ${token}` }
 : {};

 const docsRes = await fetch(
 `${apiBase}/api/candidates/${candidate.id}/documents`,
 { headers: authHeaders },
 );
 if (!docsRes.ok) throw new Error(`documents HTTP ${docsRes.status}`);
 const docs: Array<{
 id: number;
 is_primary?: boolean;
 content_type?: string | null;
 }> = await docsRes.json();
 const primary = docs.find((d) => d.is_primary) ?? docs[0];
 if (!primary) throw new Error("no document");

 const fileRes = await fetch(
 `${apiBase}/api/candidates/${candidate.id}/documents/${primary.id}/content?disposition=inline`,
 { headers: authHeaders },
 );
 if (!fileRes.ok) throw new Error(`content HTTP ${fileRes.status}`);
 const blob = await fileRes.blob();
 const ct =
 primary.content_type ||
 fileRes.headers.get("content-type") ||
 "application/pdf";
 const typed = new Blob([blob], { type: ct });
 const url = URL.createObjectURL(typed);
 window.open(url, "_blank", "noopener,noreferrer");
 setTimeout(() => URL.revokeObjectURL(url), 60_000);
 } catch {
 // Cicho — kandydat nie ma CV / pliku, fallback na detail przez klik wiersza.
 } finally {
 setOpening(false);
 }
 };
 return (
 <button
 type="button"
 onClick={openCv}
 disabled={opening}
 title="Otwórz CV w nowej karcie"
 aria-label="Otwórz CV kandydata w nowej karcie"
 className="inline-flex h-7 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/5 px-2 py-0 text-xs font-medium text-primary transition-colors hover:border-primary/60 hover:bg-primary/10 disabled:opacity-50"
 >
 {opening ? (
 <Loader2 className="h-3 w-3 animate-spin" />
 ) : (
 <FileText className="h-3 w-3" />
 )}
 <span>CV</span>
 </button>
 );
}

/** Pokazuje liczbę aktywnych rekrutacji (nie-terminalnych stages) z popoverem
 *  na hover/click z listą {job_title, klient, stage}. Klik w wpis → /jobs/{id}. */
function CandidateRecruitmentsCell({ candidate }: { candidate: Candidate }) {
 const recs = candidate.active_recruitments ?? [];
 if (recs.length === 0) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <Popover>
 <PopoverTrigger asChild>
 <button
 type="button"
 onClick={(e) => e.stopPropagation()}
 className="inline-flex items-center gap-1"
 title={`Aktywne rekrutacje: ${recs.length}`}
 >
 <Badge size="sm" variant="soft" className="gap-1">
 <Briefcase className="h-3 w-3" />
 {recs.length}
 </Badge>
 </button>
 </PopoverTrigger>
 <PopoverContent
 align="start"
 className="w-80 p-0"
 onClick={(e) => e.stopPropagation()}
 >
 <div className="px-3 py-2 border-b border-border">
 <div className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
 Aktywne rekrutacje ({recs.length})
 </div>
 </div>
 <ul className="max-h-80 overflow-auto">
 {recs.map((r) => (
 <li
 key={`${r.job_id}-${r.stage}`}
 className="border-b border-border last:border-0"
 >
 <Link
 href={`/jobs/${r.job_id}`}
 onClick={(e) => e.stopPropagation()}
 className="flex items-start gap-2 px-3 py-2 hover:bg-primary/5"
 >
 <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground mt-1" />
 <div className="min-w-0 flex-1">
 <div className="text-sm font-medium text-foreground truncate">
 {r.job_title}
 </div>
 <div className="text-xs text-muted-foreground truncate">
 {r.client_name ?? "—"}
 </div>
 </div>
 <Badge size="sm" variant="outline" className="shrink-0">
 {stageLabel(r.stage)}
 </Badge>
 </Link>
 </li>
 ))}
 </ul>
 </PopoverContent>
 </Popover>
 );
}

interface CandidateCellProps {
 columnId: ColumnId;
 candidate: Candidate;
 fullName: string;
 initials: string;
 density: "compact" |"cozy";
 stats: Candidate["match_stats"];
 searchTerms: string[];
 onOpenDetail: () => void;
}

/** Single-cell renderer for the candidates table. Renders one cell per visible
 *  column. Decoupled from the row component so we can iterate over
 *  `visibleColumns` without a giant switch inline in JSX. */
function CandidateCell({
 columnId,
 candidate,
 fullName,
 initials,
 density,
 stats,
 searchTerms,
 onOpenDetail,
}: CandidateCellProps) {
 switch (columnId) {
 case "candidate": {
 const snippet = candidate.match_snippet;
 return (
 <button
 type="button"
 onClick={onOpenDetail}
 className="flex items-center gap-3 min-w-0 text-left"
 >
 <Avatar size={density === "compact" ?"sm" :"md"}>
 <AvatarFallback>{initials}</AvatarFallback>
 </Avatar>
 <div className="min-w-0">
 <div className="font-medium text-foreground truncate hover:text-primary">
 {fullName}
 </div>
 <div className="text-xs text-muted-foreground flex items-center gap-1.5 truncate">
 {sourceIcon(candidate.source)}
 <span className="truncate">
 {candidate.email ?? candidate.location ??"—"}
 </span>
 </div>
 {snippet && searchTerms.length > 0 && (
 <MatchSnippet
 snippet={snippet}
 terms={searchTerms}
 className="block truncate mt-0.5"
 />
 )}
 </div>
 </button>
 );
 }
 case "phone": {
 const phone = candidate.phone;
 if (!phone) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 const onCopy = (e: React.MouseEvent) => {
 e.stopPropagation();
 if (typeof navigator !=="undefined" && navigator.clipboard) {
 void navigator.clipboard.writeText(phone);
 }
 };
 return (
 <div className="flex items-center gap-1.5 min-w-0 group">
 <Phone className="h-3 w-3 shrink-0 text-muted-foreground" />
 <a
 href={`tel:${phone}`}
 onClick={(e) => e.stopPropagation()}
 className="text-sm text-foreground truncate hover:text-primary"
 title={phone}
 >
 {phone}
 </a>
 <button
 type="button"
 onClick={onCopy}
 title="Kopiuj numer"
 className="opacity-0 group-hover:opacity-100 h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:bg-primary/10 hover:text-primary"
 >
 <Copy className="h-3 w-3" />
 </button>
 </div>
 );
 }
 case "email": {
 const email = candidate.email;
 if (!email) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 const onCopy = (e: React.MouseEvent) => {
 e.stopPropagation();
 if (typeof navigator !== "undefined" && navigator.clipboard) {
 void navigator.clipboard.writeText(email);
 }
 };
 return (
 <div className="flex items-center gap-1.5 min-w-0 group">
 <Mail className="h-3 w-3 shrink-0 text-muted-foreground" />
 <a
 href={`mailto:${email}`}
 onClick={(e) => e.stopPropagation()}
 className="text-sm text-foreground truncate hover:text-primary"
 title={email}
 >
 {email}
 </a>
 <button
 type="button"
 onClick={onCopy}
 title="Kopiuj email"
 className="opacity-0 group-hover:opacity-100 h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:bg-primary/10 hover:text-primary"
 >
 <Copy className="h-3 w-3" />
 </button>
 </div>
 );
 }
 case "cv": {
 return <CandidateCvCell candidate={candidate} />;
 }
 case "recruitments": {
 return <CandidateRecruitmentsCell candidate={candidate} />;
 }
 case "title": {
 const title = getCurrentTitle(candidate);
 return (
 <span
 className="text-sm text-foreground truncate block"
 title={title ?? undefined}
 >
 {title ??"—"}
 </span>
 );
 }
 case "company": {
 const company = getCurrentCompany(candidate);
 if (!company) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <div className="flex items-center gap-1.5 min-w-0">
 <Building2 className="h-3 w-3 shrink-0 text-muted-foreground" />
 <span
 className="text-sm text-foreground truncate"
 title={company}
 >
 {company}
 </span>
 </div>
 );
 }
 case "location": {
 const loc = candidate.city ?? candidate.location ?? null;
 if (!loc) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <div className="flex items-center gap-1.5 min-w-0">
 <MapPin className="h-3 w-3 shrink-0 text-muted-foreground" />
 <span className="text-sm text-foreground truncate" title={loc}>
 {loc}
 </span>
 </div>
 );
 }
 case "experience": {
 const tag = getExperienceLabel(candidate.years_it_experience);
 if (!tag) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <Badge size="sm" variant={tag.variant}>
 {tag.label}
 </Badge>
 );
 }
 case "skills": {
 const skills = getSkillList(candidate, 8);
 if (skills.length === 0) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 const shown = skills.slice(0, 3);
 const overflow = skills.length - shown.length;
 return (
 <div className="flex items-center gap-1 min-w-0 flex-wrap">
 {shown.map((s) => (
 <Badge key={s} size="sm" variant="outline" className="font-normal">
 {s}
 </Badge>
 ))}
 {overflow > 0 && (
 <span
 className="text-[11px] text-muted-foreground"
 title={skills.slice(3).join(",")}
 >
 +{overflow}
 </span>
 )}
 </div>
 );
 }
 case "rate": {
 const rate = candidate.last_rate;
 if (!rate) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <div className="flex items-center gap-1.5 min-w-0">
 <Banknote className="h-3 w-3 shrink-0 text-muted-foreground" />
 <span
 className="text-sm font-medium text-foreground truncate"
 title={rate}
 >
 {rate}
 </span>
 </div>
 );
 }
 case "last_note": {
 const note = candidate.last_note_preview;
 if (!note) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <div className="flex items-start gap-1.5 min-w-0">
 <MessageSquare className="h-3 w-3 shrink-0 text-muted-foreground mt-0.5" />
 <span
 className="text-xs text-muted-foreground line-clamp-2"
 title={note}
 >
 {note}
 </span>
 </div>
 );
 }
 case "rejection_reason": {
 const reason = candidate.last_rejection_reason;
 if (!reason) {
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 return (
 <div className="flex items-start gap-1.5 min-w-0">
 <XCircle className="h-3 w-3 shrink-0 text-rose-500 mt-0.5" />
 <span
 className="text-xs text-foreground line-clamp-2"
 title={reason}
 >
 {reason}
 </span>
 </div>
 );
 }
 case "position": {
 // Legacy column kept for back-compat — recruiters who opt-in still get
 // the old "Pozycja" value (rarely populated outside of pipeline rows).
 return (
 <span className="text-sm text-foreground truncate block">
 {candidate.position ?? candidate.current_role ??"—"}
 </span>
 );
 }
 case "status": {
 return (
 <div className="min-w-0">
 <CandidateHighlights candidate={candidate} variant="compact" />
 </div>
 );
 }
 case "match": {
 if (stats && stats.open_count > 0) {
 return (
 <Badge
 size="sm"
 variant={matchBadgeVariant(stats.top_score)}
 className="gap-1"
 >
 <Target className="h-3 w-3" />
 {stats.open_count}/{stats.total_open} · top{""}
 {Math.round(stats.top_score)}
 </Badge>
 );
 }
 return <span className="text-xs text-muted-foreground">—</span>;
 }
 case "created": {
 return (
 <span className="text-xs text-muted-foreground truncate block">
 {candidate.created_at
 ? formatRelativeTime(candidate.created_at)
 :"—"}
 </span>
 );
 }
 case "added_by": {
 return (
 <span
 className="text-xs text-muted-foreground truncate block"
 title={
 candidate.created_by_user
 ? candidate.created_by_user.name
 :"Import systemowy"
 }
 >
 {candidate.created_by_user
 ? candidate.created_by_user.name
 :"System"}
 </span>
 );
 }
 default:
 return null;
 }
}

export function CandidatesListV2() {
 const router = useRouter();
 const searchParams = useSearchParams();
 const density = useUiStore((s) => s.density);
 const setDensity = useUiStore((s) => s.setDensity);
 const candidatesView = useUiStore((s) => s.candidatesView);
 const setCandidatesView = useUiStore((s) => s.setCandidatesView);
 const columnPrefs = useUiStore((s) => s.columnPreferences);
 const setColumnPref = useUiStore((s) => s.setColumnPreference);
 const parentRef = useRef<HTMLDivElement>(null);
 const queryClient = useQueryClient();

 // Global default column config (admin-editable via PUT /api/settings/candidates-columns).
 // Per-user overrides live in the zustand store — they always win.
 const { data: globalColumnsConfig } = useQuery<{ columns: ColumnId[] }>({
 queryKey: ["settings","candidates-columns"],
 queryFn: () =>
 api.get("/api/settings/candidates-columns").then((r) => r.data),
 staleTime: 60_000,
 });
 const globalDefaultHiddenCols: ColumnId[] = useMemo(() => {
 const visibleIds = new Set<string>(
 globalColumnsConfig?.columns ?? HARD_DEFAULT_COLUMNS
 );
 return ALL_COLUMNS.filter((c) => !c.required && !visibleIds.has(c.id)).map(
 (c) => c.id as ColumnId
 );
 }, [globalColumnsConfig]);
 const userOverride = columnPrefs["candidates-v2"];
 const hiddenColumns = new Set<string>(
 userOverride ?? globalDefaultHiddenCols
 );
 const visibleColumns = ALL_COLUMNS.filter((c) => !hiddenColumns.has(c.id));
 // CSS grid template: 32px checkbox + each visible column's width + 60px action slot.
 const gridTemplateColumns = [
 "32px",
 ...visibleColumns.map((c) => c.width),
 "60px",
 ].join(" ");
 // Aggregate the user's positive search phrases (simple q + advanced
 // q_all + q_any). MatchSnippet uses these to <mark>-highlight matched
 // substrings inside each row's snippet. Skipped: q_none — exclusion
 // phrases shouldn't be highlighted as matches.

 // Admin scope for the"Zapisz jako domyślne" action. `"_global"` means save
 // the baseline that applies to every role without a specific override.
 const [saveTargetRole, setSaveTargetRole] = useState<UserRole |"_global">("_global"
 );

 const saveColumnDefault = useMutation({
 mutationFn: (args: { columns: ColumnId[]; role: UserRole |"_global" }) =>
 api
 .put("/api/settings/candidates-columns", {
 columns: args.columns,
 role: args.role === "_global" ? null : args.role,
 })
 .then((r) => r.data),
 onSuccess: (_data, variables) => {
 queryClient.invalidateQueries({
 queryKey: ["settings","candidates-columns"],
 });
 const label =
 variables.role === "_global"
 ?"dla wszystkich"
 : `dla roli: ${ROLE_LABELS[variables.role]}`;
 setToast?.(`Zapisano jako domyślne ${label}.`);
 },
 });
 const resetToGlobalDefault = () =>
 useUiStore.getState().clearColumnPreference("candidates-v2");

 // URL state ---------------------------------------------------
 const [search, setSearch] = useState(searchParams.get("q") ??"");
 const [statusFilter, setStatusFilter] = useState<CandidateStatusFilter[]>(
 parseEnumCsv(
 searchParams.get("status"),
 ["active","passive","blacklisted"] as const,
 ),
 );
 const [sortBy, setSortBy] = useState(searchParams.get("sort") ??"newest");
 const [page, setPage] = useState(Number(searchParams.get("page") ??"1"));
 const [remoteFilter, setRemoteFilter] = useState<string[]>(
 searchParams.get("remote")?.split(",").filter(Boolean) ?? []
 );
 const [skillsFilter, setSkillsFilter] = useState<string[]>(
 searchParams.get("skills")?.split(",").filter(Boolean) ?? []
 );
 const [skillInput, setSkillInput] = useState("");
 const [employmentFilter, setEmploymentFilter] = useState<EmploymentFilter[]>(
 parseEnumCsv(
 searchParams.get("employment"),
 ["at_client","available"] as const,
 ),
 );
 const [availabilityFilter, setAvailabilityFilter] = useState<AvailabilityFilter[]>(
 parseEnumCsv(
 // Backward-compat: legacy URLs used `avail`; new ones use `availability`.
 searchParams.get("availability") ?? searchParams.get("avail"),
 ["actively_looking","open_to_offers","not_looking","unknown"] as const,
 ),
 );
 const [pipelineStageFilter, setPipelineStageFilter] = useState<PipelineStageFilter[]>(
 parseEnumCsv(
 searchParams.get("stage"),
 [
 "new",
 "prep_call",
 "screening",
 "verified",
 "interview",
 "cv_sent",
 "client_interview",
 "acceptance",
 "negotiation",
 "onboarding",
 "hired",
 "rejected",
 "withdrawn",
 ] as const,
 ),
 );
 const [locationFilter, setLocationFilter] = useState<string>(
 searchParams.get("loc") ??""
 );
 const [poolIds, setPoolIds] = useState<number[]>(
 (searchParams.get("pool") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 const [addedByIds, setAddedByIds] = useState<number[]>(
 (searchParams.get("added_by") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 // LinkedIn-Recruiter-style filters — pipe-separated to allow commas in company names
 const [currentCompanyFilter, setCurrentCompanyFilter] = useState<string[]>(
 (searchParams.get("cur_co") ??"").split("|").filter(Boolean)
 );
 const [pastCompanyFilter, setPastCompanyFilter] = useState<string[]>(
 (searchParams.get("past_co") ??"").split("|").filter(Boolean)
 );
 const [currentTitleFilter, setCurrentTitleFilter] = useState<string[]>(
 (searchParams.get("title") ??"").split("|").filter(Boolean)
 );
 const [workedAtClientIds, setWorkedAtClientIds] = useState<number[]>(
 (searchParams.get("client_hist") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 // LinkedIn-detected job change window —"1","2", or"3" months. Empty = off.
 const [recentlyChangedJobs, setRecentlyChangedJobs] = useState<string>(
 searchParams.get("rcj") ??""
 );
 // Engagement openness — any of {side_projects, sales_support, expert_consult}, OR-combined.
 const [openToFilter, setOpenToFilter] = useState<OpenToValue[]>(
 (searchParams.get("open_to") ??"")
 .split(",")
 .filter((v): v is OpenToValue =>
 v === "side_projects" || v === "sales_support" || v === "expert_consult"
 )
 );
 // Traffit-style boolean buckets — pipe-separated in URL, serialized as repeating
 // query params when calling the API.
 const [qAll, setQAll] = useState<string[]>(
 (searchParams.get("q_all") ??"").split("|").filter(Boolean)
 );
 const [qAny, setQAny] = useState<string[]>(
 (searchParams.get("q_any") ??"").split("|").filter(Boolean)
 );
 const [qNone, setQNone] = useState<string[]>(
 (searchParams.get("q_none") ??"").split("|").filter(Boolean)
 );
 // Boolean-search panel visibility. Opens automatically when the URL arrives
 // with any q_all/q_any/q_none — the user has filters and needs to see them.
 // Otherwise opt-in via the `Boolean` toggle next to the search input. Persists
 // across reloads via `?boolean=1` once opened so the recruiter doesn't lose
 // their workspace.
 const [showAdvanced, setShowAdvanced] = useState<boolean>(
 () =>
 searchParams.get("boolean") === "1" ||
 qAll.length > 0 ||
 qAny.length > 0 ||
 qNone.length > 0
 );
 const currentUser = useAuthStore((s) => s.user);

 // Sync URL -----------------------------------------------------
 useEffect(() => {
 const params = new URLSearchParams();
 if (search) params.set("q", search);
 if (statusFilter.length) params.set("status", statusFilter.join(","));
 if (sortBy && sortBy !== "newest") params.set("sort", sortBy);
 if (page > 1) params.set("page", String(page));
 if (remoteFilter.length) params.set("remote", remoteFilter.join(","));
 if (skillsFilter.length) params.set("skills", skillsFilter.join(","));
 if (employmentFilter.length) params.set("employment", employmentFilter.join(","));
 if (availabilityFilter.length) params.set("availability", availabilityFilter.join(","));
 if (pipelineStageFilter.length) params.set("stage", pipelineStageFilter.join(","));
 if (locationFilter) params.set("loc", locationFilter);
 if (poolIds.length) params.set("pool", poolIds.join(","));
 if (addedByIds.length) params.set("added_by", addedByIds.join(","));
 if (currentCompanyFilter.length) params.set("cur_co", currentCompanyFilter.join("|"));
 if (pastCompanyFilter.length) params.set("past_co", pastCompanyFilter.join("|"));
 if (currentTitleFilter.length) params.set("title", currentTitleFilter.join("|"));
 if (workedAtClientIds.length) params.set("client_hist", workedAtClientIds.join(","));
 if (recentlyChangedJobs) params.set("rcj", recentlyChangedJobs);
 if (openToFilter.length) params.set("open_to", openToFilter.join(","));
 if (qAll.length) params.set("q_all", qAll.join("|"));
 if (qAny.length) params.set("q_any", qAny.join("|"));
 if (qNone.length) params.set("q_none", qNone.join("|"));
 // Persist Boolean-panel visibility ONLY when the user toggled it open
 // without any active phrases yet — otherwise the q_all/q_any/q_none params
 // already imply the panel should be shown (no need to clutter the URL).
 if (
 showAdvanced &&
 qAll.length === 0 &&
 qAny.length === 0 &&
 qNone.length === 0
 ) {
 params.set("boolean", "1");
 }
 const qs = params.toString();
 window.history.replaceState(null, "", qs ? `/candidates?${qs}` :"/candidates");
 }, [
 search,
 statusFilter,
 sortBy,
 page,
 remoteFilter,
 skillsFilter,
 employmentFilter,
 availabilityFilter,
 pipelineStageFilter,
 locationFilter,
 poolIds,
 addedByIds,
 currentCompanyFilter,
 pastCompanyFilter,
 currentTitleFilter,
 workedAtClientIds,
 recentlyChangedJobs,
 openToFilter,
 qAll,
 qAny,
 qNone,
 showAdvanced,
 ]);

 // Data --------------------------------------------------------
 const { data, isLoading, isFetching } = useQuery({
 queryKey: ["candidates-v2",
 search,
 statusFilter,
 page,
 sortBy,
 remoteFilter,
 skillsFilter,
 employmentFilter,
 availabilityFilter,
 pipelineStageFilter,
 locationFilter,
 poolIds,
 addedByIds,
 currentCompanyFilter,
 pastCompanyFilter,
 currentTitleFilter,
 workedAtClientIds,
 recentlyChangedJobs,
 openToFilter,
 qAll,
 qAny,
 qNone,
 ],
 queryFn: () =>
 api
 .get("/api/candidates", {
 params: {
 q: search || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 page,
 sort: sortBy || undefined,
 include_match_stats: true,
 include_active_recruitments: true,
 include_last_activity: true,
 match_threshold: 35,
 skills: skillsFilter.length ? skillsFilter : undefined,
 skill_combine: skillsFilter.length > 1 ?"AND" : undefined,
 remote_policy: remoteFilter.length ? remoteFilter : undefined,
 employment: employmentFilter.length ? employmentFilter : undefined,
 availability: availabilityFilter.length ? availabilityFilter : undefined,
 pipeline_stage: pipelineStageFilter.length ? pipelineStageFilter : undefined,
 location: locationFilter || undefined,
 talent_pool_id: poolIds.length ? poolIds : undefined,
 added_by_user_id: addedByIds.length ? addedByIds : undefined,
 current_company: currentCompanyFilter.length ? currentCompanyFilter : undefined,
 past_company: pastCompanyFilter.length ? pastCompanyFilter : undefined,
 current_title: currentTitleFilter.length ? currentTitleFilter : undefined,
 worked_at_client_id: workedAtClientIds.length ? workedAtClientIds : undefined,
 recently_changed_jobs: recentlyChangedJobs
 ? Number(recentlyChangedJobs)
 : undefined,
 open_to: openToFilter.length ? openToFilter : undefined,
 q_all: qAll.length ? qAll : undefined,
 q_any: qAny.length ? qAny : undefined,
 q_none: qNone.length ? qNone : undefined,
 },
 paramsSerializer: { indexes: null },
 })
 .then((r) => r.data),
 });

 const items: Candidate[] = data?.items ?? [];
 const total = data?.total ?? 0;
 const pageSize = data?.page_size ?? 20;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));

 // Positive search phrases used for <mark> highlighting in row snippets.
 // We memo on the raw arrays (not deps stringified) — referential equality
 // is enough since each setter creates a new array. q_none is omitted by
 // design: exclusion phrases shouldn't render as matches.
 const searchTerms = useMemo(() => {
 const terms: string[] = [];
 const simple = search.trim();
 if (simple) terms.push(simple);
 for (const list of [qAll, qAny]) {
 for (const t of list) {
 const v = t.trim();
 if (v) terms.push(v);
 }
 }
 return terms;
 }, [search, qAll, qAny]);

 // Virtualization ---------------------------------------------
 const rowHeight = density === "compact" ? 52 : 72;
 const virtualizer = useVirtualizer({
 count: items.length,
 getScrollElement: () => parentRef.current,
 estimateSize: () => rowHeight,
 overscan: 10,
 });

 // Selection ---------------------------------------------------
 const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
 const toggleId = useCallback((id: number) => {
 setSelectedIds((prev) => {
 const next = new Set(prev);
 if (next.has(id)) next.delete(id);
 else next.add(id);
 return next;
 });
 }, []);
 const clearSelection = () => setSelectedIds(new Set());
 const selectAllVisible = () => {
 setSelectedIds(new Set(items.map((i) => i.id)));
 };

 // Modals + assigns -------------------------------------------
 const [showAdd, setShowAdd] = useState(false);
 const [showImport, setShowImport] = useState(false);
 const [showAddFromCV, setShowAddFromCV] = useState(false);
 const [showInvite, setShowInvite] = useState(false);
 const [showBulkPool, setShowBulkPool] = useState(false);
 const [bulkPoolPending, setBulkPoolPending] = useState(false);
 const [assignFor, setAssignFor] = useState<{ id: number; name: string } | null>(null);
 const [detailId, setDetailId] = useState<number | null>(null);
 // 1-based position of the open profile within the filtered set. Updated on
 // row click and on prev/next navigation inside the modal so CandidateNav
 // can show"N / total" and walk page boundaries.
 const [detailPosition, setDetailPosition] = useState<number>(1);
 const [showToast, setToast] = useState<string | null>(null);
 const [isDownloadingZip, setIsDownloadingZip] = useState(false);
 const toastOnSuccess = (msg: string) => {
 setToast(msg);
 setTimeout(() => setToast(null), 4000);
 };

 const doBulkAddToPool = async (poolId: number) => {
 if (selectedIds.size === 0 || bulkPoolPending) return;
 setBulkPoolPending(true);
 try {
 const res = await api.post(`/api/talent-pools/${poolId}/bulk-add`, {
 candidate_ids: Array.from(selectedIds),
 });
 const { added, already_in_pool, not_found } = res.data ?? {};
 const parts: string[] = [];
 if (added) parts.push(`dodano ${added}`);
 if (already_in_pool) parts.push(`już w puli: ${already_in_pool}`);
 if (not_found) parts.push(`brak: ${not_found}`);
 toastOnSuccess(parts.length ? parts.join(",") : "Brak zmian");
 queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
 setShowBulkPool(false);
 clearSelection();
 } catch (e) {
 const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??"Nie udało się dodać do puli";
 toastOnSuccess(msg);
 } finally {
 setBulkPoolPending(false);
 }
 };

 const doBulkDownloadCvs = async () => {
 if (selectedIds.size === 0 || isDownloadingZip) return;
 setIsDownloadingZip(true);
 toastOnSuccess("Przygotowywanie ZIP…");
 try {
 const { includedCount, skippedCount } = await downloadBulkCvs(
 Array.from(selectedIds)
 );
 toastOnSuccess(
 skippedCount > 0
 ? `Pobrano ${includedCount} CV. Pominięto: ${skippedCount} (brak CV).`
 : `Pobrano ${includedCount} CV.`
 );
 } catch (e) {
 toastOnSuccess(
 e instanceof BulkCvDownloadError
 ? e.message : "Pobieranie nie powiodło się."
 );
 } finally {
 setIsDownloadingZip(false);
 }
 };

 // Export
 const doExport = async (format: "csv" |"xlsx") => {
 const params = new URLSearchParams();
 if (search) params.set("q", search);
 if (statusFilter.length) {
 // Repeat the param so backend `Optional[list[CandidateStatus]]` parses it.
 statusFilter.forEach((s) => params.append("status", s));
 }
 params.set("format", format);
 const apiBase = process.env.NEXT_PUBLIC_API_URL ||"";
 const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
 const res = await fetch(`${apiBase}/api/candidates/export?${params}`, {
 headers: token ? { Authorization: `Bearer ${token}` } : {},
 });
 if (!res.ok) {
 toastOnSuccess("Eksport nie powiódł się.");
 return;
 }
 const blob = await res.blob();
 const url = URL.createObjectURL(blob);
 const a = document.createElement("a");
 a.href = url;
 a.download = `kandydaci-${new Date().toISOString().slice(0, 10)}.${format}`;
 a.click();
 URL.revokeObjectURL(url);
 };

 // Skill input helpers
 const addSkill = (s: string) => {
 const trimmed = s.trim();
 if (!trimmed || skillsFilter.includes(trimmed)) return;
 setSkillsFilter([...skillsFilter, trimmed]);
 setSkillInput("");
 setPage(1);
 };
 const removeSkill = (s: string) =>
 setSkillsFilter(skillsFilter.filter((x) => x !== s));

 const activeFilterCount =
 (remoteFilter.length > 0 ? 1 : 0) +
 (skillsFilter.length > 0 ? 1 : 0) +
 (locationFilter ? 1 : 0) +
 (poolIds.length > 0 ? 1 : 0) +
 (addedByIds.length > 0 ? 1 : 0) +
 (currentCompanyFilter.length > 0 ? 1 : 0) +
 (pastCompanyFilter.length > 0 ? 1 : 0) +
 (currentTitleFilter.length > 0 ? 1 : 0) +
 (workedAtClientIds.length > 0 ? 1 : 0) +
 (recentlyChangedJobs ? 1 : 0) +
 (qAll.length > 0 ? 1 : 0) +
 (qAny.length > 0 ? 1 : 0) +
 (qNone.length > 0 ? 1 : 0);

 // Snapshot of filters used by <ActiveFilterChips> and saved-search plumbing.
 const filtersSnapshot: CandidateFilters = useMemo(
 () => ({
 q: search,
 status: statusFilter,
 employment: employmentFilter,
 availability: availabilityFilter,
 pipelineStage: pipelineStageFilter,
 sort: (sortBy as CandidateFilters["sort"]) ||"newest",
 page,
 remote: remoteFilter as CandidateFilters["remote"],
 skills: skillsFilter,
 skillCombine: "and",
 location: locationFilter,
 poolIds,
 addedByIds,
 currentCompany: currentCompanyFilter,
 pastCompany: pastCompanyFilter,
 currentTitle: currentTitleFilter,
 workedAtClientIds,
 view: "list",
 savedSearchId: null,
 qAll,
 qAny,
 qNone,
 }),
 [
 search,
 statusFilter,
 employmentFilter,
 availabilityFilter,
 pipelineStageFilter,
 sortBy,
 page,
 remoteFilter,
 skillsFilter,
 locationFilter,
 poolIds,
 addedByIds,
 currentCompanyFilter,
 pastCompanyFilter,
 currentTitleFilter,
 workedAtClientIds,
 qAll,
 qAny,
 qNone,
 ]
 );
 const applyFiltersPatch = (patch: Partial<CandidateFilters>) => {
 if (patch.q !== undefined) setSearch(patch.q);
 if (patch.status !== undefined) setStatusFilter(patch.status);
 if (patch.employment !== undefined) setEmploymentFilter(patch.employment);
 if (patch.availability !== undefined) setAvailabilityFilter(patch.availability);
 if (patch.pipelineStage !== undefined) setPipelineStageFilter(patch.pipelineStage);
 if (patch.sort !== undefined) setSortBy(patch.sort);
 if (patch.page !== undefined) setPage(patch.page);
 if (patch.remote !== undefined) setRemoteFilter(patch.remote);
 if (patch.skills !== undefined) setSkillsFilter(patch.skills);
 if (patch.location !== undefined) setLocationFilter(patch.location);
 if (patch.poolIds !== undefined) setPoolIds(patch.poolIds);
 if (patch.addedByIds !== undefined) setAddedByIds(patch.addedByIds);
 if (patch.currentCompany !== undefined) setCurrentCompanyFilter(patch.currentCompany);
 if (patch.pastCompany !== undefined) setPastCompanyFilter(patch.pastCompany);
 if (patch.currentTitle !== undefined) setCurrentTitleFilter(patch.currentTitle);
 if (patch.workedAtClientIds !== undefined)
 setWorkedAtClientIds(patch.workedAtClientIds);
 if (patch.qAll !== undefined) setQAll(patch.qAll);
 if (patch.qAny !== undefined) setQAny(patch.qAny);
 if (patch.qNone !== undefined) setQNone(patch.qNone);
 };

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Sourcing · Kandydaci
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground mt-1">
 Kandydaci
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 {isLoading ?"Ładowanie…" : `${total.toLocaleString("pl-PL")} w bazie`}
 {isFetching && !isLoading ?"· synchronizacja…" :""}
 </p>
 </div>

 <div className="flex items-center gap-2">
 <Button size="sm" variant="outline" onClick={() => setShowImport(true)}>
 <Upload className="h-4 w-4" /> Import CSV
 </Button>
 <Button
 size="sm"
 variant="outline"
 onClick={() => setShowAddFromCV(true)}
 >
 <Sparkles className="h-4 w-4" /> Dodaj z CV
 </Button>
 <Link
 href="/candidates/bulk-import"
 className={buttonVariants({ size: "sm", variant: "outline" })}
 >
 <FileArchive className="h-4 w-4" /> Bulk CV
 </Link>
 <Link
 href="/candidates/search"
 className={buttonVariants({ size: "sm", variant: "outline" })}
 data-testid="link-manual-search"
 >
 <Search className="h-4 w-4" /> Wyszukaj manualnie
 </Link>
 <Popover>
 <PopoverTrigger asChild>
 <Button size="sm" variant="outline">
 <Download className="h-4 w-4" /> Eksport
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" className="w-40 p-1">
 <button
 onClick={() => doExport("csv")}
 className="block w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 CSV
 </button>
 <button
 onClick={() => doExport("xlsx")}
 className="block w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-primary/10"
 >
 Excel (.xlsx)
 </button>
 </PopoverContent>
 </Popover>
 <Button size="sm" variant="outline" onClick={() => setShowInvite(true)}>
 <LinkIcon className="h-4 w-4" /> Wygeneruj link
 </Button>
 <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
 <Plus className="h-4 w-4" /> Dodaj
 </Button>
 </div>
 </div>

 {/* Toolbar */}
 <div className="flex items-center gap-2 flex-wrap">
 <div className="flex-1 min-w-[240px] max-w-lg">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po imieniu, emailu, stanowisku…"
 value={search}
 onChange={(e) => {
 setSearch(e.target.value);
 setPage(1);
 }}
 />
 </div>
 <Button
 size="sm"
 variant={showAdvanced ?"primary" :"outline"}
 onClick={() => setShowAdvanced((v) => !v)}
 title="Boolean search — ALL / ANY / NONE"
 aria-expanded={showAdvanced}
 aria-controls="boolean-search-panel"
 >
 <Filter className="h-4 w-4" />
 Zaawansowane
 {qAll.length + qAny.length + qNone.length > 0 && (
 <Badge variant="burgundy" size="sm" className="ml-1">
 {qAll.length + qAny.length + qNone.length}
 </Badge>
 )}
 </Button>
 <MultiSelectFilter<CandidateStatusValue>
 value={statusFilter}
 onChange={(v) => {
 setStatusFilter(v);
 setPage(1);
 }}
 options={CANDIDATE_STATUS_OPTIONS}
 placeholder="Wszystkie statusy"
 searchPlaceholder="Szukaj statusu…"
 triggerWidthClass="w-[180px]"
 triggerLabel={(n) =>
 n === 1
 ? (CANDIDATE_STATUS_OPTIONS.find((o) => o.value === statusFilter[0])
 ?.label ??"Status")
 : `Status: ${n}`
 }
 />
 <MultiSelectFilter<EmploymentValue>
 value={employmentFilter}
 onChange={(v) => {
 setEmploymentFilter(v);
 setPage(1);
 }}
 options={EMPLOYMENT_OPTIONS}
 placeholder="Zatrudnienie"
 searchPlaceholder="Szukaj…"
 triggerWidthClass="w-[200px]"
 title="Filtruj po stanie zatrudnienia"
 triggerLabel={(n) =>
 n === 1
 ? (EMPLOYMENT_OPTIONS.find((o) => o.value === employmentFilter[0])
 ?.label ??"Zatrudnienie")
 : `Zatrudnienie: ${n}`
 }
 />
 <MultiSelectFilter<AvailabilityValue>
 value={availabilityFilter}
 onChange={(v) => {
 setAvailabilityFilter(v);
 setPage(1);
 }}
 options={AVAILABILITY_OPTIONS}
 placeholder="Dyspozycyjność"
 searchPlaceholder="Szukaj…"
 triggerWidthClass="w-[190px]"
 title="Filtruj po dyspozycyjności"
 triggerLabel={(n) =>
 n === 1
 ? (AVAILABILITY_OPTIONS.find((o) => o.value === availabilityFilter[0])
 ?.label ??"Dyspozycyjność")
 : `Dyspozycyjność: ${n}`
 }
 />
 <MultiSelectFilter<PipelineStageValue>
 value={pipelineStageFilter}
 onChange={(v) => {
 setPipelineStageFilter(v);
 setPage(1);
 }}
 options={PIPELINE_STAGE_OPTIONS}
 placeholder="Etap"
 searchPlaceholder="Szukaj etapu…"
 triggerWidthClass="w-[170px]"
 title="Filtruj po etapie w pipeline'ie rekrutacyjnym (aktualny etap kandydata)"
 triggerLabel={(n) =>
 n === 1
 ? (PIPELINE_STAGE_OPTIONS.find((o) => o.value === pipelineStageFilter[0])
 ?.label ??"Etap")
 : `Etap: ${n}`
 }
 />
 <MultiSelectFilter<OpenToValue>
 value={openToFilter}
 onChange={(v) => {
 setOpenToFilter(v);
 setPage(1);
 }}
 options={OPEN_TO_OPTIONS}
 placeholder="Otwartość"
 searchPlaceholder="Szukaj…"
 triggerWidthClass="w-[190px]"
 title="Kandydaci otwarci na dodatkowe zaangażowanie"
 triggerLabel={(n) =>
 n === 1
 ? (OPEN_TO_OPTIONS.find((o) => o.value === openToFilter[0])
 ?.label ??"Otwartość")
 : `Otwartość: ${n}`
 }
 />
 <Button
 size="sm"
 variant="outline"
 onClick={() => {
 // Shortcut: show everyone who can realistically be sourced right now —
 // not at a client AND explicitly open to offers (or actively looking).
 setEmploymentFilter(["available"]);
 setAvailabilityFilter(["actively_looking"]);
 setPage(1);
 }}
 title="Bez projektu + aktywnie szukający"
 >
 <Sparkles className="h-4 w-4" /> Dostępni do sourcingu
 </Button>
 <Button
 size="sm"
 variant={openToFilter.length === OPEN_TO_OPTIONS.length ?"secondary" :"outline"}
 onClick={() => {
 // Zakładka „Otwarci na extra": toggle ALL three flags at once.
 if (openToFilter.length === OPEN_TO_OPTIONS.length) {
 setOpenToFilter([]);
 } else {
 setOpenToFilter(OPEN_TO_OPTIONS.map((o) => o.value) as OpenToValue[]);
 }
 setPage(1);
 }}
 title="Kandydaci zadeklarowani jako otwarci na dodatkowe projekty / wsparcie / konsultacje"
 >
 <Sparkles className="h-4 w-4" /> Otwarci na extra
 </Button>
 <Select value={sortBy} onValueChange={setSortBy}>
 <SelectTrigger className="w-[160px]">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 {SORT_OPTIONS.map((o) => (
 <SelectItem key={o.value} value={o.value}>
 {o.label}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 {/* Phase 2: 3 najczęściej używane filtry jako zawsze-widoczne chipsy
 (Traffit parity). Każdy chip otwiera mini-popover; gdy ma wartość,
 pokazuje ją inline + × do wyczyszczenia. Rzadsze filtry zostają w
 "Filtry zaawansowane" popup poniżej. */}
 <FilterChipPopover
 label="Lokalizacja"
 activeLabel={locationFilter || null}
 onClear={() => {
 setLocationFilter("");
 setPage(1);
 }}
 contentWidthClass="w-72"
 >
 <LocationInput
 value={locationFilter}
 onChange={(v) => {
 setLocationFilter(v);
 setPage(1);
 }}
 />
 </FilterChipPopover>
 <FilterChipPopover
 label="Obecna firma"
 activeLabel={
 currentCompanyFilter.length === 0
 ? null
 : currentCompanyFilter.length === 1
 ? currentCompanyFilter[0]
 : `${currentCompanyFilter.length} firm`
 }
 activeCount={currentCompanyFilter.length}
 onClear={() => {
 setCurrentCompanyFilter([]);
 setPage(1);
 }}
 >
 <CompanyAutocomplete
 value={currentCompanyFilter}
 onChange={(v) => {
 setCurrentCompanyFilter(v);
 setPage(1);
 }}
 placeholder="np. Google, Allegro"
 suggestEndpoint="/api/candidates/companies/suggest"
 />
 </FilterChipPopover>
 <FilterChipPopover
 label="Obecne stanowisko"
 activeLabel={
 currentTitleFilter.length === 0
 ? null
 : currentTitleFilter.length === 1
 ? currentTitleFilter[0]
 : `${currentTitleFilter.length} stanowisk`
 }
 activeCount={currentTitleFilter.length}
 onClear={() => {
 setCurrentTitleFilter([]);
 setPage(1);
 }}
 >
 <CompanyAutocomplete
 value={currentTitleFilter}
 onChange={(v) => {
 setCurrentTitleFilter(v);
 setPage(1);
 }}
 placeholder="np. Senior Engineer, PM"
 suggestEndpoint="/api/candidates/titles/suggest"
 />
 </FilterChipPopover>
 <FilterChipPopover
 label="Talent pool"
 activeLabel={
 poolIds.length === 0
 ? null
 : poolIds.length === 1
 ? "1 pula"
 : `${poolIds.length} pul`
 }
 activeCount={poolIds.length}
 onClear={() => {
 setPoolIds([]);
 setPage(1);
 }}
 contentWidthClass="w-80"
 >
 <TalentPoolMultiSelect
 value={poolIds}
 onChange={(ids) => {
 setPoolIds(ids);
 setPage(1);
 }}
 />
 </FilterChipPopover>
 <Popover>
 <PopoverTrigger asChild>
 <Button size="md" variant="outline">
 <Filter className="h-4 w-4" /> Filtry zaawansowane
 {activeFilterCount > 0 && (
 <Badge variant="burgundy" size="sm">
 {activeFilterCount}
 </Badge>
 )}
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" className="w-80 space-y-3 max-h-[80vh] overflow-y-auto">
 {/* Note (Phase 2): Obecna firma, Lokalizacja, Talent pool przeniesione
 jako zawsze-widoczne chipsy na main toolbar. Tu zostają rzadziej
 używane filtry. */}
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Poprzednia firma
 </h3>
 <CompanyAutocomplete
 value={pastCompanyFilter}
 onChange={(v) => {
 setPastCompanyFilter(v);
 setPage(1);
 }}
 placeholder="np. IBM, Accenture"
 suggestEndpoint="/api/candidates/companies/suggest"
 />
 </div>
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Niedawno zmienił pracę (LinkedIn)
 </h3>
 <div className="flex gap-1.5 flex-wrap">
 {(
 [
 { value: "", label: "Wszyscy" },
 { value: "1", label: "1 mies." },
 { value: "2", label: "2 mies." },
 { value: "3", label: "3 mies." },
 ] as const
 ).map((opt) => {
 const active = recentlyChangedJobs === opt.value;
 return (
 <button
 key={opt.value ||"all"}
 onClick={() => {
 setRecentlyChangedJobs(opt.value);
 setPage(1);
 }}
 className={cn("px-2.5 py-1 text-xs rounded-md border transition-colors",
 active
 ?"bg-primary text-white border-primary"
 :"bg-card text-foreground border-border hover:border-primary"
 )}
 >
 {opt.label}
 </button>
 );
 })}
 </div>
 </div>
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Pracował u klienta
 </h3>
 <ClientMultiSelect
 value={workedAtClientIds}
 onChange={(ids) => {
 setWorkedAtClientIds(ids);
 setPage(1);
 }}
 />
 </div>
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Dodany przez
 </h3>
 <AddedByMultiSelect
 value={addedByIds}
 onChange={(ids) => {
 setAddedByIds(ids);
 setPage(1);
 }}
 />
 </div>
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Tryb pracy
 </h3>
 <div className="flex gap-1.5 flex-wrap">
 {(["remote","hybrid","onsite"] as const).map((v) => {
 const active = remoteFilter.includes(v);
 return (
 <button
 key={v}
 onClick={() =>
 setRemoteFilter((p) =>
 p.includes(v) ? p.filter((x) => x !== v) : [...p, v]
 )
 }
 className={cn("px-2.5 py-1 text-xs rounded-md border transition-colors",
 active
 ?"bg-primary text-white border-primary"
 :"bg-card text-foreground border-border hover:border-primary"
 )}
 >
 {v === "remote" ?"Zdalnie" : v === "hybrid" ?"Hybryda" :"Stacjonarnie"}
 </button>
 );
 })}
 </div>
 </div>
 <div>
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Umiejętności (AND)
 </h3>
 <div className="flex gap-1.5 flex-wrap mb-2">
 {skillsFilter.map((s) => (
 <span
 key={s}
 className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary"
 >
 {s}
 <button onClick={() => removeSkill(s)} className="hover:opacity-70">
 <X className="h-3 w-3" />
 </button>
 </span>
 ))}
 </div>
 <Input
 placeholder="np. Python, React, AWS"
 value={skillInput}
 onChange={(e) => setSkillInput(e.target.value)}
 onKeyDown={(e) => {
 if (e.key === "Enter") {
 e.preventDefault();
 addSkill(skillInput);
 }
 }}
 />
 <p className="text-[10px] text-muted-foreground mt-1">
 Enter, aby dodać. {skillsFilter.length > 1 &&"Wszystkie muszą być obecne (AND)."}
 </p>
 </div>
 <div className="flex justify-between pt-1">
 <button
 onClick={() => {
 setRemoteFilter([]);
 setSkillsFilter([]);
 setLocationFilter("");
 setPoolIds([]);
 setAddedByIds([]);
 setCurrentCompanyFilter([]);
 setPastCompanyFilter([]);
 setCurrentTitleFilter([]);
 setWorkedAtClientIds([]);
 setQAll([]);
 setQAny([]);
 setQNone([]);
 setPage(1);
 }}
 className="text-xs text-muted-foreground hover:text-primary"
 >
 Wyczyść filtry
 </button>
 {activeFilterCount > 0 && (
 <Badge variant="soft" size="sm">
 {activeFilterCount} aktywny
 </Badge>
 )}
 </div>
 </PopoverContent>
 </Popover>
 {currentUser && (
 <Button
 size="sm"
 variant={
 addedByIds.length === 1 && addedByIds[0] === currentUser.id
 ?"primary"
 :"outline"
 }
 onClick={() => {
 const alreadyMine =
 addedByIds.length === 1 && addedByIds[0] === currentUser.id;
 setAddedByIds(alreadyMine ? [] : [currentUser.id]);
 setPage(1);
 }}
 title="Pokaż tylko kandydatów, których dodałem"
 >
 Moi kandydaci
 </Button>
 )}
 <SavedSearchesMenu
 currentQs={encodeFilters(filtersSnapshot).toString()}
 onApply={(qs) => {
 const decoded = decodeFilters(new URLSearchParams(qs));
 applyFiltersPatch({
 q: decoded.q,
 status: decoded.status,
 employment: decoded.employment,
 availability: decoded.availability,
 sort: decoded.sort,
 page: 1,
 remote: decoded.remote,
 skills: decoded.skills,
 location: decoded.location,
 poolIds: decoded.poolIds,
 addedByIds: decoded.addedByIds,
 currentCompany: decoded.currentCompany,
 pastCompany: decoded.pastCompany,
 currentTitle: decoded.currentTitle,
 workedAtClientIds: decoded.workedAtClientIds,
 qAll: decoded.qAll,
 qAny: decoded.qAny,
 qNone: decoded.qNone,
 });
 }}
 />

 <div className="ml-auto flex items-center gap-2">
 {/* Column customization popover */}
 <Popover>
 <PopoverTrigger asChild>
 <button
 title="Konfiguracja kolumn"
 className="h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:bg-primary/10 hover:text-foreground"
 >
 <Columns3 className="h-4 w-4" />
 </button>
 </PopoverTrigger>
 <PopoverContent align="end" className="w-64">
 <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-2">
 Pokazuj kolumny
 </h3>
 <div className="space-y-1.5">
 {ALL_COLUMNS.map((col) => {
 const shown = !hiddenColumns.has(col.id);
 return (
 <label
 key={col.id}
 className="flex items-center gap-2 text-sm cursor-pointer rounded-md px-1.5 py-1 hover:bg-primary/10"
 >
 <Checkbox
 checked={shown}
 disabled={col.required}
 onCheckedChange={(v) => {
 const next = new Set(hiddenColumns);
 if (v) next.delete(col.id);
 else next.add(col.id);
 setColumnPref("candidates-v2",
 Array.from(next) as ColumnId[]
 );
 }}
 />
 <span
 className={
 col.required
 ?"text-muted-foreground"
 :"text-foreground"
 }
 >
 {col.label}
 {col.required && (
 <span className="ml-1 text-[10px]">(wymagane)</span>
 )}
 </span>
 </label>
 );
 })}
 </div>
 <div className="mt-3 pt-2 border-t border-border flex flex-col gap-1.5">
 {userOverride && (
 <button
 type="button"
 onClick={resetToGlobalDefault}
 className="text-xs text-muted-foreground hover:text-primary text-left"
 >
 Przywróć domyślne
 </button>
 )}
 <RequireRole roles={["admin"]}>
 <div className="flex flex-col gap-1.5">
 <label
 htmlFor="candidates-columns-save-scope"
 className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground"
 >
 Zakres zapisu (admin)
 </label>
 <select
 id="candidates-columns-save-scope"
 value={saveTargetRole}
 onChange={(e) =>
 setSaveTargetRole(
 e.target.value as UserRole |"_global"
 )
 }
 className="text-xs rounded-md border border-border bg-card px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary"
 >
 {SAVE_ROLE_OPTIONS.map((opt) => (
 <option key={opt.value} value={opt.value}>
 {opt.label}
 </option>
 ))}
 </select>
 <button
 type="button"
 onClick={() => {
 const visibleIds = ALL_COLUMNS.filter(
 (c) => !hiddenColumns.has(c.id)
 ).map((c) => c.id as ColumnId);
 saveColumnDefault.mutate({
 columns: visibleIds,
 role: saveTargetRole,
 });
 }}
 disabled={saveColumnDefault.isPending}
 className="text-xs text-primary hover:underline text-left disabled:opacity-50"
 title="Zapisz bieżący układ jako domyślny dla wybranego zakresu"
 >
 {saveColumnDefault.isPending
 ?"Zapisywanie…"
 :"💾 Zapisz jako domyślne"}
 </button>
 </div>
 </RequireRole>
 </div>
 </PopoverContent>
 </Popover>
 <div
 className="flex items-center rounded-md border border-border overflow-hidden"
 role="group"
 aria-label="Widok listy"
 >
 <button
 onClick={() => setCandidatesView("list")}
 title="Widok tabeli"
 aria-pressed={candidatesView === "list"}
 className={cn("h-9 w-9 flex items-center justify-center transition-colors",
 candidatesView === "list"
 ?"bg-primary text-white"
 :"text-muted-foreground hover:bg-primary/10"
 )}
 >
 <Table2 className="h-4 w-4" />
 </button>
 <button
 onClick={() => setCandidatesView("tiles")}
 title="Widok kafelków"
 aria-pressed={candidatesView === "tiles"}
 className={cn("h-9 w-9 flex items-center justify-center transition-colors",
 candidatesView === "tiles"
 ?"bg-primary text-white"
 :"text-muted-foreground hover:bg-primary/10"
 )}
 >
 <LayoutGrid className="h-4 w-4" />
 </button>
 </div>
 <button
 onClick={() => setDensity(density === "cozy" ?"compact" :"cozy")}
 title="Przełącz gęstość"
 className="h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:bg-primary/10 hover:text-foreground"
 >
 <Rows3 className="h-4 w-4" />
 </button>
 </div>
 </div>

 {/* Pinned candidates bar — short-list workflow (Phase 4). Hidden when
 user has zero pins so it doesn't waste space for casual browsing. */}
 <PinnedCandidatesBar
 onOpenCandidate={(id) => {
 setDetailId(id);
 const idx = items.findIndex((c) => c.id === id);
 if (idx >= 0) {
 setDetailPosition((page - 1) * pageSize + idx + 1);
 } else {
 setDetailPosition(0);
 }
 }}
 />

 {/* Boolean-search panel — inline (Phase 3, Traffit parity). Toggled by
 the "Zaawansowane" button above; auto-opens when URL carries q_all/q_any/q_none
 so reloads don't hide active filters. */}
 {showAdvanced && (
 <div
 id="boolean-search-panel"
 className="rounded-lg border border-border bg-card p-4"
 >
 <AdvancedSearchPopover
 value={{ all: qAll, any: qAny, none: qNone }}
 onChange={(next) => {
 setQAll(next.all);
 setQAny(next.any);
 setQNone(next.none);
 setPage(1);
 }}
 />
 </div>
 )}

 {/* Active filter chips */}
 <ActiveFilterChips filters={filtersSnapshot} onUpdate={applyFiltersPatch} />

 {/* Data grid (virtualized) */}
 <div className="rounded-lg border border-border bg-card overflow-hidden">
 {/* Header row (list view only) */}
 {candidatesView === "list" && (
 <div
 className={cn("grid items-center gap-4 px-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground bg-background/60 border-b border-border",
 density === "compact" ?"h-9" :"h-10"
 )}
 style={{ gridTemplateColumns }}
 >
 <div className="flex items-center">
 <Checkbox
 checked={
 items.length > 0 && items.every((i) => selectedIds.has(i.id))
 ? true
 : selectedIds.size > 0
 ?"indeterminate"
 : false
 }
 onCheckedChange={(v) => (v ? selectAllVisible() : clearSelection())}
 aria-label="Zaznacz wszystkie"
 />
 </div>
 {visibleColumns.map((col) => (
 <div key={col.id} className="truncate">{col.label}</div>
 ))}
 <div />
 </div>
 )}

 {/* Virtualized body — list or tiles */}
 {candidatesView === "tiles" ? (
 items.length === 0 && !isLoading ? (
 <div className="py-16 text-center text-sm text-muted-foreground">
 <Users className="h-10 w-10 mx-auto mb-2 opacity-40" />
 Brak wyników. Zmień filtry lub{""}
 <button
 className="text-primary hover:underline"
 onClick={() => setShowAdd(true)}
 >
 dodaj nowego kandydata
 </button>
 .
 </div>
 ) : (
 <CandidatesTiles
 items={items}
 selectedIds={selectedIds}
 onToggleSelect={toggleId}
 onOpenDetail={(id) => {
 setDetailId(id);
 const idx = items.findIndex((c) => c.id === id);
 if (idx >= 0) {
 setDetailPosition((page - 1) * pageSize + idx + 1);
 }
 }}
 onQuickAssign={(c) => setAssignFor(c)}
 />
 )
 ) : (
 <div
 ref={parentRef}
 style={{ height: "calc(100vh - 340px)", minHeight: 360 }}
 className="overflow-auto"
 >
 {isLoading ? (
 <div className="py-16 text-center text-sm text-muted-foreground">
 Ładowanie kandydatów…
 </div>
 ) : items.length === 0 ? (
 <div className="py-16 text-center text-sm text-muted-foreground">
 <Users className="h-10 w-10 mx-auto mb-2 opacity-40" />
 Brak wyników. Zmień filtry lub{""}
 <button
 className="text-primary hover:underline"
 onClick={() => setShowAdd(true)}
 >
 dodaj nowego kandydata
 </button>
 .
 </div>
 ) : (
 <div
 style={{
 height: `${virtualizer.getTotalSize()}px`,
 width: "100%",
 position: "relative",
 }}
 >
 {virtualizer.getVirtualItems().map((virtualRow) => {
 const candidate = items[virtualRow.index];
 const fullName =
 `${candidate.name ??""} ${candidate.lastname ??""}`.trim() ||"Kandydat";
 const initials = fullName
 .split("")
 .map((w) => w[0])
 .slice(0, 2)
 .join("")
 .toUpperCase();
 const isSelected = selectedIds.has(candidate.id);
 const stats = candidate.match_stats;
 const openDetail = () => {
 setDetailId(candidate.id);
 const idx = items.findIndex((c) => c.id === candidate.id);
 if (idx >= 0) {
 setDetailPosition((page - 1) * pageSize + idx + 1);
 }
 };
 return (
 <div
 key={candidate.id}
 data-index={virtualRow.index}
 style={{
 position: "absolute",
 top: 0,
 left: 0,
 width: "100%",
 height: `${virtualRow.size}px`,
 transform: `translateY(${virtualRow.start}px)`,
 gridTemplateColumns,
 }}
 className={cn("grid items-center gap-4 px-4 border-b border-border/50 transition-colors","hover:bg-primary/10",
 isSelected &&"bg-primary/10 hover:bg-primary/10"
 )}
 >
 <div
 className="flex items-center"
 onClick={(e) => {
 e.stopPropagation();
 toggleId(candidate.id);
 }}
 >
 <Checkbox checked={isSelected} onCheckedChange={() => toggleId(candidate.id)} />
 </div>
 {visibleColumns.map((col) => (
 <CandidateCell
 key={col.id}
 columnId={col.id}
 candidate={candidate}
 fullName={fullName}
 initials={initials}
 density={density}
 stats={stats}
 searchTerms={searchTerms}
 onOpenDetail={openDetail}
 />
 ))}
 <div className="flex justify-end">
 <button
 onClick={(e) => {
 e.stopPropagation();
 setAssignFor({ id: candidate.id, name: fullName });
 }}
 title="Przypisz do oferty"
 className="h-8 w-8 flex items-center justify-center rounded-md text-muted-foreground hover:bg-primary/10 hover:text-primary"
 >
 <Briefcase className="h-3.5 w-3.5" />
 </button>
 </div>
 </div>
 );
 })}
 </div>
 )}
 </div>
 )}

 {/* Pagination */}
 {!isLoading && items.length > 0 && (
 <div className="flex items-center justify-between gap-3 px-4 h-12 border-t border-border bg-background/40 text-sm">
 <span className="text-muted-foreground">
 Strona <span className="font-semibold text-foreground">{page}</span> z {totalPages}
 {selectedIds.size > 0 && (
 <>
 {" ·"}
 <span className="font-semibold text-primary">
 {selectedIds.size} zaznaczonych
 </span>
 </>
 )}
 </span>
 <div className="flex items-center gap-2">
 <Button
 size="sm"
 variant="outline"
 disabled={page <= 1}
 onClick={() => setPage((p) => Math.max(1, p - 1))}
 >
 Poprzednia
 </Button>
 <Button
 size="sm"
 variant="outline"
 disabled={page >= totalPages}
 onClick={() => setPage((p) => p + 1)}
 >
 Następna <ChevronRight className="h-3.5 w-3.5" />
 </Button>
 </div>
 </div>
 )}
 </div>

 {/* Floating BulkActionsBar */}
 {selectedIds.size > 0 && (
 <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-40 bg-card text-foreground rounded-xl shadow-md border border-white/10 px-4 py-2.5 flex items-center gap-3 animate-slide-in-bottom">
 <span className="text-xs">
 Zaznaczono: <span className="font-bold">{selectedIds.size}</span>
 </span>
 <div className="h-4 w-px bg-card/15" />
 <Button
 size="sm"
 variant="primary"
 onClick={() => {
 const ids = Array.from(selectedIds).slice(0, 3).join(",");
 router.push(`/candidates/compare?ids=${ids}`);
 }}
 >
 <GitCompare className="h-3.5 w-3.5" /> Porównaj (max 3)
 </Button>
 <Button size="sm" variant="ghost" onClick={() => doExport("csv")}>
 <Download className="h-3.5 w-3.5" /> Eksportuj
 </Button>
 <Button
 size="sm"
 variant="ghost"
 onClick={doBulkDownloadCvs}
 disabled={isDownloadingZip}
 >
 {isDownloadingZip ? (
 <Loader2 className="h-3.5 w-3.5 animate-spin" />
 ) : (
 <FileArchive className="h-3.5 w-3.5" />
 )}{""}
 Pobierz CV (ZIP)
 </Button>
 <Button
 size="sm"
 variant="ghost"
 onClick={() => setShowBulkPool(true)}
 disabled={bulkPoolPending}
 title="Dodaj zaznaczonych do puli talentów"
 >
 <Users className="h-3.5 w-3.5" /> Dodaj do puli
 </Button>
 <button
 onClick={clearSelection}
 className="text-xs text-foreground/70 hover:text-foreground ml-1"
 >
 Wyczyść
 </button>
 </div>
 )}

 {/* Bulk add-to-pool modal */}
 {showBulkPool && (
 <BulkAddToPoolModal
 selectedCount={selectedIds.size}
 onCancel={() => setShowBulkPool(false)}
 onConfirm={doBulkAddToPool}
 pending={bulkPoolPending}
 />
 )}

 {/* Keyboard hints */}
 <div className="hidden md:flex items-center gap-3 text-[10px] text-muted-foreground justify-center">
 <span>
 <Kbd>⌘</Kbd> <Kbd>K</Kbd> — szybkie wyszukiwanie
 </span>
 <span>
 <Kbd>N</Kbd> — nowy kandydat
 </span>
 <span>
 <Kbd>Enter</Kbd> — dodaj umiejętność w filtrze
 </span>
 </div>

 {/* Modals */}
 {showAdd && (
 <AddCandidateModal onClose={() => setShowAdd(false)} onSuccess={toastOnSuccess} />
 )}
 <ImportCandidatesV2
 open={showImport}
 onOpenChange={setShowImport}
 onImported={() => toastOnSuccess("Import zakończony.")}
 />
 <AddCandidateFromCVModal
 open={showAddFromCV}
 onOpenChange={setShowAddFromCV}
 onAdded={() => toastOnSuccess("Kandydat dodany z CV.")}
 />
 <GenerateInviteLinkV2 open={showInvite} onOpenChange={setShowInvite} />
 <QuickAssignV2
 open={!!assignFor}
 onOpenChange={(v) => !v && setAssignFor(null)}
 candidateId={assignFor?.id ?? 0}
 candidateName={assignFor?.name ??""}
 onAssigned={() => toastOnSuccess("Kandydat przypisany.")}
 />

 {/* Side sheet: candidate detail (embedded) */}
 <Sheet
 open={detailId !== null}
 onOpenChange={(v) => !v && setDetailId(null)}
 >
 <SheetContent side="right" size="2xl" className="!p-0">
 {detailId !== null && (
 <div className="h-full overflow-y-auto p-6">
 <CandidateDetailV2
 embedded
 candidateId={detailId}
 onClose={() => setDetailId(null)}
 navigation={{
 filters: filtersSnapshot,
 position: detailPosition,
 pageItems: items.map((c) => ({
 id: c.id,
 name: c.name,
 lastname: c.lastname,
 })),
 total,
 pageNumber: page,
 pageSize,
 onNavigate: ({ candidateId, position }) => {
 setDetailId(candidateId);
 setDetailPosition(position);
 // Keep the underlying list in sync so closing the sheet
 // lands on the page where navigation ended.
 const nextListPage =
 Math.floor((position - 1) / pageSize) + 1;
 if (nextListPage !== page) setPage(nextListPage);
 },
 }}
 />
 </div>
 )}
 </SheetContent>
 </Sheet>

 {showToast && (
 <div className="fixed bottom-4 right-4 z-[9999] px-4 py-3 rounded-lg shadow-md text-sm bg-card text-foreground">
 {showToast}
 </div>
 )}
 </div>
 );
}

// ── Bulk add-to-pool modal (Phase „Otwartość" Faza 2.5) ─────────────────────

function BulkAddToPoolModal({
 selectedCount,
 onCancel,
 onConfirm,
 pending,
}: {
 selectedCount: number;
 onCancel: () => void;
 onConfirm: (poolId: number) => void;
 pending: boolean;
}) {
 const [filter, setFilter] = useState("");
 const { data, isLoading } = useQuery({
 queryKey: ["talent-pools","bulk-modal"],
 queryFn: () => api.get("/api/talent-pools").then((r) => r.data),
 });
 const pools: Array<{ id: number; name: string; candidate_count: number }> =
 Array.isArray(data) ? data : data?.items ?? [];
 const filtered = pools.filter((p) =>
 p.name.toLowerCase().includes(filter.toLowerCase())
 );

 return (
 <div
 className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
 onClick={onCancel}
 >
 <div
 className="bg-card dark:bg-card rounded-lg shadow-xl w-full max-w-md p-5 space-y-3"
 onClick={(e) => e.stopPropagation()}
 >
 <h3 className="text-base font-semibold">
 Dodaj {selectedCount} {selectedCount === 1 ?"kandydata" :"kandydatów"} do puli
 </h3>
 <Input
 placeholder="Szukaj puli…"
 value={filter}
 onChange={(e) => setFilter(e.target.value)}
 autoFocus
 />
 <div className="max-h-[50vh] overflow-y-auto space-y-1">
 {isLoading && (
 <div className="text-xs text-muted-foreground py-4 text-center">Ładowanie pul…</div>
 )}
 {!isLoading && filtered.length === 0 && (
 <div className="text-xs text-muted-foreground py-4 text-center">
 Brak pul dla „{filter}". <Link href="/talents" className="underline">Stwórz nową</Link>.
 </div>
 )}
 {filtered.map((p) => (
 <button
 key={p.id}
 type="button"
 onClick={() => onConfirm(p.id)}
 disabled={pending}
 className="w-full text-left text-sm px-3 py-2 rounded hover:bg-muted dark:hover:bg-muted disabled:opacity-50 flex items-center justify-between"
 >
 <span>{p.name}</span>
 <span className="text-xs text-muted-foreground">
 {p.candidate_count} {p.candidate_count === 1 ?"kandydat" :"kandydatów"}
 </span>
 </button>
 ))}
 </div>
 <div className="flex justify-end gap-2 pt-2 border-t border-border dark:border-border">
 <Button size="sm" variant="ghost" onClick={onCancel} disabled={pending}>
 Anuluj
 </Button>
 </div>
 </div>
 </div>
 );
}
