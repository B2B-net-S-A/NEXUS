"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
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
  SlidersHorizontal,
  Sparkles,
  UserSquare2,
  Users,
} from "lucide-react";
import api from "@/lib/api";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";
import { useCapabilities } from "@/hooks/useCapability";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { AddJobModal } from "@/components/AppShell";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { OwnerBadge } from "@/components/v2/jobs/OwnerBadge";
import { JobReadinessDock } from "@/components/v2/jobs/JobReadinessDock";
import { MultiSelectFilter } from "@/components/v2/filters/MultiSelectFilter";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";
import { ClientMultiSelect } from "@/components/v2/filters/ClientMultiSelect";
import { CompetenceCategoryMultiSelect } from "@/components/v2/filters/CompetenceCategoryMultiSelect";
import {
  JOB_STATUS_OPTIONS,
  type JobStatusValue,
} from "@/lib/filter-options";
import { useUiStore } from "@/store/ui";
import {
  initialMineFromUrl,
  initialStatusFromUrl,
} from "@/lib/jobs-url-filters";
import { jobsMissingRequestOwner } from "@/lib/jobs-quick-filters";
import { extractSkills } from "@/lib/job-skills";
import { classifyJobDeadline } from "@/lib/job-deadline";
import {
  buildStageFunnel,
  funnelTooltip,
  funnelTotal,
  type FunnelGroupKey,
} from "@/lib/job-pipeline-funnel";
import { RECRUITMENT_TYPE_LABEL } from "@/lib/recruitment-type";
import type {
  PriorityChannel,
  PriorityRank,
} from "@/lib/priority-work-api";

// `recruitment_type` z backendu (`RecruitmentType`, `body_leasing` |
// `sales_project` | `tender`) — do 2026-09 ten filtr wysyłał `"sales"` /
// `"tenders"`, które nie są prawidłowymi wartościami enuma. FastAPI waliduje
// query param typu Enum, więc kliknięcie zakładki „Sales" lub „Przetargi"
// kończyło się 422 i całą listą renderowaną jako awaria — dokładnie ten sam
// gatunek błędu, który wcześniej naprawiono dla `ContractTypeValue` w
// `filter-options.ts` (tam wartości też były przepisane z tego enuma).
// Etykiety zostają PL/EN tak jak dziś — to wartości WYSYŁANE do API się liczą.
type JobType = "all" | "body_leasing" | "sales_project" | "tender";

const FILTER_TABS: { value: JobType; label: string }[] = [
  { value: "all", label: "Wszystkie" },
  { value: "body_leasing", label: "Body leasing" },
  { value: "sales_project", label: "Sales" },
  { value: "tender", label: "Przetargi" },
];

const STATUS_VARIANT: Record<
  string, "success" | "soft" | "neutral" | "warning" | "danger"
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

// Kolor paska mini-lejka per grupa — WYŁĄCZNIE tokeny (`primary`/`success`/
// `muted-foreground`), rosnąca nieprzezroczystość = postęp w lejku, `hired`
// dostaje osobny odcień sukcesu (nie jest "dalszym stopniem" tego samego
// koloru — to inny fakt: proces się udał).
const FUNNEL_BAR_COLOR: Record<FunnelGroupKey, string> = {
  new: "bg-muted-foreground/30",
  screening: "bg-primary/40",
  verified: "bg-primary/60",
  with_client: "bg-primary/80",
  contract: "bg-primary",
  hired: "bg-success",
};

type DeadlinePreset = "any" | "overdue" | "next7" | "next30" | "has" | "none";

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
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
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

/**
 * Wiersz w sekcji "Szybkie" lewej kolumny filtrów (makieta „01 Lista").
 *
 * `count` jest OPCJONALNY i CELOWO nie ma go na większości z sześciu filtrów:
 * dałby go tylko backend liczący każdy fasetę osobno, a to sześć dodatkowych
 * zapytań przy KAŻDYM renderze — zakazane wprost w briefie. Jedyny filtr
 * z licznikiem („Brak ownera requestu") liczy go z już wczytanej strony
 * wyników, więc `count` na nim jest darmowy — ale opisuje TYLKO tę stronę.
 */
function QuickFilterRow({
  active,
  onClick,
  label,
  count,
  tone = "neutral",
  title,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  tone?: "neutral" | "warning" | "danger";
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={title}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
        active
          ? "bg-primary/10 font-medium text-primary"
          : "text-foreground hover:bg-accent",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          tone === "warning"
            ? "bg-warning"
            : tone === "danger"
              ? "bg-destructive"
              : "bg-muted-foreground/40",
        )}
      />
      <span className="flex-1 truncate">{label}</span>
      {count != null && (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {count}
        </span>
      )}
    </button>
  );
}

/** Compact table presentation of the jobs list (alternative to the tile grid). */
function JobsTable({
  items,
  selectedId,
  onSelect,
  onInvite,
}: {
  items: any[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** `undefined` = brak capability `invite_link.create` — nie renderujemy akcji. */
  onInvite?: (id: number) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Rekrutacja</TableHead>
          <TableHead>Klient</TableHead>
          <TableHead className="w-[140px]">Pipeline</TableHead>
          <TableHead>Właściciel</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Deadline</TableHead>
          <TableHead className="w-[44px]" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((job: any) => {
          const statusVariant = STATUS_VARIANT[job.status] ?? "neutral";
          const statusLabel = STATUS_LABEL[job.status] ?? job.status;
          const deadlineInfo = classifyJobDeadline(job.deadline);
          // `stage_breakdown` przychodzi z `GET /api/jobs?include_stage_counts=true`
          // — JEDNO zapytanie GROUP BY na całą stronę, zero zapytań per wiersz.
          // Jego brak (np. odpowiedź spoza kontraktu) cofa wiersz do starego
          // paska `filled/target`, zamiast udawać pełny lejek zerami.
          const hasStageBreakdown = job.stage_breakdown != null;
          const funnelGroups = hasStageBreakdown
            ? buildStageFunnel(job.stage_breakdown)
            : [];
          const funnelCount = funnelTotal(funnelGroups);
          const targetCount = job.headcount ?? 1;
          const filledCount = job.candidate_count ?? 0;
          const legacyProgress = Math.min(
            100,
            Math.round((filledCount / Math.max(1, targetCount)) * 100),
          );
          return (
            <TableRow
              key={job.id}
              interactive
              selected={selectedId === job.id}
              onClick={() => onSelect(job.id)}
            >
              <TableCell className="max-w-[300px]">
                <Link
                  href={`/jobs/${job.id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="block truncate font-medium text-foreground hover:text-primary hover:underline"
                >
                  {job.title}
                </Link>
                <div className="mt-0.5 flex items-center gap-1.5">
                  {job.reference_number && (
                    <span
                      className="font-mono text-[10px] text-muted-foreground/80"
                      title="Numer referencyjny"
                    >
                      {job.reference_number}
                    </span>
                  )}
                  {job.recruitment_type && (
                    <Badge size="sm" variant="neutral">
                      {RECRUITMENT_TYPE_LABEL[job.recruitment_type] ??
                        job.recruitment_type}
                    </Badge>
                  )}
                </div>
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
                {hasStageBreakdown ? (
                  <div
                    className="flex items-center gap-1.5"
                    title={funnelTooltip(funnelGroups)}
                  >
                    <div className="flex h-2 w-16 overflow-hidden rounded-full bg-[hsl(var(--border))]/60">
                      {funnelCount > 0 &&
                        funnelGroups.map((g) =>
                          g.count > 0 ? (
                            <div
                              key={g.key}
                              className={cn("h-full", FUNNEL_BAR_COLOR[g.key])}
                              style={{ width: `${(g.count / funnelCount) * 100}%` }}
                            />
                          ) : null,
                        )}
                    </div>
                    <span className="whitespace-nowrap font-mono text-[10px] text-muted-foreground">
                      {funnelCount}
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 min-w-[48px] flex-1 overflow-hidden rounded-full bg-[hsl(var(--border))]/60">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${legacyProgress}%` }}
                      />
                    </div>
                    <span className="whitespace-nowrap font-mono text-[10px] text-muted-foreground">
                      {filledCount}/{targetCount}
                    </span>
                  </div>
                )}
              </TableCell>
              <TableCell>
                <OwnerBadge user={job.primary_owner ?? null} size="sm" />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1">
                  <Badge size="sm" variant={statusVariant}>
                    {statusLabel}
                  </Badge>
                  {job.tac_id == null && (
                    <span title="Request nie ma jawnie wybranego ownera TAC">
                      <Badge size="sm" variant="warning">
                        Brak ownera requestu
                      </Badge>
                    </span>
                  )}
                  <JobPriorityWorkBadges job={job} />
                </div>
              </TableCell>
              <TableCell>
                {deadlineInfo.urgency === "none" ? (
                  <span className="text-xs text-muted-foreground">—</span>
                ) : (
                  <span
                    className={cn(
                      "whitespace-nowrap text-xs font-medium",
                      deadlineInfo.urgency === "overdue"
                        ? "text-destructive"
                        : deadlineInfo.urgency === "soon"
                          ? "text-warning"
                          : "text-muted-foreground",
                    )}
                  >
                    {formatDate(job.deadline)} ·{" "}
                    {deadlineInfo.urgency === "overdue"
                      ? "po terminie"
                      : `${deadlineInfo.daysLeft} d`}
                  </span>
                )}
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
  // "Brak ownera requestu" jako FILTR (nie tylko badge, makieta „01 Lista").
  // `GET /api/jobs` nie ma parametru `tac_id`/`has_owner`, więc to zawęża
  // WYŁĄCZNIE bieżącą, już wczytaną stronę — patrz `jobs-quick-filters.ts`.
  const [noOwnerOnly, setNoOwnerOnly] = useState(false);
  const [sort, setSort] = useState<JobSortValue>("newest");
  const [priorityWorkFilter, setPriorityWorkFilter] =
    useState<PriorityWorkFilter>("any");
  const [page, setPage] = useState(1);
  const [showAdd, setShowAdd] = useState(false);
  const [inviteModalForJob, setInviteModalForJob] = useState<number | null>(null);
  // Dok "Gotowość zlecenia" — zaznaczenie liczone WZGLĘDEM widocznej listy
  // (patrz `effSelectedJobId` niżej), tak jak `effSelectedId` w warsztacie C2
  // (review #1380): zaznaczona rekrutacja odfiltrowana/spoza strony nie może
  // zostawić doku bez podświetlonego wiersza.
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const queryClient = useQueryClient();
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
            // Mini-lejek w wierszu (6 grup etapów) — JEDNO dodatkowe GROUP BY
            // na całą stronę wyników (`stage_breakdown` per wiersz), zero
            // zapytań per wiersz. Patrz `lib/job-pipeline-funnel.ts`.
            include_stage_counts: true,
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

  // "Brak ownera requestu" — liczone z bieżącej strony, WŁĄCZNIE gdy filtr
  // jest wyłączony (darmowe: `items` już są w pamięci). Aktywny filtr zawęża
  // TĘ SAMĄ tablicę do prezentacji, w obu widokach (lista i kafelki).
  const noOwnerOnPage = useMemo(() => jobsMissingRequestOwner(items), [items]);
  const visibleItems = noOwnerOnly ? noOwnerOnPage : items;

  // Zaznaczenie doku liczone względem WIDOCZNEJ listy — zaznaczona rekrutacja
  // odfiltrowana przez "Brak ownera requestu" albo spoza tej strony nie może
  // zostawić doku bez podświetlonego wiersza (lustro `effSelectedId` w C2,
  // page.tsx, review #1380). Dok domyślnie pokazuje pierwszy widoczny wiersz.
  const effSelectedJobId: number | null = useMemo(() => {
    if (
      selectedJobId != null &&
      visibleItems.some((j: any) => j.id === selectedJobId)
    ) {
      return selectedJobId;
    }
    return visibleItems[0]?.id ?? null;
  }, [selectedJobId, visibleItems]);
  const selectedListItem = visibleItems.find(
    (j: any) => j.id === effSelectedJobId,
  );

  // 403/404/5xx NIE mogą renderować się jako „Brak ofert" (audyt F-20).
  // Celowo liczone z `items` SERWEROWYCH, nie `visibleItems` — filtr "Brak
  // ownera requestu" jest lokalny dla przeglądarki i nie może udawać, że
  // backend nie ma żadnych rekrutacji.
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

  const resetFilters = () => {
    setTypeFilter("all");
    setStatusFilter([]);
    setMine(false);
    setResponsibleIds([]);
    setClientIds([]);
    setCcIds([]);
    setNeedsSourcing(false);
    setActiveInSearch(false);
    setDeadlinePreset("any");
    setOpenOnly(false);
    setPriorityWorkFilter("any");
    setNoOwnerOnly(false);
    setPage(1);
  };

  return (
    <div className="max-w-[1400px] mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-eyebrow text-primary">
            Pipeline · Rekrutacje
          </p>
          <h1 className="font-semibold text-3xl font-extrabold tracking-heading-tight text-foreground mt-1">
            Rekrutacje
          </h1>
          <p className="text-sm text-muted-foreground mt-1" aria-live="polite">
            {isLoading
              ? "Ładowanie…"
              : failed
                ? "Nie udało się pobrać listy"
                : `${total} rekrutacji`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Przełącznik widoku: kafelki vs lista */}
          <div
            className="flex items-center rounded-md border border-border overflow-hidden"
            role="group"
            aria-label="Widok rekrutacji"
          >
            <button
              type="button"
              onClick={() => setJobsView("tiles")}
              title="Widok kafelków"
              aria-pressed={jobsView === "tiles"}
              className={cn("h-9 w-9 flex items-center justify-center transition-colors",
                jobsView === "tiles"
                  ? "bg-primary text-white"
                  : "text-muted-foreground hover:bg-primary/10"
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
                  ? "bg-primary text-white"
                  : "text-muted-foreground hover:bg-primary/10"
              )}
            >
              <List className="h-4 w-4" />
            </button>
          </div>
          {/* Capability `job.create` = backendowy TacPlus (POST /api/jobs). */}
          {canCreateJob && (
            <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
              <Plus className="h-4 w-4" /> Nowa rekrutacja
            </Button>
          )}
        </div>
      </div>

      {/* Grid jak C2: lewa kolumna filtrów, środek, dok gotowości */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[230px_minmax(0,1fr)_360px]">
        {/* ── Lewa kolumna: filtry ─────────────────────────────────── */}
        <aside className="space-y-4 self-start rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            Filtry
            <button
              type="button"
              onClick={resetFilters}
              className="ml-auto text-[11px] font-normal text-primary hover:underline"
            >
              Wyczyść
            </button>
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">Typ</div>
            <div className="flex flex-wrap gap-1">
              {FILTER_TABS.map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => {
                    setTypeFilter(tab.value);
                    setPage(1);
                  }}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                    typeFilter === tab.value
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-foreground hover:bg-accent",
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-border" />

          <div className="space-y-1">
            <div className="px-2 text-[11px] font-medium text-muted-foreground">
              Szybkie
            </div>
            <QuickFilterRow
              active={mine}
              onClick={() => {
                setMine((p) => !p);
                setPage(1);
              }}
              label="Moje projekty"
            />
            <QuickFilterRow
              active={openOnly}
              onClick={() => {
                setOpenOnly((p) => !p);
                setPage(1);
              }}
              label="Niezamknięte"
              title="Wszystko poza zamkniętymi — Draft też się liczy"
            />
            <QuickFilterRow
              active={needsSourcing}
              onClick={() => {
                setNeedsSourcing((p) => !p);
                setPage(1);
              }}
              label="Potrzebny search"
              tone="warning"
              title="Tylko rekrutacje oznaczone jako wymagające sourcingu"
            />
            <QuickFilterRow
              active={activeInSearch}
              onClick={() => {
                setActiveInSearch((p) => !p);
                setPage(1);
              }}
              label="Aktywni w searchu"
              title="Tylko rekrutacje z aktywnym rekruterem w sourcingu"
            />
            <QuickFilterRow
              active={noOwnerOnly}
              onClick={() => setNoOwnerOnly((p) => !p)}
              label="Brak ownera requestu"
              count={noOwnerOnPage.length}
              tone="danger"
              title="Liczba dotyczy WYŁĄCZNIE bieżącej, już wczytanej strony — GET /api/jobs nie ma jeszcze filtra po ownerze requestu (tac_id), więc to nie jest liczba w całej bazie."
            />
            <QuickFilterRow
              active={deadlinePreset === "next7"}
              onClick={() => {
                setDeadlinePreset((p) => (p === "next7" ? "any" : "next7"));
                setPage(1);
              }}
              label="Deadline ≤ 7 dni"
              tone="warning"
              title="To samo co opcja „Najbliższe 7 dni” w filtrze Termin niżej"
            />
          </div>

          <div className="border-t border-border" />

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">Status</div>
            <MultiSelectFilter<JobStatusValue>
              value={statusFilter}
              onChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
              options={JOB_STATUS_OPTIONS}
              placeholder="Wszystkie statusy"
              searchPlaceholder="Szukaj statusu…"
              triggerWidthClass="w-full"
              triggerLabel={(n) =>
                n === 1
                  ? (JOB_STATUS_OPTIONS.find((o) => o.value === statusFilter[0])
                      ?.label ?? "Status")
                  : `Status: ${n}`
              }
            />
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">Klient</div>
            <ClientMultiSelect
              value={clientIds}
              onChange={(ids) => {
                setClientIds(ids);
                setPage(1);
              }}
            />
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Kategoria
            </div>
            <CompetenceCategoryMultiSelect
              value={ccIds}
              onChange={(ids) => {
                setCcIds(ids);
                setPage(1);
              }}
              triggerWidthClass="w-full"
            />
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Osoba odpowiedzialna
            </div>
            <UserMultiSelect
              value={responsibleIds}
              onChange={(ids) => {
                setResponsibleIds(ids);
                setPage(1);
              }}
              placeholder="Osoba odpowiedzialna"
              searchPlaceholder="Szukaj osoby…"
              triggerWidthClass="w-full"
            />
          </div>

          <div className="border-t border-border" />

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Priority Work
            </div>
            <Select
              value={priorityWorkFilter}
              onValueChange={(value) => {
                setPriorityWorkFilter(value as PriorityWorkFilter);
                setPage(1);
              }}
            >
              <SelectTrigger
                className="h-9 w-full font-medium"
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
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">Termin</div>
            <Select
              value={deadlinePreset}
              onValueChange={(v) => {
                setDeadlinePreset(v as DeadlinePreset);
                setPage(1);
              }}
            >
              <SelectTrigger className="h-9 w-full font-medium">
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
          </div>
        </aside>

        {/* ── Środek: wyszukiwarka, sortowanie, lista/kafelki ───────── */}
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-[260px] max-w-lg flex-1">
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
                  ? "Twoja rola nie ma dostępu do listy rekrutacji. Lista NIE jest pusta — poproś administratora o uprawnienia."
                  : undefined
              }
              onRetry={() => void refetch()}
            />
          ) : viewState === "empty" ? (
            <div className="py-12 text-center">
              <Briefcase className="h-10 w-10 mx-auto text-muted-foreground mb-2 opacity-40" />
              <p className="text-sm text-muted-foreground">
                Brak rekrutacji.{" "}
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
          ) : visibleItems.length === 0 ? (
            // `noOwnerOnly` zawęża stronę lokalnie — żadnego wiersza NIE
            // znaczy tu "brak rekrutacji", tylko "żaden z wczytanych nie
            // pasuje". Osobny, łagodniejszy komunikat niż pełny pusty stan.
            <div className="rounded-lg border border-dashed border-border bg-muted/20 py-10 px-4 text-center text-sm text-muted-foreground">
              Żadna z {items.length} rekrutacji na tej wczytanej stronie nie ma
              pustego ownera requestu.{" "}
              {totalPages > 1 && "Sprawdź kolejne strony albo "}
              <button
                type="button"
                onClick={() => setNoOwnerOnly(false)}
                className="text-primary hover:underline"
              >
                wyłącz filtr
              </button>
              .
            </div>
          ) : jobsView === "list" ? (
            <JobsTable
              items={visibleItems}
              selectedId={effSelectedJobId}
              onSelect={setSelectedJobId}
              onInvite={canInvite ? (id) => setInviteModalForJob(id) : undefined}
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {visibleItems.map((job: any) => {
                const skills = extractSkills(job.must_skills);
                const statusVariant = STATUS_VARIANT[job.status] ?? "neutral";
                const statusLabel = STATUS_LABEL[job.status] ?? job.status;
                // `candidates_count`/`filled_count`/`target_positions` nie
                // istnieją w odpowiedzi API (patrz `JobsTable` — poprawny
                // klucz to `candidate_count` + `headcount`) — ZOSTAWIONE tu
                // bez zmian celowo: kafelki są poza zakresem tego PR-a
                // ("kafelki nietknięte"), poprawka idzie osobnym follow-upem.
                const filledCount = job.candidates_count ?? job.filled_count ?? 0;
                const targetCount = job.target_positions ?? job.headcount ?? 1;
                const progress = Math.min(
                  100,
                  Math.round((filledCount / Math.max(1, targetCount)) * 100)
                );
                return (
                  // `can_open === false`: rejestr pokazuje tę rekrutację (jest
                  // ŚWIADOMIE ogólnofirmowy — patrz komentarz przy zapytaniu
                  // w `jobs.py`), ale detal egzekwuje dokładny zakres klient–TAC
                  // i zwróci 403. Komunikat po 403 jest dobry, tylko przychodzi
                  // ZA PÓŹNO: Delivery Lead bez przypisań klikał kolejne wiersze
                  // i za każdym razem trafiał w ścianę. Mówimy o tym ZAWCZASU.
                  //
                  // Wiersz zostaje WIDOCZNY i czytelny — flaga nic nie ujawnia,
                  // bo te rekrutacje i tak są na liście. Zmienia się tylko to, że
                  // nie udaje klikalnego. `pointer-events-none` + `tabIndex={-1}`
                  // odcinają myszkę i klawiaturę, `aria-disabled` mówi to samo
                  // czytnikowi ekranu.
                  <Link
                    key={job.id}
                    href={`/jobs/${job.id}`}
                    aria-disabled={job.can_open === false || undefined}
                    tabIndex={job.can_open === false ? -1 : undefined}
                    title={
                      job.can_open === false
                        ? "Nie masz dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu."
                        : undefined
                    }
                    className={
                      job.can_open === false
                        ? "pointer-events-none opacity-60"
                        : undefined
                    }
                  >
                    <Card
                      variant={job.can_open === false ? "default" : "interactive"}
                      className="h-full flex flex-col"
                    >
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
                            <span title="Request nie ma jawnie wybranego ownera TAC">
                              <Badge size="sm" variant="warning">
                                Brak ownera requestu
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
        </div>

        {/* ── Prawy dok: Gotowość zlecenia ───────────────────────────── */}
        <aside className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-4 xl:self-start">
          <JobReadinessDock
            jobId={effSelectedJobId}
            stageBreakdown={selectedListItem?.stage_breakdown}
          />
        </aside>
      </div>

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
