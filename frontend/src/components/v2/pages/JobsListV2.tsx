"use client";

import { useState, type ReactNode } from"react";
import Link from"next/link";
import { useQuery, useQueryClient } from"@tanstack/react-query";
import {
 Briefcase,
 Building2,
 DollarSign,
 Link2,
 MapPin,
 Plus,
 Search,
 Sparkles,
 UserSquare2,
 Users,
} from"lucide-react";
import api from"@/lib/api";
import { cn, formatRelativeTime } from"@/lib/utils";
import { AddJobModal } from"@/components/AppShell";
import { GenerateInviteLinkV2 } from"@/components/v2/modals/GenerateInviteLinkV2";
import { RequireRole } from"@/components/RequireRole";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card } from"@/components/ui/card";
import { Input } from"@/components/ui/input";
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from"@/components/ui/select";
import { OwnerBadge } from"@/components/v2/jobs/OwnerBadge";
import { MultiSelectFilter } from"@/components/v2/filters/MultiSelectFilter";
import { UserMultiSelect } from"@/components/v2/filters/UserMultiSelect";
import { ClientMultiSelect } from"@/components/v2/filters/ClientMultiSelect";
import { CompetenceCategoryMultiSelect } from"@/components/v2/filters/CompetenceCategoryMultiSelect";
import {
 JOB_STATUS_OPTIONS,
 type JobStatusValue,
} from"@/lib/filter-options";

type JobType ="all" |"body_leasing" |"sales" |"tenders";

const FILTER_TABS: { value: JobType; label: string }[] = [
 { value: "all", label: "Wszystkie" },
 { value: "body_leasing", label: "Body leasing" },
 { value: "sales", label: "Sales" },
 { value: "tenders", label: "Przetargi" },
];

const STATUS_VARIANT: Record<
 string, "success" |"soft" |"neutral" |"warning" |"danger"
> = {
 open: "success",
 published: "success",
 closed: "neutral",
 draft: "soft",
 on_hold: "warning",
 lost: "danger",
};

const STATUS_LABEL: Record<string, string> = {
 open: "Otwarta",
 published: "Opublikowana",
 closed: "Zamknięta",
 draft: "Draft",
 on_hold: "Wstrzymana",
 lost: "Utracona",
};

function extractSkills(must: unknown): string[] {
 if (!must) return [];
 if (Array.isArray(must)) {
 return must
 .map((x) => (typeof x === "string" ? x : (x as any)?.name ?? null))
 .filter(Boolean) as string[];
 }
 if (typeof must === "object" && (must as any).technologies) {
 return Array.isArray((must as any).technologies) ? (must as any).technologies : [];
 }
 return [];
}

type DeadlinePreset ="any" |"overdue" |"next7" |"next30" |"has" |"none";

const DEADLINE_OPTIONS: { value: DeadlinePreset; label: string }[] = [
 { value: "any", label: "Termin: dowolny" },
 { value: "overdue", label: "Po terminie" },
 { value: "next7", label: "Najbliższe 7 dni" },
 { value: "next30", label: "Najbliższe 30 dni" },
 { value: "has", label: "Z terminem" },
 { value: "none", label: "Bez terminu" },
];

type JobSortValue = "newest" | "oldest" | "deadline";

const SORT_OPTIONS: { value: JobSortValue; label: string }[] = [
 { value: "newest", label: "Od najnowszej" },
 { value: "oldest", label: "Od najstarszej" },
 { value: "deadline", label: "Wg terminu" },
];

/** Local-date ISO string (YYYY-MM-DD) — avoids UTC off-by-one near midnight. */
function isoLocal(d: Date): string {
 const y = d.getFullYear();
 const m = String(d.getMonth() + 1).padStart(2,"0");
 const day = String(d.getDate()).padStart(2,"0");
 return `${y}-${m}-${day}`;
}

/** Map a deadline preset to backend query params. */
function deadlineParams(preset: DeadlinePreset): {
 deadline_from?: string;
 deadline_to?: string;
 has_deadline?: boolean;
} {
 if (preset === "any") return {};
 if (preset === "has") return { has_deadline: true };
 if (preset === "none") return { has_deadline: false };
 const today = new Date();
 const addDays = (n: number) => {
 const d = new Date(today);
 d.setDate(d.getDate() + n);
 return d;
 };
 if (preset === "overdue") {
 // Strictly before today → upper bound is yesterday (inclusive).
 return { deadline_to: isoLocal(addDays(-1)) };
 }
 if (preset === "next7") {
 return { deadline_from: isoLocal(today), deadline_to: isoLocal(addDays(7)) };
 }
 // next30
 return { deadline_from: isoLocal(today), deadline_to: isoLocal(addDays(30)) };
}

function FilterToggle({
 active,
 onClick,
 title,
 children,
}: {
 active: boolean;
 onClick: () => void;
 title?: string;
 children: ReactNode;
}) {
 return (
 <button
 type="button"
 onClick={onClick}
 aria-pressed={active}
 title={title}
 className={cn("px-3 h-9 rounded-lg text-sm font-medium transition-all border whitespace-nowrap",
 active
 ?"bg-primary text-white border-primary shadow-sm"
 :"bg-card text-foreground border-border hover:text-foreground"
 )}
 >
 {children}
 </button>
 );
}

export function JobsListV2() {
 const [search, setSearch] = useState("");
 const [statusFilter, setStatusFilter] = useState<JobStatusValue[]>([]);
 const [typeFilter, setTypeFilter] = useState<JobType>("all");
 const [mine, setMine] = useState(false);
 const [responsibleIds, setResponsibleIds] = useState<number[]>([]);
 const [clientIds, setClientIds] = useState<number[]>([]);
 const [ccIds, setCcIds] = useState<number[]>([]);
 const [needsSourcing, setNeedsSourcing] = useState(false);
 const [activeInSearch, setActiveInSearch] = useState(false);
 const [deadlinePreset, setDeadlinePreset] = useState<DeadlinePreset>("any");
 const [openOnly, setOpenOnly] = useState(false);
 const [sort, setSort] = useState<JobSortValue>("newest");
 const [page, setPage] = useState(1);
 const [showAdd, setShowAdd] = useState(false);
 const [inviteModalForJob, setInviteModalForJob] = useState<number | null>(null);
 const queryClient = useQueryClient();

 const dl = deadlineParams(deadlinePreset);

 const { data, isLoading } = useQuery({
 queryKey: ["jobs-v2",
 search,
 statusFilter,
 typeFilter,
 mine ? 1 : 0,
 responsibleIds,
 clientIds,
 ccIds,
 needsSourcing ? 1 : 0,
 activeInSearch ? 1 : 0,
 deadlinePreset,
 openOnly ? 1 : 0,
 sort,
 page,
 ],
 queryFn: () =>
 api
 .get("/api/jobs", {
 params: {
 q: search || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 recruitment_type: typeFilter !== "all" ? typeFilter : undefined,
 mine: mine ? true : undefined,
 responsible_id: responsibleIds.length ? responsibleIds : undefined,
 client_id: clientIds.length ? clientIds : undefined,
 competence_category_id: ccIds.length ? ccIds : undefined,
 needs_sourcing: needsSourcing ? true : undefined,
 active_in_search: activeInSearch ? true : undefined,
 open_only: openOnly ? true : undefined,
 sort,
 ...dl,
 page,
 },
 paramsSerializer: { indexes: null },
 })
 .then((r) => r.data),
 });

 const items = data?.items ?? [];
 const total = data?.total ?? 0;

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">
 Pipeline · Oferty
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-[-0.02em] text-foreground mt-1">
 Oferty pracy
 </h1>
 <p className="text-sm text-muted-foreground mt-1">
 {isLoading ?"Ładowanie…" : `${total} ofert`}
 </p>
 </div>
 <RequireRole roles={["admin","delivery_lead","tac"]}>
 <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
 <Plus className="h-4 w-4" /> Nowa oferta
 </Button>
 </RequireRole>
 </div>

 {/* Type tabs */}
 <div className="flex gap-1 bg-card rounded-lg p-1 w-fit border border-border">
 {FILTER_TABS.map((tab) => (
 <button
 key={tab.value}
 onClick={() => {
 setTypeFilter(tab.value);
 setPage(1);
 }}
 className={cn("px-4 py-1.5 rounded-md text-sm font-medium transition-all",
 typeFilter === tab.value
 ?"bg-primary text-white shadow-sm"
 :"text-muted-foreground hover:text-foreground"
 )}
 >
 {tab.label}
 </button>
 ))}
 </div>

 {/* Search + status + ownership filters */}
 <div className="flex gap-2 flex-wrap">
 <div className="flex-1 min-w-[260px] max-w-lg">
 <Input
 leadingIcon={<Search className="h-4 w-4" />}
 placeholder="Szukaj po tytule, kliencie, technologii…"
 value={search}
 onChange={(e) => {
 setSearch(e.target.value);
 setPage(1);
 }}
 />
 </div>
 <MultiSelectFilter<JobStatusValue>
 value={statusFilter}
 onChange={(v) => {
 setStatusFilter(v);
 setPage(1);
 }}
 options={JOB_STATUS_OPTIONS}
 placeholder="Wszystkie statusy"
 searchPlaceholder="Szukaj statusu…"
 triggerWidthClass="w-[180px]"
 triggerLabel={(n) =>
 n === 1
 ? (JOB_STATUS_OPTIONS.find((o) => o.value === statusFilter[0])
 ?.label ??"Status")
 : `Status: ${n}`
 }
 />
 <div className="w-[190px]">
 <ClientMultiSelect
 value={clientIds}
 onChange={(ids) => {
 setClientIds(ids);
 setPage(1);
 }}
 />
 </div>
 <CompetenceCategoryMultiSelect
 value={ccIds}
 onChange={(ids) => {
 setCcIds(ids);
 setPage(1);
 }}
 />
 <UserMultiSelect
 value={responsibleIds}
 onChange={(ids) => {
 setResponsibleIds(ids);
 setPage(1);
 }}
 placeholder="Osoba odpowiedzialna"
 searchPlaceholder="Szukaj osoby…"
 triggerWidthClass="w-[210px]"
 />
 <Select
 value={deadlinePreset}
 onValueChange={(v) => {
 setDeadlinePreset(v as DeadlinePreset);
 setPage(1);
 }}
 >
 <SelectTrigger className="h-9 w-[180px] font-medium">
 <SelectValue placeholder="Termin: dowolny" />
 </SelectTrigger>
 <SelectContent>
 {DEADLINE_OPTIONS.map((o) => (
 <SelectItem key={o.value} value={o.value}>
 {o.label}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 <Select
 value={sort}
 onValueChange={(v) => {
 setSort(v as JobSortValue);
 setPage(1);
 }}
 >
 <SelectTrigger className="h-9 w-[170px] font-medium">
 <SelectValue placeholder="Od najnowszej" />
 </SelectTrigger>
 <SelectContent>
 {SORT_OPTIONS.map((o) => (
 <SelectItem key={o.value} value={o.value}>
 {o.label}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
 <FilterToggle
 active={openOnly}
 onClick={() => {
 setOpenOnly((p) => !p);
 setPage(1);
 }}
 title="Tylko otwarte oferty (nie zamknięte)"
 >
 Otwarte
 </FilterToggle>
 <FilterToggle
 active={needsSourcing}
 onClick={() => {
 setNeedsSourcing((p) => !p);
 setPage(1);
 }}
 title="Tylko oferty oznaczone jako wymagające sourcingu"
 >
 Potrzebny search
 </FilterToggle>
 <FilterToggle
 active={activeInSearch}
 onClick={() => {
 setActiveInSearch((p) => !p);
 setPage(1);
 }}
 title="Tylko oferty z aktywnym rekruterem w sourcingu"
 >
 Aktywni w searchu
 </FilterToggle>
 <FilterToggle
 active={mine}
 onClick={() => {
 setMine((p) => !p);
 setPage(1);
 }}
 >
 Moje projekty
 </FilterToggle>
 </div>

 {/* Grid of job cards */}
 {isLoading ? (
 <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
 {Array.from({ length: 6 }).map((_, i) => (
 <Card key={i} className="animate-pulse h-48">
 <div className="h-4 bg-[hsl(var(--border))] rounded w-3/4 mb-3" />
 <div className="h-3 bg-[hsl(var(--border))] rounded w-1/2" />
 </Card>
 ))}
 </div>
 ) : items.length === 0 ? (
 <div className="py-12 text-center">
 <Briefcase className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 Brak ofert.{""}
 <button
 onClick={() => setShowAdd(true)}
 className="text-primary hover:underline"
 >
 Utwórz pierwszą
 </button>
 .
 </p>
 </div>
 ) : (
 <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
 {items.map((job: any) => {
 const skills = extractSkills(job.must_skills);
 const statusVariant = STATUS_VARIANT[job.status] ??"neutral";
 const statusLabel = STATUS_LABEL[job.status] ?? job.status;
 const filledCount = job.candidates_count ?? job.filled_count ?? 0;
 const targetCount = job.target_positions ?? job.headcount ?? 1;
 const progress = Math.min(
 100,
 Math.round((filledCount / Math.max(1, targetCount)) * 100)
 );
 return (
 <Link key={job.id} href={`/jobs/${job.id}`}>
 <Card variant="interactive" className="h-full flex flex-col">
 <div className="flex items-start justify-between gap-2 mb-2">
 <div className="flex-1 min-w-0">
 <h3 className="font-semibold text-foreground text-base truncate">
 {job.title}
 </h3>
 <div className="flex items-center gap-2 flex-wrap">
 {job.client_name && (
 <p className="text-xs text-muted-foreground flex items-center gap-1">
 <Building2 className="h-3 w-3" />
 {job.client_name}
 </p>
 )}
 {job.reference_number && (
 <span
 className="font-mono text-[10px] text-muted-foreground/80"
 title="Numer referencyjny"
 >
 {job.reference_number}
 </span>
 )}
 </div>
 </div>
 <div className="flex items-center gap-1 shrink-0">
 {job.status === "published" && (
 <button
 type="button"
 onClick={(e) => {
 e.preventDefault();
 e.stopPropagation();
 setInviteModalForJob(job.id);
 }}
 className="p-1 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
 title="Wygeneruj link aplikacyjny"
 aria-label="Wygeneruj link aplikacyjny"
 >
 <Link2 className="h-3.5 w-3.5" />
 </button>
 )}
 <Badge size="sm" variant={statusVariant}>
 {statusLabel}
 </Badge>
 {job.tac_id == null && (
 <span title="Klient nie ma przypisanego primary TAC">
 <Badge size="sm" variant="warning">
 Brak TAC
 </Badge>
 </span>
 )}
 </div>
 </div>

 <div className="mb-2 flex items-center gap-3 flex-wrap">
 <OwnerBadge user={job.primary_owner ?? null} size="sm" />
 {job.hiring_manager_name && (
 <span
 className="inline-flex items-center gap-1 text-xs text-primary bg-primary/10 px-2 py-0.5 rounded"
 title="Hiring manager po stronie klienta"
 >
 <UserSquare2 className="h-3 w-3" />
 {job.hiring_manager_name}
 </span>
 )}
 </div>

 {(job.location || job.seniority) && (
 <div className="flex items-center gap-3 text-xs text-foreground mb-2">
 {job.location && (
 <span className="inline-flex items-center gap-1">
 <MapPin className="h-3 w-3" />
 {job.location}
 </span>
 )}
 {job.seniority && <Badge size="sm" variant="plum">{job.seniority}</Badge>}
 </div>
 )}

 {skills.length > 0 && (
 <div className="flex flex-wrap gap-1 mb-3">
 {skills.slice(0, 5).map((s) => (
 <span
 key={s}
 className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary"
 >
 {s}
 </span>
 ))}
 {skills.length > 5 && (
 <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[hsl(var(--border))] text-muted-foreground">
 +{skills.length - 5}
 </span>
 )}
 </div>
 )}

 <div className="mt-auto space-y-2">
 {targetCount > 0 && (
 <div className="flex items-center gap-2">
 <Users className="h-3 w-3 text-muted-foreground" />
 <div className="flex-1 h-1.5 rounded-full bg-[hsl(var(--border))]/60 overflow-hidden">
 <div
 className="h-full bg-primary rounded-full transition-all"
 style={{ width: `${progress}%` }}
 />
 </div>
 <span className="text-[10px] font-mono text-muted-foreground">
 {filledCount}/{targetCount}
 </span>
 </div>
 )}
 {job.salary_range && (
 <div className="flex items-center gap-1.5 text-xs text-foreground">
 <DollarSign className="h-3 w-3 text-primary" />
 {job.salary_range}
 </div>
 )}
 <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-border">
 <span>
 {job.created_at ? formatRelativeTime(job.created_at) : "—"}
 </span>
 <Sparkles className="h-3 w-3 text-primary" />
 </div>
 </div>
 </Card>
 </Link>
 );
 })}
 </div>
 )}

 {showAdd && (
 <AddJobModal
 onClose={() => setShowAdd(false)}
 onSuccess={() => {
 queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
 setShowAdd(false);
 }}
 />
 )}

 <GenerateInviteLinkV2
 open={inviteModalForJob !== null}
 onOpenChange={(v) => {
 if (!v) setInviteModalForJob(null);
 }}
 defaultJobId={inviteModalForJob ?? undefined}
 />
 </div>
 );
}
