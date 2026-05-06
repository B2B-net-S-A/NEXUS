"use client";

import { useState } from"react";
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
import {
 JOB_STATUS_OPTIONS,
 type JobStatusValue,
} from"@/lib/filter-options";

type JobType ="all" |"body_leasing" |"sales" |"tenders";

const FILTER_TABS: { value: JobType; label: string }[] = [
 { value:"all", label:"Wszystkie" },
 { value:"body_leasing", label:"Body leasing" },
 { value:"sales", label:"Sales" },
 { value:"tenders", label:"Przetargi" },
];

const STATUS_VARIANT: Record<
 string,"success" |"soft" |"neutral" |"warning" |"danger"
> = {
 open:"success",
 published:"success",
 closed:"neutral",
 draft:"soft",
 on_hold:"warning",
 lost:"danger",
};

const STATUS_LABEL: Record<string, string> = {
 open:"Otwarta",
 published:"Opublikowana",
 closed:"Zamknięta",
 draft:"Draft",
 on_hold:"Wstrzymana",
 lost:"Utracona",
};

function extractSkills(must: unknown): string[] {
 if (!must) return [];
 if (Array.isArray(must)) {
 return must
 .map((x) => (typeof x ==="string" ? x : (x as any)?.name ?? null))
 .filter(Boolean) as string[];
 }
 if (typeof must ==="object" && (must as any).technologies) {
 return Array.isArray((must as any).technologies) ? (must as any).technologies : [];
 }
 return [];
}

export function JobsListV2() {
 const [search, setSearch] = useState("");
 const [statusFilter, setStatusFilter] = useState<JobStatusValue[]>([]);
 const [typeFilter, setTypeFilter] = useState<JobType>("all");
 const [mine, setMine] = useState(false);
 const [ownerIds, setOwnerIds] = useState<number[]>([]);
 const [page, setPage] = useState(1);
 const [showAdd, setShowAdd] = useState(false);
 const [inviteModalForJob, setInviteModalForJob] = useState<number | null>(null);
 const queryClient = useQueryClient();

 const { data, isLoading } = useQuery({
 queryKey: ["jobs-v2",
 search,
 statusFilter,
 typeFilter,
 mine ? 1 : 0,
 ownerIds,
 page,
 ],
 queryFn: () =>
 api
 .get("/api/jobs", {
 params: {
 q: search || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 recruitment_type: typeFilter !=="all" ? typeFilter : undefined,
 mine: mine ? true : undefined,
 owner_id: ownerIds.length ? ownerIds : undefined,
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
 <UserMultiSelect
 value={ownerIds}
 onChange={(ids) => {
 setOwnerIds(ids);
 setPage(1);
 }}
 placeholder="Rekruter: dowolny"
 searchPlaceholder="Szukaj rekrutera…"
 triggerWidthClass="w-[220px]"
 />
 <button
 type="button"
 onClick={() => {
 setMine((prev) => !prev);
 setPage(1);
 }}
 aria-pressed={mine}
 className={cn("px-3 h-9 rounded-lg text-sm font-medium transition-all border",
 mine
 ?"bg-primary text-white border-primary shadow-sm"
 :"bg-card text-foreground border-border hover:text-foreground"
 )}
 >
 Moje projekty
 </button>
 </div>

 {/* Grid of job cards */}
 {isLoading ? (
 <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
 {Array.from({ length: 6 }).map((_, i) => (
 <Card key={i} className="animate-pulse h-48">
 <div className="h-4 bg-[hsl(var(--border-subtle))] rounded w-3/4 mb-3" />
 <div className="h-3 bg-[hsl(var(--border-subtle))] rounded w-1/2" />
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
 {job.client_name && (
 <p className="text-xs text-muted-foreground flex items-center gap-1">
 <Building2 className="h-3 w-3" />
 {job.client_name}
 </p>
 )}
 </div>
 <div className="flex items-center gap-1 shrink-0">
 {job.status ==="published" && (
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

 <div className="mb-2">
 <OwnerBadge user={job.primary_owner ?? null} size="sm" />
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
 <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[hsl(var(--border-subtle))] text-muted-foreground">
 +{skills.length - 5}
 </span>
 )}
 </div>
 )}

 <div className="mt-auto space-y-2">
 {targetCount > 0 && (
 <div className="flex items-center gap-2">
 <Users className="h-3 w-3 text-muted-foreground" />
 <div className="flex-1 h-1.5 rounded-full bg-[hsl(var(--border-subtle))]/60 overflow-hidden">
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
 {job.created_at ? formatRelativeTime(job.created_at) :"—"}
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
