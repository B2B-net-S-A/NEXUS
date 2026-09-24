"use client";

import { pluralPl } from "@/lib/plural-pl";
import { useEffect, useMemo, useState } from "react";
import { TAC_UI_ENABLED } from "@/lib/tac-ui";
import {
  REQUEST_STATUS_FILTER_ORDER,
  REQUEST_STATUS_META,
  requestStatusOf,
  type RequestStatus,
} from "@/lib/request-status";
import { SimilarJobsDialog } from "@/components/v2/jobs/SimilarJobsDialog";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Briefcase,
  Building2,
  ChevronRight,
  DollarSign,
  Eye,
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
  X,
} from "lucide-react";
import api, { jobsApi } from "@/lib/api";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";
import { useCapabilities } from "@/hooks/useCapability";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
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
import {
  JobDeadlineCell,
  RequestStatusBadge,
  SimilarJobsCell,
  JobStageCounts,
  JobStageCountsHeader,
  STAGE_COUNTS_LEGEND,
} from "@/components/v2/jobs/JobListCells";
import { UserMultiSelect } from "@/components/v2/filters/UserMultiSelect";
import { ClientMultiSelect } from "@/components/v2/filters/ClientMultiSelect";
import { CompetenceCategoryMultiSelect } from "@/components/v2/filters/CompetenceCategoryMultiSelect";
import {
  JOB_STATUS_OPTIONS,
  type JobStatusValue,
} from "@/lib/filter-options";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";
import {
  deadlineQueryParams,
  defaultScopeForUser,
  defaultSortForScope,
  encodeJobsListUrl,
  initialDeadlineFromUrl,
  initialDeadlineRangeFromUrl,
  initialFlagFromUrl,
  initialIdsFromUrl,
  initialSentFromUrl,
  resolveScope,
  scopeOverrideFromUrl,
  scopeQueryFlags,
  sentQueryParams,
  initialPriorityWorkFromUrl,
  initialSearchFromUrl,
  sortOverrideFromUrl,
  initialStatusFromUrl,
  initialTypeFromUrl,
  type JobDeadlinePreset,
  type JobDeadlineRange,
  type JobScope,
  type JobSentFilterValue,
  type JobSortFilterValue,
  type JobTypeFilterValue,
} from "@/lib/jobs-url-filters";
import { extractSkills } from "@/lib/job-skills";
import { shortenPersonName } from "@/lib/job-header-subtitle";
import { stageSummaryOf } from "@/lib/job-pipeline-funnel";
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
type JobType = JobTypeFilterValue;

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

type DeadlinePreset = JobDeadlinePreset;

/** Od tej szerokości kolumna filtrów jest domyślnie rozwinięta (Tailwind `2xl`). */
const FILTERS_AUTO_EXPAND_QUERY = "(min-width: 1536px)";

type FiltersMode = "auto" | "expanded" | "collapsed";

/**
 * Siatka strony dla 3 stanów filtrów × 2 stanów doku. Pełne literały klas
 * (Tailwind nie widzi sklejanych) — `auto` przełącza się CSS-em na `2xl`.
 */
const LAYOUT_GRID: Record<FiltersMode, { closed: string; open: string }> = {
  // Trzy kolumny dopiero od `2xl`: przy 1280 px z przypiętym paskiem bocznym
  // tabela dostawała ~370 px. Na `xl` otwarty dok zajmuje miejsce filtrów
  // (patrz `FILTERS_ASIDE_VISIBILITY_WITH_DOCK`).
  expanded: {
    closed: "lg:grid-cols-[230px_minmax(0,1fr)]",
    open: "lg:grid-cols-[230px_minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[230px_minmax(0,1fr)_360px]",
  },
  collapsed: {
    closed: "",
    open: "xl:grid-cols-[minmax(0,1fr)_360px]",
  },
  // Tryb `auto` z otwartym dokiem CHOWA filtry: trzy kolumny na 1400 px
  // ucinały tabeli termin i akcje. Jawnie rozwinięte filtry zostają.
  auto: {
    closed: "2xl:grid-cols-[230px_minmax(0,1fr)]",
    open: "xl:grid-cols-[minmax(0,1fr)_360px]",
  },
};

const FILTERS_ASIDE_VISIBILITY: Record<FiltersMode, string> = {
  expanded: "",
  collapsed: "hidden",
  auto: "hidden 2xl:block",
};

const DEADLINE_OPTIONS: { value: DeadlinePreset; label: string }[] = [
  { value: "any", label: "Termin: dowolny" },
  { value: "overdue", label: "Po terminie" },
  { value: "this_week", label: "W tym tygodniu" },
  { value: "next7", label: "Najbliższe 7 dni" },
  { value: "next14", label: "Do 14 dni" },
  { value: "next30", label: "Najbliższe 30 dni" },
  { value: "has", label: "Z terminem" },
  { value: "none", label: "Bez terminu" },
  { value: "range", label: "Zakres dat…" },
];

/**
 * „Wysłanych do klienta" — OSOBY (nie wiersze etapów), które w rekrutacji
 * doszły do „CV wysłane" albo dalej (backend `min_sent`/`max_sent`).
 */
const SENT_OPTIONS: { value: JobSentFilterValue; label: string }[] = [
  { value: "any", label: "Wysłanych: dowolnie" },
  { value: "none", label: "Nikt jeszcze" },
  { value: "1", label: "Co najmniej 1 osoba" },
  { value: "3", label: "Co najmniej 3 osoby" },
  { value: "5", label: "Co najmniej 5 osób" },
];

// Bez `title` na przyciskach: w Chrome `title` potrafi przejąć nazwę dostępną
// przycisku, a nazwa ma zostać „Otwarte 318". Opis idzie w `aria-describedby`.
const SCOPE_OPTIONS: { value: JobScope; label: string; hint: string }[] = [
  { value: "mine", label: "Moje", hint: "Prowadzę albo współpracuję." },
  { value: "open", label: "Otwarte", hint: "Wszystkie poza zamkniętymi (otwarte i szkice)." },
  { value: "all", label: "Wszystkie", hint: "Cały rejestr, także zamknięte." },
];

type JobSortValue = JobSortFilterValue;
type PriorityWorkFilter = "any" | "assigned" | "carry_over" | "either";

const SORT_OPTIONS: { value: JobSortValue; label: string }[] = [
  // `sort=attention`: najpierw rekrutacje z największą liczbą kandydatów
  // czekających na ruch rekrutera (backend: `needs_action_count` DESC).
  { value: "attention", label: "Wymaga uwagi" },
  { value: "newest", label: "Od najnowszej" },
  { value: "oldest", label: "Od najstarszej" },
  // Termin rosnąco, bez terminu na końcu (backend `sort=deadline`).
  { value: "deadline", label: "Najbliższy termin" },
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

/**
 * Klucze react-query listy — eksportowane, żeby harness `/preview/jobs-list-v3`
 * zasiewał cache TYM SAMYM kluczem, którego używa komponent. Ręcznie przepisany
 * klucz rozjeżdża się przy pierwszym dołożonym filtrze, a niezasiany klucz
 * uruchamia `queryFn` → 401 → przerzut na /login.
 */
export interface JobsListQueryState {
  search: string;
  status: readonly JobStatusValue[];
  type: JobTypeFilterValue;
  mine: boolean;
  responsibleIds: readonly number[];
  clientIds: readonly number[];
  ccIds: readonly number[];
  needsSourcing: boolean;
  activeInSearch: boolean;
  deadline: JobDeadlinePreset;
  openOnly: boolean;
  noOwnerOnly: boolean;
  sort: JobSortFilterValue;
  priorityWork: "any" | "assigned" | "carry_over" | "either";
  page: number;
  /** Status requestu (0341) — pusty/brak = wszystkie. */
  requestStatuses?: readonly RequestStatus[];
  /** Granice presetu terminu `range` — brak = bez zakresu. */
  deadlineRange?: JobDeadlineRange;
  /** Delivery Lead rekrutacji (`delivery_lead_id`, LUB). */
  deliveryLeadIds?: readonly number[];
  /** „Wysłanych do klienta" — brak = dowolnie. */
  sent?: JobSentFilterValue;
}

export function jobsListQueryKey(state: JobsListQueryState): unknown[] {
  return [
    "jobs-v2",
    state.search,
    state.status,
    state.type,
    state.mine ? 1 : 0,
    state.responsibleIds,
    state.clientIds,
    state.ccIds,
    state.needsSourcing ? 1 : 0,
    state.activeInSearch ? 1 : 0,
    state.deadline,
    state.openOnly ? 1 : 0,
    state.noOwnerOnly ? 1 : 0,
    state.sort,
    state.priorityWork,
    state.page,
    state.requestStatuses ?? [],
    state.deadline === "range"
      ? [state.deadlineRange?.from ?? "", state.deadlineRange?.to ?? ""]
      : [],
    state.deliveryLeadIds ?? [],
    state.sent ?? "any",
  ];
}

/** Okno „Deadline ≤ 7 dni" liczy przeglądarka — ta sama para dat co filtr. */
export function jobsQuickCountsQueryKey(): unknown[] {
  const next7 = deadlineQueryParams("next7");
  return ["jobs-quick-counts", next7.deadline_from, next7.deadline_to];
}

/** Pigułka filtra w lewej kolumnie (makieta `.fp`) — Typ i Status. */
function FilterPill({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-background text-foreground hover:bg-accent",
      )}
    >
      {label}
    </button>
  );
}

/**
 * Wiersz w sekcji "Szybkie" lewej kolumny filtrów (makieta „01 Lista").
 *
 * `count` jest GLOBALNY — pochodzi z `GET /api/jobs/quick-counts`, który liczy
 * wszystkie sześć faset JEDNYM zapytaniem (`count(*) FILTER (WHERE …)`) tymi
 * samymi predykatami, co filtry listy. Do 09.2026 licznik miał tu tylko „Brak
 * ownera requestu" i opisywał WYŁĄCZNIE wczytaną stronę — „63" znaczyło „63
 * na dwudziestu widocznych wierszach", czyli liczbę, której nie dało się
 * zinterpretować.
 *
 * `count === undefined` (liczniki jeszcze się ładują albo ich zapytanie padło)
 * renderuje BRAK liczby, nie zero: zero jest zdaniem o bazie, a nie o tym, że
 * czegoś nie wiemy.
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
      {/* Etykieta ZAWIJA się zamiast ucinać: przy czterocyfrowym liczniku
          („Brak opiekuna TAC 4236") `truncate` zostawiał „Brak ownera req…",
          a to ta sama etykieta, po której użytkownik rozpoznaje filtr. */}
      <span className="min-w-0 flex-1 leading-snug">{label}</span>
      {count != null && (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {count}
        </span>
      )}
    </button>
  );
}

/**
 * Właściciel prowadzący w wierszu listy (makieta: `Marta K.` / `Nieprzypisany`).
 *
 * Świadomie NIE `OwnerBadge`: ten sam komponent rysuje właściciela w kafelkach,
 * na pulpicie i w nagłówku rekrutacji, a tutaj potrzebne są dwie rzeczy, które
 * tam byłyby regresją — skrócone nazwisko (wiersz ma jedną linię na osobę)
 * i **ton ostrzegawczy przy braku** (na liście „nieprzypisany" jest sprawą do
 * załatwienia, a nie neutralnym faktem: nikt nie dostanie alertów deadline'u).
 */
function JobOwnerCell({ user }: { user?: { name?: string | null } | null }) {
  const short = shortenPersonName(user?.name);
  if (!short) {
    return (
      <span
        className="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-warning"
        title="Rekrutacja nie ma właściciela prowadzącego — nikt nie dostanie alertów deadline'u"
      >
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        Nieprzypisany
      </span>
    );
  }
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5 text-xs text-foreground"
      title={user?.name ?? undefined}
    >
      <span
        aria-hidden="true"
        className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground"
      >
        {initialsOf(user?.name)}
      </span>
      <span className="truncate">{short}</span>
    </span>
  );
}

function initialsOf(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Compact table presentation of the jobs list (alternative to the tile grid). */
function JobsTable({
  items,
  previewId,
  onOpen,
  onPreview,
  onInvite,
  onSimilar,
}: {
  items: any[];
  /** Rekrutacja otwarta w doku podglądu — jej wiersz jest podświetlony. */
  previewId: number | null;
  /** Klik w wiersz OTWIERA rekrutację (rekrutacja v3); dok ma własną ikonę. */
  onOpen: (id: number, newTab: boolean) => void;
  onPreview: (id: number) => void;
  /** `undefined` = brak capability `invite_link.create` — nie renderujemy akcji. */
  onInvite?: (id: number) => void;
  /** Okno „Podobne rekrutacje" (0341) — plakietka pod tytułem. */
  onSimilar: (id: number) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {/* Lista v5 (24.09.2026): etapy = osiem kolumn Tablicy ze skrótami
              RAZ w nagłówku, „Podobne rekrutacje" jako plakietka pod tytułem.
              „Wymaga ruchu" i „W bazie" zdjęte decyzją Artura (22.09) —
              kolejność nadal daje sortowanie „Wymaga uwagi". */}
          {/* Telefon: tabela przewija się w poziomie (6 kolumn ≈ 850 px), więc
              kolumna „Rekrutacja" stoi przyklejona — bez niej po przewinięciu
              nie wiadomo, czyj to status i termin. */}
          <TableHead className="max-md:sticky max-md:left-0 max-md:z-20 max-md:bg-background">Rekrutacja</TableHead>
          <TableHead className="w-[150px]">Status</TableHead>
          <TableHead className="w-[250px] py-1.5" title={STAGE_COUNTS_LEGEND}>
            <span className="sr-only">Etapy</span>
            <JobStageCountsHeader />
          </TableHead>
          <TableHead className="w-[120px]">Termin</TableHead>
          <TableHead className="w-[120px]">Prowadzi</TableHead>
          <TableHead className="w-[64px]" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((job: any) => {
          // `stage_columns`/`stage_breakdown` przychodzą z
          // `GET /api/jobs?include_stage_counts=true` — JEDNO zapytanie GROUP BY
          // na całą stronę, zero zapytań per wiersz. Ich brak (odpowiedź spoza
          // kontraktu) cofa wiersz do paska `filled/target`, zamiast udawać
          // pełny lejek zerami. Grupuje ta sama funkcja co szyny w szczegółach
          // — jedna liczba pod jedną nazwą (UAT B33).
          const stageSummary = stageSummaryOf(job);
          const targetCount = job.headcount ?? 1;
          const filledCount = job.candidate_count ?? 0;
          const legacyProgress = Math.min(
            100,
            Math.round((filledCount / Math.max(1, targetCount)) * 100),
          );
          // `can_open === false` — ten sam kontrakt co kafelki: wiersz zostaje
          // czytelny, ale nie udaje klikalnego (detal zwróciłby 403).
          const locked = job.can_open === false;
          return (
            <TableRow
              key={job.id}
              interactive={!locked}
              selected={previewId === job.id}
              onClick={
                locked
                  ? undefined
                  : (e) => onOpen(job.id, e.metaKey || e.ctrlKey)
              }
              aria-disabled={locked || undefined}
              title={
                locked
                  ? "Nie masz dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu."
                  : undefined
              }
              className={locked ? "opacity-60" : undefined}
            >
              <TableCell className="max-w-[360px] max-md:sticky max-md:left-0 max-md:z-10 max-md:w-[200px] max-md:max-w-[200px] max-md:border-r max-md:border-border/60 max-md:bg-card">
                {/* `can_open === false` — ta sama reguła co kafelki: rekrutacja
                    jest w rejestrze, ale detal odpowie 403, więc tytuł nie
                    udaje linku (tabela do 09.2026 prowadziła prosto w ścianę). */}
                {job.can_open === false ? (
                  <span
                    aria-disabled="true"
                    title="Nie masz dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu."
                    className="line-clamp-2 break-words font-medium leading-snug text-muted-foreground"
                  >
                    {job.title}
                  </span>
                ) : (
                  // Dwie linie zamiast jednej (lista v5): tytuły z Traffita
                  // niosą klienta i technologię w nazwie, a ucięte do jednej
                  // linii wyglądały identycznie.
                  <Link
                    href={`/jobs/${job.id}`}
                    onClick={(e) => e.stopPropagation()}
                    title={job.title}
                    className="line-clamp-2 break-words font-medium leading-snug text-foreground hover:text-primary hover:underline"
                  >
                    {job.title}
                  </Link>
                )}
                <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-muted-foreground">
                  {job.client_name && (
                    <span className="inline-flex min-w-0 items-center gap-0.5" title="Klient">
                      <Building2 className="h-3 w-3 shrink-0" />
                      <span className="truncate">{job.client_name}</span>
                    </span>
                  )}
                  {job.reference_number && (
                    <span className="font-mono text-[10px]" title="Numer referencyjny">
                      {job.reference_number}
                    </span>
                  )}
                  {job.location && (
                    <span className="inline-flex min-w-0 items-center gap-0.5" title="Lokalizacja">
                      <MapPin className="h-3 w-3 shrink-0" />
                      <span className="truncate">{job.location}</span>
                    </span>
                  )}
                  <JobPriorityWorkBadges job={job} />
                  <SimilarJobsCell
                    similar={job.similar}
                    disabled={locked}
                    onOpen={() => onSimilar(job.id)}
                  />
                </div>
              </TableCell>
              <TableCell>
                <RequestStatusBadge status={job.request_status} />
              </TableCell>
              <TableCell>
                {stageSummary ? (
                  <JobStageCounts summary={stageSummary} />
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 min-w-[48px] flex-1 overflow-hidden rounded-full bg-border/60">
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
              <TableCell
                title={job.created_at ? `Dodano ${formatDate(job.created_at)}` : undefined}
              >
                <JobDeadlineCell deadline={job.deadline} />
              </TableCell>
              <TableCell>
                <JobOwnerCell user={job.primary_owner ?? null} />
              </TableCell>
              <TableCell>
                <div className="flex items-center justify-end gap-0.5">
                  {job.status === "published" && onInvite && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onInvite(job.id);
                      }}
                      className="p-1 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors pointer-coarse:p-2.5"
                      title="Wygeneruj link aplikacyjny"
                      aria-label="Wygeneruj link aplikacyjny"
                    >
                      <Link2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                  {/* Podgląd (dok gotowości) — osobna, dostępna z klawiatury
                      akcja; klik w wiersz otwiera rekrutację. Wiersz bez
                      dostępu nie ma podglądu: dok pytałby o detal → 403. */}
                  {!locked && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onPreview(job.id);
                      }}
                      aria-pressed={previewId === job.id}
                      className={cn(
                        "rounded-md p-1 transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:p-2.5",
                        previewId === job.id
                          ? "bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-primary/10 hover:text-primary",
                      )}
                      title="Podgląd"
                      aria-label={`Podgląd: ${job.title}`}
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <ChevronRight
                    className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60"
                    aria-hidden="true"
                  />
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function JobsListV2() {
  // Stan początkowy z URL-a. Bez tego deep-linki były atrapą: pulpit prowadzi
  // na `/jobs?mine=0&status=published`, a lista i tak startowała z pustymi
  // filtrami, więc użytkownik dostawał WSZYSTKIE oferty (z Draftami włącznie)
  // i nie miał sygnału, że kliknięty filtr nie zadziałał.
  //
  // Czytane raz, przy montowaniu. Status, „moje", typ, termin i sortowanie są
  // potem ZAPISYWANE z powrotem do URL-a (efekt niżej, M03-B01) — inaczej F5
  // i „Wstecz" z profilu rekrutacji gubiły zawężenie bez słowa.
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(() => initialSearchFromUrl(searchParams));
  const [statusFilter, setStatusFilter] = useState<JobStatusValue[]>(
    () => initialStatusFromUrl(searchParams)
  );
  const [typeFilter, setTypeFilter] = useState<JobType>(() =>
    initialTypeFromUrl(searchParams),
  );
  // Zakres i sortowanie trzymamy jako NADPISANIA (`null` = „bez wyboru"):
  // zakres obowiązujący to jawny wybór albo domyślny roli, a sortowanie bez
  // wyboru idzie za zakresem. Dzięki temu lista reaguje na hydratację store'u
  // (rola znana dopiero po mount) bez gubienia jawnego `mine=0/1` z adresu.
  const authUser = useAuthStore((s) => s.user);
  const authHydrated = useAuthStore((s) => s.hydrated);
  // Zakres: „Moje" | „Otwarte" | „Wszystkie" (lista v5). Role prowadzące
  // startują w „Moich", nadzorujące (admin, HoR, Finanse, viewer) —
  // w „Otwartych", nie w całym rejestrze z tysiącami zamkniętych.
  const defaultScope = defaultScopeForUser(authUser);
  const [scopeOverride, setScopeOverride] = useState<JobScope | null>(() =>
    scopeOverrideFromUrl(searchParams),
  );
  const scope = resolveScope(scopeOverride, authUser);
  const { mine, openOnly } = scopeQueryFlags(scope);
  const [responsibleIds, setResponsibleIds] = useState<number[]>(() =>
    initialIdsFromUrl(searchParams, "responsible"),
  );
  const [clientIds, setClientIds] = useState<number[]>(() =>
    initialIdsFromUrl(searchParams, "client"),
  );
  const [ccIds, setCcIds] = useState<number[]>(() =>
    initialIdsFromUrl(searchParams, "cc"),
  );
  const [needsSourcing, setNeedsSourcing] = useState(() =>
    initialFlagFromUrl(searchParams, "sourcing"),
  );
  const [activeInSearch, setActiveInSearch] = useState(() =>
    initialFlagFromUrl(searchParams, "active_search"),
  );
  const [deadlinePreset, setDeadlinePreset] = useState<DeadlinePreset>(() =>
    initialDeadlineFromUrl(searchParams),
  );
  const [deadlineRange, setDeadlineRange] = useState<JobDeadlineRange>(() =>
    initialDeadlineRangeFromUrl(searchParams),
  );
  const [deliveryLeadIds, setDeliveryLeadIds] = useState<number[]>(() =>
    initialIdsFromUrl(searchParams, "lead"),
  );
  const [sentFilter, setSentFilter] = useState<JobSentFilterValue>(() =>
    initialSentFromUrl(searchParams),
  );
  // "Brak opiekuna TAC" jako FILTR (nie tylko badge, makieta „01 Lista").
  // Od 09.2026 filtruje SERWER (`owner_missing` w `GET /api/jobs`, predykat
  // `tac_id IS NULL`). Wcześniej zawężał wyłącznie już wczytaną stronę, więc
  // „63" obok nazwy filtra opisywało dwadzieścia widocznych wierszy, a nie
  // bazę — i paginacja pokazywała strony, na których nie było czego zawężać.
  // Przy wyłączonej funkcji TAC stary link z `?no_owner=1` nie może zawężać
  // listy ukrytym filtrem, którego nie da się zobaczyć ani zdjąć.
  const [noOwnerOnly, setNoOwnerOnly] = useState(
    () => TAC_UI_ENABLED && initialFlagFromUrl(searchParams, "no_owner"),
  );
  const [sortOverride, setSort] = useState<JobSortValue | null>(() =>
    sortOverrideFromUrl(searchParams),
  );
  const sort: JobSortValue = sortOverride ?? defaultSortForScope(scope);
  const [priorityWorkFilter, setPriorityWorkFilter] =
    useState<PriorityWorkFilter>(() => initialPriorityWorkFromUrl(searchParams));
  const [page, setPage] = useState(1);
  // Status requestu (0341) — adres `rs=` (powtarzalny), jak pozostałe filtry.
  const [requestStatuses, setRequestStatuses] = useState<RequestStatus[]>(() =>
    searchParams
      .getAll("rs")
      .map(requestStatusOf)
      .filter((s): s is RequestStatus => s !== null),
  );
  const [similarForJob, setSimilarForJob] = useState<number | null>(null);
  const [inviteModalForJob, setInviteModalForJob] = useState<number | null>(null);
  // Dok podglądu (gotowość rekrutacji) otwiera ikona „Podgląd" w wierszu —
  // klik w wiersz OTWIERA rekrutację (rekrutacja v3). `null` = dok zamknięty,
  // lista ma pełną szerokość. Zaznaczenie liczone WZGLĘDEM widocznej listy
  // (patrz `effPreviewJobId` niżej): rekrutacja odfiltrowana albo spoza strony
  // zamyka dok, zamiast zostawić go bez podświetlonego wiersza.
  const [previewJobId, setPreviewJobId] = useState<number | null>(null);
  const router = useRouter();
  const jobsView = useUiStore((s) => s.jobsView);
  const setJobsView = useUiStore((s) => s.setJobsView);
  // Kolumna filtrów: `null` = brak wyboru → domyślne wg szerokości okna
  // (rozwinięta od `2xl`), liczone CSS-em, więc bez migotania przy hydracji.
  const filtersPref = useUiStore((s) => s.jobsFiltersCollapsed);
  const setFiltersCollapsed = useUiStore((s) => s.setJobsFiltersCollapsed);
  const [wideViewport, setWideViewport] = useState<boolean | null>(null);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(FILTERS_AUTO_EXPAND_QUERY);
    const sync = () => setWideViewport(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  // Lista v4: kolumna filtrów domyślnie ZWINIĘTA — codzienne zawężenia
  // (status, zakres, szukanie) stoją nad tabelą. Rozwinięcie zapamiętuje się.
  // `as FiltersMode`: tryb „auto" zostaje w typie dla gałęzi układu (dok).
  const filtersMode = (
    filtersPref === false ? "expanded" : "collapsed"
  ) as FiltersMode;
  // Sortowanie bez jawnego wyboru samo idzie za zakresem; jawnie wybrane
  // zostaje. `null` = powrót do domyślnego zakresu roli („Wyczyść").
  const changeScope = (nextScope: JobScope | null) => {
    setScopeOverride(nextScope);
    setPage(1);
  };

  // Do zapytania idzie wartość zdebouncowana, do inputa surowa — inaczej każde
  // naciśnięcie klawisza wysyłało request i przerzucało tabelę w stan ładowania.
  const debouncedSearch = useDebouncedValue(search, 300);

  // Filtry → URL. `replaceState`, nie `router.replace`: zmiana filtra nie jest
  // nawigacją (nie ma zostawiać wpisu w historii ani przebudowywać drzewa),
  // a stan i tak żyje w komponencie. Lustro `CandidatesListV2`.
  useEffect(() => {
    const qs = encodeJobsListUrl(
      {
        status: statusFilter,
        scope,
        defaultScope,
        type: typeFilter,
        deadline: deadlinePreset,
        deadlineRange,
        sort,
        q: debouncedSearch,
        responsibleIds,
        clientIds,
        ccIds,
        deliveryLeadIds,
        sent: sentFilter,
        needsSourcing,
        activeInSearch,
        noOwnerOnly,
        priorityWork: priorityWorkFilter,
      },
      new URLSearchParams(window.location.search),
    );
    const withStatus = new URLSearchParams(qs);
    withStatus.delete("rs");
    for (const s of requestStatuses) withStatus.append("rs", s);
    const qsFull = withStatus.toString();
    const target = qsFull
      ? `${window.location.pathname}?${qsFull}`
      : window.location.pathname;
    if (target !== `${window.location.pathname}${window.location.search}`) {
      window.history.replaceState(window.history.state, "", target);
    }
  }, [
    statusFilter,
    scope,
    defaultScope,
    typeFilter,
    deadlinePreset,
    deadlineRange,
    sort,
    debouncedSearch,
    responsibleIds,
    clientIds,
    ccIds,
    deliveryLeadIds,
    sentFilter,
    needsSourcing,
    activeInSearch,
    noOwnerOnly,
    priorityWorkFilter,
    requestStatuses,
  ]);

  const dl = deadlineQueryParams(deadlinePreset, deadlineRange);

  // Jeden rejestr capability dla nagłówka, pustego stanu i akcji w wierszach
  // (audyt F-19) — wcześniej gate'owany był tylko przycisk w nagłówku.
  const can = useCapabilities();
  const canCreateJob = can["job.create"];
  const canInvite = can["invite_link.create"];

  const {
    data,
    isLoading: queryLoading,
    isError,
    isSuccess,
    error,
    refetch,
  } = useQuery({
    // Domyślny zakres zależy od ROLI, a tę znamy dopiero po hydratacji store'u
    // — bez bramki rekruter strzelałby najpierw we „Wszystkie", potem w „Moje".
    enabled: authHydrated,
    queryKey: jobsListQueryKey({
      search: debouncedSearch,
      status: statusFilter,
      type: typeFilter,
      mine,
      responsibleIds,
      clientIds,
      ccIds,
      needsSourcing,
      activeInSearch,
      deadline: deadlinePreset,
      openOnly,
      noOwnerOnly,
      sort,
      priorityWork: priorityWorkFilter,
      page,
      requestStatuses,
      deadlineRange,
      deliveryLeadIds,
      sent: sentFilter,
    }),
    queryFn: () =>
      api
        .get("/api/jobs", {
          params: {
            q: debouncedSearch || undefined,
            status: statusFilter.length ? statusFilter : undefined,
            recruitment_type: typeFilter !== "all" ? typeFilter : undefined,
            mine: mine ? true : undefined,
            responsible_id: responsibleIds.length ? responsibleIds : undefined,
            delivery_lead_id: deliveryLeadIds.length ? deliveryLeadIds : undefined,
            client_id: clientIds.length ? clientIds : undefined,
            competence_category_id: ccIds.length ? ccIds : undefined,
            needs_sourcing: needsSourcing ? true : undefined,
            active_in_search: activeInSearch ? true : undefined,
            open_only: openOnly ? true : undefined,
            owner_missing: noOwnerOnly ? true : undefined,
            priority_work:
              priorityWorkFilter === "any" ? undefined : priorityWorkFilter,
            request_status: requestStatuses.length ? requestStatuses : undefined,
            sort,
            ...dl,
            ...sentQueryParams(sentFilter),
            page,
            // Osiem kolumn Tablicy w wierszu — JEDNO dodatkowe GROUP BY
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

  // Liczniki sześciu filtrów „Szybkie" — JEDNO zapytanie na całą kolumnę,
  // niezależne od stronicowania i od pozostałych filtrów (makieta „01 Lista").
  // Okno „≤ 7 dni" liczy PRZEGLĄDARKA i wysyła je do backendu, żeby licznik
  // i lista używały tej samej pary dat — serwer w innej strefie czasowej
  // potrafiłby wypaść o dzień inaczej.
  const next7 = deadlineQueryParams("next7");
  const { data: quickCounts } = useQuery({
    queryKey: jobsQuickCountsQueryKey(),
    queryFn: () =>
      jobsApi
        .quickCounts({
          deadline_from: next7.deadline_from,
          deadline_to: next7.deadline_to,
        })
        .then((r) => r.data),
    staleTime: 60_000,
  });

  const isLoading = queryLoading || !authHydrated;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Filtry są w całości serwerowe — lista pokazuje dokładnie to, co przyszło.
  const visibleItems = items;

  // Podgląd liczony względem WIDOCZNEJ listy i tylko dla wierszy, które da
  // się otworzyć (`can_open` per wiersz w `jobs.py`): dok strzela w
  // `GET /api/jobs/{id}`, więc wiersz bez dostępu kończyłby się 403.
  const effPreviewJobId: number | null = useMemo(() => {
    if (previewJobId == null) return null;
    const row = visibleItems.find((j: any) => j.id === previewJobId);
    return row && row.can_open !== false ? row.id : null;
  }, [previewJobId, visibleItems]);
  const previewListItem = visibleItems.find(
    (j: any) => j.id === effPreviewJobId,
  );
  const dockOpen = effPreviewJobId != null;
  // Poniżej `xl` dok jest nakładką — Esc ją zamyka jak każdy arkusz.
  useEffect(() => {
    if (!dockOpen || typeof window.matchMedia !== "function") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (window.matchMedia("(min-width: 1280px)").matches) return;
      setPreviewJobId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dockOpen]);

  // `undefined` = jeszcze nie wiemy (SSR / brak matchMedia) — nie zgadujemy
  // `aria-expanded`, układ i tak rozstrzyga CSS. W trybie `auto` otwarty dok
  // chowa filtry (patrz `LAYOUT_GRID`).
  const autoExpanded = (wide: boolean) => wide && !dockOpen;
  const filtersExpanded: boolean | undefined =
    filtersMode === "auto"
      ? wideViewport == null
        ? undefined
        : autoExpanded(wideViewport)
      : filtersMode === "expanded";
  const toggleFilters = () => {
    const expandedNow =
      filtersMode === "auto"
        ? typeof window.matchMedia === "function" &&
          autoExpanded(window.matchMedia(FILTERS_AUTO_EXPAND_QUERY).matches)
        : filtersMode === "expanded";
    setFiltersCollapsed(expandedNow);
  };


  // Nawigacja „N z M" w doku — strzałki przesuwają wybór po wierszach BIEŻĄCEJ
  // strony (makieta „01 Lista"). Świadomie nie przeskakują na kolejną stronę:
  // dok czyta `stage_breakdown` i `can_open` z wiersza, więc wyjście poza
  // wczytany zbiór zostawiłoby go bez danych, które ma pokazywać.
  const previewableItems = visibleItems.filter((j: any) => j.can_open !== false);
  const selectedIndex = previewableItems.findIndex(
    (j: any) => j.id === effPreviewJobId,
  );
  const listNav =
    selectedIndex >= 0 && previewableItems.length > 1
      ? {
          index: selectedIndex + 1,
          total: previewableItems.length,
          onPrev: () => {
            const prev = previewableItems[selectedIndex - 1];
            if (prev) setPreviewJobId(prev.id);
          },
          onNext: () => {
            const next = previewableItems[selectedIndex + 1];
            if (next) setPreviewJobId(next.id);
          },
        }
      : undefined;

  const openJob = (id: number, newTab: boolean) => {
    const href = `/jobs/${id}`;
    if (newTab) window.open(href, "_blank", "noopener");
    else router.push(href);
  };

  // „Wszystkie filtry N" (makieta `.allfilters`) — ile zawężeń jest czynnych.
  // Wyszukiwarka jest POZA tą liczbą: stoi we własnym wierszu narzędzi nad
  // listą i widać ją bez otwierania kolumny filtrów. ZAKRES („Moje" /
  // „Otwarte" / „Wszystkie") też: ma własny, zawsze widoczny przełącznik,
  // a zakres domyślny liczony jako filtr dawałby „Filtry (1)" na starcie.
  const activeFilterCount =
    (typeFilter !== "all" ? 1 : 0) +
    statusFilter.length +
    (sentFilter !== "any" ? 1 : 0) +
    deliveryLeadIds.length +
    (needsSourcing ? 1 : 0) +
    (activeInSearch ? 1 : 0) +
    (noOwnerOnly ? 1 : 0) +
    (deadlinePreset !== "any" ? 1 : 0) +
    (priorityWorkFilter !== "any" ? 1 : 0) +
    clientIds.length +
    ccIds.length +
    responsibleIds.length +
    requestStatuses.length;

  // „4 241 · pokazuję 12 moich" (makieta). Pierwsza liczba to ZAWSZE `total`
  // z API — czyli ile rekrutacji pasuje do filtrów, nie ile widać. Druga mówi,
  // co jest na ekranie, i tylko wtedy, gdy jest inna niż pierwsza: „20 z 20"
  // pod nagłówkiem „20" byłoby szumem.
  const listSummary = (() => {
    const totalLabel = total.toLocaleString("pl-PL");
    if (visibleItems.length === 0) return totalLabel;
    if (scope === "mine") {
      return `${totalLabel} · pokazuję ${visibleItems.length} moich`;
    }
    if (total > visibleItems.length) {
      return `${totalLabel} · pokazuję ${visibleItems.length} na stronie`;
    }
    return totalLabel;
  })();

  // 403/404/5xx NIE mogą renderować się jako „Brak ofert" (audyt F-20).
  // Celowo liczone z `items` SERWEROWYCH, nie `visibleItems` — filtr "Brak
  // ownera requestu" jest lokalny dla przeglądarki i nie może udawać, że
  // backend nie ma żadnych rekrutacji.
  // `isSuccess` obowiązkowe (kontrakt `lib/view-state.ts`): w przerwie między
  // ponowieniami react-query ma `isLoading=false`, `isError=false` i puste
  // `data` — bez tej flagi awaria renderowałaby się jako „Brak rekrutacji".
  const viewState = resolveViewState({
    isLoading,
    isError,
    isSuccess,
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
    setRequestStatuses([]);
    // „Wyczyść" wraca do domyślnego zakresu ROLI (`defaultMineForUser`).
    changeScope(null);
    setResponsibleIds([]);
    setClientIds([]);
    setCcIds([]);
    setNeedsSourcing(false);
    setActiveInSearch(false);
    setDeadlinePreset("any");
    setDeadlineRange({});
    setDeliveryLeadIds([]);
    setSentFilter("any");
    setPriorityWorkFilter("any");
    setNoOwnerOnly(false);
    setPage(1);
  };

  return (
    <div className="max-w-[1400px] mx-auto space-y-3">
      {/* Nagłówek kompaktowy (makieta „01 Lista", `.lhead`): jedna linia
          zamiast eyebrow + H1 + podpis w trzech wierszach. Lista rekrutacji
          jest ekranem SKANOWANYM — trzy wiersze tytułu zabierały pionową
          przestrzeń wierszom, dla których się tu przychodzi. */}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-lg font-semibold tracking-heading-tight text-foreground">
          Rekrutacje
        </h1>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {isLoading
            ? "Ładowanie…"
            : failed
              ? "Nie udało się pobrać listy"
              : listSummary}
        </p>
        <div className="ml-auto flex items-center gap-2">
          {/* Capability `job.create` = backendowy TacPlus (POST /api/jobs). */}
          {canCreateJob && (
            <Button size="sm" variant="primary" onClick={() => router.push("/jobs/new")} data-help="jobs.list.new">
              <Plus className="h-4 w-4" /> Nowa rekrutacja
            </Button>
          )}
        </div>
      </div>

      {/* Grid jak C2: lewa kolumna filtrów, środek, dok gotowości */}
      <div
        className={cn(
          "grid grid-cols-1 gap-4",
          LAYOUT_GRID[filtersMode][dockOpen ? "open" : "closed"],
        )}
      >
        {/* ── Lewa kolumna: filtry (zwijana, stan w `store/ui.ts`) ──── */}
        <aside
          id="jobs-filters-rail"
          aria-label="Filtry listy rekrutacji"
          className={cn(
            "space-y-4 self-start rounded-xl border border-border bg-card p-4",
            filtersMode === "auto" && dockOpen
              ? "hidden"
              : filtersMode === "expanded" && dockOpen
                ? "xl:hidden 2xl:block"
                : FILTERS_ASIDE_VISIBILITY[filtersMode],
          )}
        >
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
            {/* `role="group"` + nazwa: obie grupy pigułek mają pozycję
                „Wszystkie", więc bez tego dwa różne przyciski miałyby w tym
                samym widoku identyczną nazwę dostępną. */}
            <div
              className="flex flex-wrap gap-1"
              role="group"
              aria-label="Filtr: Typ"
            >
              {FILTER_TABS.map((tab) => (
                <FilterPill
                  key={tab.value}
                  active={typeFilter === tab.value}
                  onClick={() => {
                    setTypeFilter(tab.value);
                    setPage(1);
                  }}
                  label={tab.label}
                />
              ))}
            </div>
          </div>

          <div className="border-t border-border" />

          <div className="space-y-1">
            <div className="px-2 text-[11px] font-medium text-muted-foreground">
              Szybkie
            </div>
            {/* „Moje rekrutacje" i „Niezamknięte" zeszły do przełącznika
                zakresu nad tabelą (lista v5) — dwa przełączniki tego samego
                zawężenia rozjeżdżały się ze sobą. */}
            <QuickFilterRow
              active={needsSourcing}
              onClick={() => {
                setNeedsSourcing((p) => !p);
                setPage(1);
              }}
              label="Potrzebny search"
              count={quickCounts?.needs_sourcing}
              tone="warning"
              title="Wymagają sourcingu"
            />
            <QuickFilterRow
              active={activeInSearch}
              onClick={() => {
                setActiveInSearch((p) => !p);
                setPage(1);
              }}
              label="Aktywni w searchu"
              count={quickCounts?.active_in_search}
              title="Rekruter aktywnie szuka"
            />
            {TAC_UI_ENABLED && (
            <QuickFilterRow
              active={noOwnerOnly}
              onClick={() => {
                setNoOwnerOnly((p) => !p);
                setPage(1);
              }}
              label="Brak opiekuna TAC"
              count={quickCounts?.owner_missing}
              tone="danger"
              title="Bez opiekuna TAC"
            />
            )}
            <QuickFilterRow
              active={deadlinePreset === "next7"}
              onClick={() => {
                setDeadlinePreset((p) => (p === "next7" ? "any" : "next7"));
                setPage(1);
              }}
              label="Deadline ≤ 7 dni"
              count={quickCounts?.deadline_7d}
              tone="warning"
              title="Termin w ciągu 7 dni"
            />
          </div>

          <div className="border-t border-border" />

          {/* Status jako pigułki, nie select (makieta „01 Lista"). Trzy wartości
              `JobStatus` mieszczą się w rzędzie, a rozwijana lista chowała
              najczęstsze zawężenie listy za dodatkowym kliknięciem.
              Etykiety CELOWO te same, co plakietka statusu w wierszu
              (`STATUS_LABEL`) — pigułka „Szkic" nad wierszami opisanymi
              „Draft" kazałaby zgadywać, czy to na pewno ten sam stan. */}
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">Status</div>
            <div
              className="flex flex-wrap gap-1"
              role="group"
              aria-label="Filtr: Status"
            >
              <FilterPill
                active={statusFilter.length === 0}
                onClick={() => {
                  setStatusFilter([]);
                  setPage(1);
                }}
                label="Wszystkie"
              />
              {JOB_STATUS_OPTIONS.map((option) => (
                <FilterPill
                  key={option.value}
                  active={statusFilter.includes(option.value)}
                  onClick={() => {
                    setStatusFilter((previous) =>
                      previous.includes(option.value)
                        ? previous.filter((v) => v !== option.value)
                        : [...previous, option.value],
                    );
                    setPage(1);
                  }}
                  label={STATUS_LABEL[option.value] ?? option.label}
                />
              ))}
            </div>
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

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Delivery Lead
            </div>
            <UserMultiSelect
              value={deliveryLeadIds}
              onChange={(ids) => {
                setDeliveryLeadIds(ids);
                setPage(1);
              }}
              onlyRoles={["delivery_lead"]}
              placeholder="Dowolny"
              searchPlaceholder="Szukaj Delivery Leada…"
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
              <SelectTrigger className="h-9 w-full font-medium" aria-label="Filtr: Termin">
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
            {deadlinePreset === "range" && (
              <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="w-5 shrink-0">Od</span>
                  <Input
                    type="date"
                    value={deadlineRange.from ?? ""}
                    max={deadlineRange.to}
                    onChange={(e) => {
                      setDeadlineRange((r) => ({ ...r, from: e.target.value || undefined }));
                      setPage(1);
                    }}
                    aria-label="Termin od"
                    className="h-8 min-w-0 flex-1 px-2 text-xs"
                  />
                </label>
                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="w-5 shrink-0">Do</span>
                  <Input
                    type="date"
                    value={deadlineRange.to ?? ""}
                    min={deadlineRange.from}
                    onChange={(e) => {
                      setDeadlineRange((r) => ({ ...r, to: e.target.value || undefined }));
                      setPage(1);
                    }}
                    aria-label="Termin do"
                    className="h-8 min-w-0 flex-1 px-2 text-xs"
                  />
                </label>
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
              Wysłanych do klienta
            </div>
            <Select
              value={sentFilter}
              onValueChange={(v) => {
                setSentFilter(v as JobSentFilterValue);
                setPage(1);
              }}
            >
              <SelectTrigger
                className="h-9 w-full font-medium"
                aria-label="Filtr: Wysłanych do klienta"
                title="Osoby, które w tej rekrutacji doszły do „CV wysłane” albo dalej"
              >
                <SelectValue placeholder="Wysłanych: dowolnie" />
              </SelectTrigger>
              <SelectContent>
                {SENT_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Licznik czynnych zawężeń (makieta `.allfilters`). Kolumna jest
              długa i przewijana razem ze stroną — bez tej liczby łatwo
              patrzeć na wynik zawężony filtrem, którego nie widać na ekranie. */}
          <div
            className="flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-border px-2 py-1.5 text-[11px] text-muted-foreground"
            aria-live="polite"
          >
            <SlidersHorizontal className="h-3 w-3" aria-hidden="true" />
            Wszystkie filtry
            <span className="font-semibold text-primary tabular-nums">
              {activeFilterCount}
            </span>
          </div>

          {/* Ta sama akcja co w nagłówku (makieta ma ją w obu miejscach) —
              po przescrollowaniu długiej kolumny filtrów przycisk z nagłówka
              jest już poza ekranem. */}
          {canCreateJob && (
            <Button
              size="sm"
              variant="outline"
              className="w-full"
              onClick={() => router.push("/jobs/new")}
            >
              <Plus className="h-4 w-4" /> Nowa rekrutacja
            </Button>
          )}
        </aside>

        {/* ── Środek: wyszukiwarka, sortowanie, lista/kafelki ───────── */}
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={toggleFilters}
              aria-expanded={filtersExpanded}
              aria-controls="jobs-filters-rail"
              data-help="jobs.list.filters"
              className="h-9"
            >
              <SlidersHorizontal className="h-4 w-4" />
              Filtry
              {activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
            </Button>
            {/* Zakres: domyślny zależy od roli („Moje" albo „Otwarte"); jawny
                wybór żyje w adresie (`mine=1` / `open=1` / `mine=0`). Liczniki
                są GLOBALNE (`/api/jobs/quick-counts`), a ich brak to brak
                liczby, nie zero. */}
            <div
              className="flex items-center overflow-hidden rounded-md border border-border"
              role="group"
              aria-label="Zakres rekrutacji"
              data-help="jobs.list.scope"
            >
              {SCOPE_OPTIONS.map((option) => {
                const count =
                  option.value === "mine"
                    ? quickCounts?.mine
                    : option.value === "open"
                      ? quickCounts?.open
                      : quickCounts?.all;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => changeScope(option.value)}
                    aria-pressed={scope === option.value}
                    aria-describedby={`jobs-scope-hint-${option.value}`}
                    className={cn(
                      "flex h-9 items-center gap-1.5 px-3 text-sm transition-colors",
                      scope === option.value
                        ? "bg-primary font-medium text-primary-foreground"
                        : "text-muted-foreground hover:bg-primary/10",
                    )}
                  >
                    {option.label}
                    {count != null && (
                      <span className="text-xs tabular-nums opacity-80">
                        {count.toLocaleString("pl-PL")}
                      </span>
                    )}
                  </button>
                );
              })}
              {SCOPE_OPTIONS.map((option) => (
                <span
                  key={option.value}
                  id={`jobs-scope-hint-${option.value}`}
                  className="sr-only"
                >
                  {option.hint}
                </span>
              ))}
            </div>
            <div className="min-w-[240px] max-w-lg flex-1" data-help="jobs.list.search">
              <Input
                leadingIcon={<Search className="h-4 w-4" />}
                placeholder="Tytuł, klient, technologia…"
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
              <SelectTrigger className="h-9 w-[170px] font-medium" data-help="jobs.list.sort">
                <SelectValue placeholder="Sortowanie" />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* Przełącznik widoku zjechał z nagłówka do wiersza narzędzi
                (makieta `.tools .rt`) — stoi przy sortowaniu, czyli przy
                pozostałych decyzjach o TYM, JAK oglądać wyniki, a nie przy
                akcji tworzącej nową rekrutację. */}
            <div
              className="ml-auto flex items-center overflow-hidden rounded-md border border-border"
              role="group"
              aria-label="Widok rekrutacji"
            >
              <button
                type="button"
                onClick={() => setJobsView("list")}
                title="Widok listy"
                aria-pressed={jobsView === "list"}
                className={cn(
                  "flex h-9 w-9 items-center justify-center transition-colors",
                  jobsView === "list"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-primary/10",
                )}
              >
                <List className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setJobsView("tiles")}
                title="Widok kafelków"
                aria-pressed={jobsView === "tiles"}
                className={cn(
                  "flex h-9 w-9 items-center justify-center transition-colors",
                  jobsView === "tiles"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-primary/10",
                )}
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Status requestu (0341) — codzienne zawężenie, zawsze na wierzchu.
              Klik przełącza; kilka naraz = LUB (serwer: `request_status`). */}
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label="Status requestu"
            data-help="jobs.list.status"
          >
            <span className="mr-1 text-xs text-muted-foreground">Status:</span>
            {REQUEST_STATUS_FILTER_ORDER.map((value) => {
              const on = requestStatuses.includes(value);
              // Liczba z `/quick-counts` tym samym wyrażeniem co filtr: w „Moich"
              // — moje, poza nimi — cały rejestr (statusy z tej listy dotyczą
              // wyłącznie niezamkniętych, więc to zarazem liczba „Otwartych").
              const statusCounts =
                scope === "mine"
                  ? quickCounts?.request_status_mine
                  : quickCounts?.request_status;
              const count = statusCounts?.[value];
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={on}
                  title={REQUEST_STATUS_META[value].hint}
                  onClick={() => {
                    setRequestStatuses((prev) =>
                      on ? prev.filter((s) => s !== value) : [...prev, value],
                    );
                    setPage(1);
                  }}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors",
                    on
                      ? "border-primary/40 bg-primary/10 font-semibold text-primary"
                      : "border-border text-muted-foreground hover:bg-muted",
                  )}
                >
                  {REQUEST_STATUS_META[value].label}
                  {count != null && (
                    <span
                      className={cn(
                        "tabular-nums",
                        on ? "text-primary" : "text-muted-foreground/80",
                      )}
                    >
                      {count.toLocaleString("pl-PL")}
                    </span>
                  )}
                </button>
              );
            })}
            {(() => {
              const withSuggestions = visibleItems.filter(
                (j: any) => j.similar?.suggested && j.can_open !== false,
              ).length;
              return withSuggestions > 0 ? (
                <span className="ml-auto inline-flex items-center gap-1 rounded-md border border-dashed border-primary/40 px-2 py-1 text-xs font-medium text-primary">
                  ≈ {withSuggestions}{" "}
                  {pluralPl(withSuggestions, "rekrutacja", "rekrutacje", "rekrutacji")}
                  {/* Liczone z wierszy na ekranie — przy wielu stronach mówimy to
                      wprost, inaczej liczba wyglądała na sumę całej listy. */}
                  {total > visibleItems.length ? " na tej stronie" : ""}{" "}
                  {pluralPl(withSuggestions, "ma", "mają", "ma")} podobne z osobami u klienta — przepnij je
                </span>
              ) : null;
            })()}
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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
              {/* Pustka POD filtrem to inna wiadomość niż pusta baza —
                  „Utwórz pierwszą" pod aktywnym zawężeniem sugeruje, że
                  w systemie nie ma żadnej rekrutacji. */}
              {scope !== "all" && activeFilterCount === 0 && !debouncedSearch ? (
                // Pusty zakres to nie pusta baza — osoba bez własnych
                // rekrutacji nie może zobaczyć tu „Brak rekrutacji".
                <p className="text-sm text-muted-foreground">
                  {scope === "mine"
                    ? "Nie prowadzisz teraz żadnej rekrutacji."
                    : "Nie ma otwartych rekrutacji."}{" "}
                  <button
                    type="button"
                    onClick={() => changeScope("all")}
                    className="text-primary hover:underline"
                  >
                    Pokaż wszystkie
                  </button>
                  .
                </p>
              ) : activeFilterCount > 0 || debouncedSearch ? (
                <p className="text-sm text-muted-foreground">
                  Żadna rekrutacja nie pasuje do filtrów.{" "}
                  <button
                    type="button"
                    onClick={() => {
                      resetFilters();
                      setSearch("");
                    }}
                    className="text-primary hover:underline"
                  >
                    Wyczyść filtry
                  </button>
                  .
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Brak rekrutacji.{" "}
                  {canCreateJob && (
                    <>
                      <button
                        onClick={() => router.push("/jobs/new")}
                        className="text-primary hover:underline"
                      >
                        Utwórz pierwszą
                      </button>
                      .
                    </>
                  )}
                </p>
              )}
            </div>
          ) : jobsView === "list" ? (
            <JobsTable
              items={visibleItems}
              previewId={effPreviewJobId}
              onOpen={openJob}
              onPreview={(id) =>
                setPreviewJobId((current) => (current === id ? null : id))
              }
              onInvite={canInvite ? (id) => setInviteModalForJob(id) : undefined}
              onSimilar={(id) => setSimilarForJob(id)}
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {visibleItems.map((job: any) => {
                const skills = extractSkills(job.must_skills);
                const statusVariant = STATUS_VARIANT[job.status] ?? "neutral";
                const statusLabel = STATUS_LABEL[job.status] ?? job.status;
                // Te same klucze co w wierszu listy wyżej: `GET /api/jobs`
                // zwraca `candidate_count` (`list_jobs` w `jobs.py`) i
                // `headcount` (`JobResponse`). Do 09.2026 kafelek czytał
                // `candidates_count`/`filled_count`/`target_positions` — pól,
                // których odpowiedź nigdy nie miała — więc pasek „Kandydaci"
                // pokazywał na produkcji zawsze 0/N, niezależnie od pipeline'u.
                const filledCount = job.candidate_count ?? 0;
                const targetCount = job.headcount ?? 1;
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
                      {/* `flex-wrap` + `min-w-[160px]`: w środkowej kolumnie
                          układu C2 kafelek jest wąski, a plakietki statusu
                          (`shrink-0`) wypychały tytuł (`flex-1 min-w-0`) do
                          zerowej szerokości — tytuł znikał z kafelka. */}
                      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-[160px] flex-1">
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
                              className="p-1 rounded-md text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors pointer-coarse:p-2.5"
                              title="Wygeneruj link aplikacyjny"
                              aria-label="Wygeneruj link aplikacyjny"
                            >
                              <Link2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                          {job.can_open !== false && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                setPreviewJobId((current) =>
                                  current === job.id ? null : job.id,
                                );
                              }}
                              aria-pressed={effPreviewJobId === job.id}
                              className={cn(
                                "rounded-md p-1 transition-colors pointer-coarse:p-2.5",
                                effPreviewJobId === job.id
                                  ? "bg-primary/10 text-primary"
                                  : "text-muted-foreground hover:bg-primary/10 hover:text-primary",
                              )}
                              title="Podgląd"
                              aria-label={`Podgląd: ${job.title}`}
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </button>
                          )}
                          <Badge size="sm" variant={statusVariant}>
                            {statusLabel}
                          </Badge>
                          {TAC_UI_ENABLED && job.tac_id == null && (
                            <span title="Rekrutacja nie ma jawnie wybranego opiekuna TAC">
                              <Badge size="sm" variant="warning">
                                Brak opiekuna TAC
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
                            <div className="flex-1 h-1.5 rounded-full bg-border/60 overflow-hidden">
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

        {/* ── Prawy dok: podgląd gotowości — otwiera go ikona „Podgląd" ──
            Od `xl` dok jest kolumną siatki. Węziej siatka jest jednokolumnowa,
            więc dok stałby POD całą listą i klik „Podgląd" nie dawałby
            widocznego efektu — tam dok wysuwa się z prawej jak arkusz. */}
        {dockOpen && (
          <div
            aria-hidden="true"
            data-testid="jobs-preview-backdrop"
            className="fixed inset-0 z-40 bg-card/50 backdrop-blur-[2px] xl:hidden"
            onClick={() => setPreviewJobId(null)}
          />
        )}
        {dockOpen && (
          <aside
            aria-label="Podgląd rekrutacji"
            className={cn(
              "space-y-2",
              "fixed inset-y-0 right-0 z-50 w-full overflow-y-auto border-l border-border bg-background p-4 shadow-xl sm:max-w-[420px]",
              "xl:inset-auto xl:z-auto xl:w-auto xl:max-w-none xl:overflow-visible xl:border-0 xl:bg-transparent xl:p-0 xl:shadow-none",
              "xl:sticky xl:top-4 xl:self-start",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-xs font-medium text-muted-foreground">
                Podgląd: {previewListItem?.title}
              </span>
              <button
                type="button"
                onClick={() => setPreviewJobId(null)}
                aria-label="Zamknij podgląd"
                title="Zamknij podgląd"
                className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:p-2.5"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <JobReadinessDock
              jobId={effPreviewJobId}
              stageBreakdown={stageSummaryOf(previewListItem)}
              canOpen={previewListItem?.can_open !== false}
              listNav={listNav}
            />
          </aside>
        )}
      </div>


      {similarForJob !== null && (
        <SimilarJobsDialog
          jobId={similarForJob}
          open
          onOpenChange={(v) => {
            if (!v) setSimilarForJob(null);
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
