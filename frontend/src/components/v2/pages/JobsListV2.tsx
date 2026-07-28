"use client";

import { useState, type ReactNode } from"react";
import Link from"next/link";
import { useRouter, useSearchParams } from"next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from"@tanstack/react-query";
import {
 Briefcase,
 Building2,
 DollarSign,
 LayoutGrid,
 Link2,
 List,
 MapPin,
 Plus,
 Search,
 Sparkles,
 UserSquare2,
 Users,
} from"lucide-react";
import api from"@/lib/api";
import { cn, formatRelativeTime } from"@/lib/utils";
import { useDebouncedValue } from"@/lib/use-debounced-value";
import { resolveViewState } from"@/lib/view-state";
import { useCapabilities } from"@/hooks/useCapability";
import { QueryStateNotice } from"@/components/ds/QueryStateNotice";
import { AddJobModal } from"@/components/AppShell";
import { GenerateInviteLinkV2 } from"@/components/v2/modals/GenerateInviteLinkV2";
import { Badge } from"@/components/ui/badge";
import { Button } from"@/components/ui/button";
import { Card } from"@/components/ui/card";
import { Input } from"@/components/ui/input";
import {
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
} from"@/components/ui/table";
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
import { useUiStore } from"@/store/ui";
import {
 initialMineFromUrl,
 initialStatusFromUrl,
} from"@/lib/jobs-url-filters";
import type {
 PriorityChannel,
 PriorityRank,
} from "@/lib/priority-work-api";

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
type PriorityWorkFilter = "any" | "assigned" | "carry_over" | "either";

const SORT_OPTIONS: { value: JobSortValue; label: string }[] = [
 { value: "newest", label: "Od najnowszej" },
 { value: "oldest", label: "Od najstarszej" },
 { value: "deadline", label: "Wg terminu" },
];

const PRIORITY_WORK_OPTIONS: {
 value: PriorityWorkFilter;
 label: string;
}[] = [
 { value: "any", label: "Priority Work: wszystko" },
 { value: "assigned", label: "Przydzielone w planie" },
 { value: "carry_over", label: "Tylko carry-over" },
 { value: "either", label: "Plan lub carry-over" },
];

interface JobPriorityWorkSummary {
 priority_assignment?: {
 id: number;
 rank: PriorityRank;
 channel: PriorityChannel;
 } | null;
 priority_carry_over_count?: number | null;
}

function priorityChannelLabel(channel: PriorityChannel): string {
 if (channel === "database") return "Baza NEXUS";
 if (channel === "linkedin") return "LinkedIn";
 return "TAC / mieszany";
}

export function JobPriorityWorkBadges({
 job,
}: {
 job: JobPriorityWorkSummary;
}) {
 const assignment = job.priority_assignment;
 const carryOverCount = job.priority_carry_over_count ?? 0;
 if (!assignment && carryOverCount === 0) return null;
 return (
 <div
 className="flex flex-wrap items-center gap-1"
 data-testid="job-priority-work-badges"
 >
 {assignment ? (
 <Badge
 size="sm"
 variant="soft"
 aria-label={`Assignment Priority Work ${assignment.rank}`}
 >
 Plan {assignment.rank} · {priorityChannelLabel(assignment.channel)}
 </Badge>
 ) : null}
 {carryOverCount > 0 ? (
 <Badge
 size="sm"
 variant="warning"
 aria-label={`${carryOverCount} procesów carry-over`}
 >
 Carry-over: {carryOverCount}
 </Badge>
 ) : null}
 </div>
 );
}

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
 ?"bg-primary text-white border-primary shadow-xs"
 :"bg-card text-foreground border-border hover:text-foreground"
 )}
 >
 {children}
 </button>
 );
}

/** Compact table presentation of the jobs list (alternative to the tile grid). */
function JobsTable({
 items,
 onOpen,
 onInvite,
}: {
 items: any[];
 onOpen: (id: number) => void;
 /** `undefined` = brak capability `invite_link.create` — nie renderujemy akcji. */
 onInvite?: (id: number) => void;
}) {
 return (
 <Table>
 <TableHeader>
 <TableRow className="hover:bg-transparent">
 <TableHead>Oferta</TableHead>
 <TableHead>Klient</TableHead>
 <TableHead>Status</TableHead>
 <TableHead>Odpowiedzialny</TableHead>
 <TableHead>Lokalizacja</TableHead>
 <TableHead className="w-[150px]">Kandydaci</TableHead>
 <TableHead>Dodano</TableHead>
 <TableHead className="w-[44px]" />
 </TableRow>
 </TableHeader>
 <TableBody>
 {items.map((job: any) => {
 const statusVariant = STATUS_VARIANT[job.status] ??"neutral";
 const statusLabel = STATUS_LABEL[job.status] ?? job.status;
 const filledCount = job.candidates_count ?? job.filled_count ?? 0;
 const targetCount = job.target_positions ?? job.headcount ?? 1;
 const progress = Math.min(
 100,
 Math.round((filledCount / Math.max(1, targetCount)) * 100)
 );
 return (
 <TableRow key={job.id} interactive onClick={() => onOpen(job.id)}>
 <TableCell className="max-w-[340px]">
 <div className="font-medium text-foreground truncate">
 {job.title}
 </div>
 {job.reference_number && (
 <div
 className="font-mono text-[10px] text-muted-foreground/80"
 title="Numer referencyjny"
 >
 {job.reference_number}
 </div>
 )}
 </TableCell>
 <TableCell>
 {job.client_name ? (
 <span className="inline-flex items-center gap-1 text-sm text-foreground">
 <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
 {job.client_name}
 </span>
 ) : (
 <span className="text-muted-foreground">—</span>
 )}
 </TableCell>
 <TableCell>
 <div className="flex items-center gap-1 flex-wrap">
 <Badge size="sm" variant={statusVariant}>
 {statusLabel}
 </Badge>
 {job.tac_id == null && (
 <Badge size="sm" variant="warning">
 Brak TAC
 </Badge>
 )}
 <JobPriorityWorkBadges job={job} />
 </div>
 </TableCell>
 <TableCell>
 <OwnerBadge user={job.primary_owner ?? null} size="sm" />
 </TableCell>
 <TableCell>
 {job.location || job.seniority ? (
 <div className="flex items-center gap-2 text-xs text-foreground">
 {job.location && (
 <span className="inline-flex items-center gap-1">
 <MapPin className="h-3 w-3 text-muted-foreground" />
 {job.location}
 </span>
 )}
 {job.seniority && (
 <Badge size="sm" variant="plum">
 {job.seniority}
 </Badge>
 )}
 </div>
 ) : (
 <span className="text-muted-foreground">—</span>
 )}
 </TableCell>
 <TableCell>
 <div className="flex items-center gap-2">
 <div className="flex-1 h-1.5 rounded-full bg-[hsl(var(--border))]/60 overflow-hidden min-w-[48px]">
 <div
 className="h-full bg-primary rounded-full"
 style={{ width: `${progress}%` }}
 />
 </div>
 <span className="text-[10px] font-mono text-muted-foreground whitespace-nowrap">
 {filledCount}/{targetCount}
 </span>
 </div>
 </TableCell>
 <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
 {job.created_at ? formatRelativeTime(job.created_at) :"—"}
 </TableCell>
 <TableCell>
 {job.status === "published" && onInvite && (
 <button
 type="button"
 onClick={(e) => {
 e.stopPropagation();
 onInvite(job.id);
 }}
 className="p-1 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
 title="Wygeneruj link aplikacyjny"
 aria-label="Wygeneruj link aplikacyjny"
 >
 <Link2 className="h-3.5 w-3.5" />
 </button>
 )}
 </TableCell>
 </TableRow>
 );
 })}
 </TableBody>
 </Table>
 );
}

export function JobsListV2() {
 const [search, setSearch] = useState("");
 // Stan początkowy z URL-a. Bez tego deep-linki były atrapą: pulpit prowadzi
 // na `/jobs?mine=0&status=published`, a lista i tak startowała z pustymi
 // filtrami, więc użytkownik dostawał WSZYSTKIE oferty (z Draftami włącznie)
 // i nie miał sygnału, że kliknięty filtr nie zadziałał.
 //
 // Czytane raz, przy montowaniu — te parametry są punktem wejścia, nie
 // dwukierunkowym wiązaniem; późniejsze klikanie w filtry nie ma przepisywać
 // URL-a ani być przez niego nadpisywane.
 const searchParams = useSearchParams();
 const [statusFilter, setStatusFilter] = useState<JobStatusValue[]>(
 () => initialStatusFromUrl(searchParams)
 );
 const [typeFilter, setTypeFilter] = useState<JobType>("all");
 const [mine, setMine] = useState(() => initialMineFromUrl(searchParams));
 const [responsibleIds, setResponsibleIds] = useState<number[]>([]);
 const [clientIds, setClientIds] = useState<number[]>([]);
 const [ccIds, setCcIds] = useState<number[]>([]);
 const [needsSourcing, setNeedsSourcing] = useState(false);
 const [activeInSearch, setActiveInSearch] = useState(false);
 const [deadlinePreset, setDeadlinePreset] = useState<DeadlinePreset>("any");
 const [openOnly, setOpenOnly] = useState(false);
 const [sort, setSort] = useState<JobSortValue>("newest");
 const [priorityWorkFilter, setPriorityWorkFilter] =
 useState<PriorityWorkFilter>("any");
 const [page, setPage] = useState(1);
 const [showAdd, setShowAdd] = useState(false);
 const [inviteModalForJob, setInviteModalForJob] = useState<number | null>(null);
 const queryClient = useQueryClient();
 const router = useRouter();
 const jobsView = useUiStore((s) => s.jobsView);
 const setJobsView = useUiStore((s) => s.setJobsView);

 // Do zapytania idzie wartość zdebouncowana, do inputa surowa — inaczej każde
 // naciśnięcie klawisza wysyłało request i przerzucało tabelę w stan ładowania.
 const debouncedSearch = useDebouncedValue(search, 300);

 const dl = deadlineParams(deadlinePreset);

 // Jeden rejestr capability dla nagłówka, pustego stanu i akcji w wierszach
 // (audyt F-19) — wcześniej gate'owany był tylko przycisk w nagłówku.
 const can = useCapabilities();
 const canCreateJob = can["job.create"];
 const canInvite = can["invite_link.create"];

 const { data, isLoading, isError, error, refetch } = useQuery({
 queryKey: ["jobs-v2",
 debouncedSearch,
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
 priorityWorkFilter,
 page,
 ],
 queryFn: () =>
 api
 .get("/api/jobs", {
 params: {
 q: debouncedSearch || undefined,
 status: statusFilter.length ? statusFilter : undefined,
 recruitment_type: typeFilter !== "all" ? typeFilter : undefined,
 mine: mine ? true : undefined,
 responsible_id: responsibleIds.length ? responsibleIds : undefined,
 client_id: clientIds.length ? clientIds : undefined,
 competence_category_id: ccIds.length ? ccIds : undefined,
 needs_sourcing: needsSourcing ? true : undefined,
 active_in_search: activeInSearch ? true : undefined,
 open_only: openOnly ? true : undefined,
 priority_work:
 priorityWorkFilter === "any" ? undefined : priorityWorkFilter,
 sort,
 ...dl,
 page,
 },
 paramsSerializer: { indexes: null },
 })
 .then((r) => r.data),
 // Poprzednia strona wyników zostaje na ekranie do czasu przyjścia nowej —
 // bez tego lista migocze pustym stanem ładowania przy każdej zmianie filtra.
 placeholderData: keepPreviousData,
 });

 const items = data?.items ?? [];
 const total = data?.total ?? 0;
 const pageSize = data?.page_size ?? 20;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));

 // 403/404/5xx NIE mogą renderować się jako „Brak ofert" (audyt F-20).
 const viewState = resolveViewState({
 isLoading,
 isError,
 error,
 isEmpty: items.length === 0,
 });
 const failed =
 viewState === "forbidden" ||
 viewState === "not_found" ||
 viewState === "error";

 return (
 <div className="max-w-[1400px] mx-auto space-y-4">
 {/* Header */}
 <div className="flex items-end justify-between flex-wrap gap-3">
 <div>
 <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
 Pipeline · Oferty
 </p>
 <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
 Oferty pracy
 </h1>
 <p className="text-sm text-muted-foreground mt-1" aria-live="polite">
 {isLoading
 ?"Ładowanie…"
 : failed
 ?"Nie udało się pobrać listy"
 : `${total} ofert`}
 </p>
 </div>
 <div className="flex items-center gap-2">
 {/* Przełącznik widoku: kafelki vs lista */}
 <div
 className="flex items-center rounded-md border border-border overflow-hidden"
 role="group"
 aria-label="Widok ofert"
 >
 <button
 type="button"
 onClick={() => setJobsView("tiles")}
 title="Widok kafelków"
 aria-pressed={jobsView === "tiles"}
 className={cn("h-9 w-9 flex items-center justify-center transition-colors",
 jobsView === "tiles"
 ?"bg-primary text-white"
 :"text-muted-foreground hover:bg-primary/10"
 )}
 >
 <LayoutGrid className="h-4 w-4" />
 </button>
 <button
 type="button"
 onClick={() => setJobsView("list")}
 title="Widok listy"
 aria-pressed={jobsView === "list"}
 className={cn("h-9 w-9 flex items-center justify-center transition-colors",
 jobsView === "list"
 ?"bg-primary text-white"
 :"text-muted-foreground hover:bg-primary/10"
 )}
 >
 <List className="h-4 w-4" />
 </button>
 </div>
 {/* Capability `job.create` = backendowy TacPlus (POST /api/jobs). */}
 {canCreateJob && (
 <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
 <Plus className="h-4 w-4" /> Nowa oferta
 </Button>
 )}
 </div>
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
 ?"bg-primary text-white shadow-xs"
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
 <Select
 value={priorityWorkFilter}
 onValueChange={(value) => {
 setPriorityWorkFilter(value as PriorityWorkFilter);
 setPage(1);
 }}
 >
 <SelectTrigger
 className="h-9 w-[210px] font-medium"
 aria-label="Filtr Priority Work"
 >
 <SelectValue placeholder="Priority Work: wszystko" />
 </SelectTrigger>
 <SelectContent>
 {PRIORITY_WORK_OPTIONS.map((option) => (
 <SelectItem key={option.value} value={option.value}>
 {option.label}
 </SelectItem>
 ))}
 </SelectContent>
 </Select>
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
 title="Wszystko poza zamkniętymi — Draft też się liczy"
 >
 Niezamknięte
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

 {/* Wyniki — kafelki lub lista */}
 {isLoading ? (
 jobsView === "list" ? (
 <div className="rounded-lg border border-border bg-card divide-y divide-border/60">
 {Array.from({ length: 8 }).map((_, i) => (
 <div key={i} className="h-12 flex items-center px-4 animate-pulse">
 <div className="h-3 bg-[hsl(var(--border))] rounded w-1/3" />
 </div>
 ))}
 </div>
 ) : (
 <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
 {Array.from({ length: 6 }).map((_, i) => (
 <Card key={i} className="animate-pulse h-48">
 <div className="h-4 bg-[hsl(var(--border))] rounded w-3/4 mb-3" />
 <div className="h-3 bg-[hsl(var(--border))] rounded w-1/2" />
 </Card>
 ))}
 </div>
 )
 ) : failed ? (
 <QueryStateNotice
 state={viewState as "forbidden" | "not_found" | "error"}
 description={
 viewState === "forbidden"
 ?"Twoja rola nie ma dostępu do listy ofert. Lista NIE jest pusta — poproś administratora o uprawnienia."
 : undefined
 }
 onRetry={() => void refetch()}
 />
 ) : viewState === "empty" ? (
 <div className="py-12 text-center">
 <Briefcase className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
 <p className="text-sm text-muted-foreground">
 Brak ofert.{" "}
 {canCreateJob && (
 <>
 <button
 onClick={() => setShowAdd(true)}
 className="text-primary hover:underline"
 >
 Utwórz pierwszą
 </button>
 .
 </>
 )}
 </p>
 </div>
 ) : jobsView === "list" ? (
 <JobsTable
 items={items}
 onOpen={(id) => router.push(`/jobs/${id}`)}
 onInvite={canInvite ? (id) => setInviteModalForJob(id) : undefined}
 />
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
 {job.status === "published" && canInvite && (
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

 {(job.priority_assignment ||
 (job.priority_carry_over_count ?? 0) > 0) && (
 <div className="mb-2">
 <JobPriorityWorkBadges job={job} />
 </div>
 )}

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

 {viewState === "ready" && total > pageSize && (
 <div className="flex items-center justify-between text-sm">
 <span className="text-muted-foreground">
 Strona <strong className="text-foreground">{page}</strong> z {totalPages}
 </span>
 <div className="flex gap-2">
 <Button
 size="sm"
 variant="outline"
 disabled={page <= 1}
 onClick={() => setPage((p) => p - 1)}
 >
 Poprzednia
 </Button>
 <Button
 size="sm"
 variant="outline"
 disabled={page >= totalPages}
 onClick={() => setPage((p) => p + 1)}
 >
 Następna
 </Button>
 </div>
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
