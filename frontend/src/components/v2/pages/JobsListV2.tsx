"use client";

import { pluralPl } from "@/lib/plural-pl";
import { useEffect, useMemo, useState } from "react";
import {
  REQUEST_STAGE_CHIPS,
  REQUEST_STAGE_META,
  initialStagesFromUrl,
  type RequestStage,
} from "@/lib/request-stage";
import { jobsActiveFilterCount } from "@/lib/jobs-filter-groups";
import {
  JobsFilterBar,
  type JobsFilterBarValue,
} from "@/components/v2/jobs/JobsFilterBar";
import { SimilarJobsDialog } from "@/components/v2/jobs/SimilarJobsDialog";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Briefcase,
  Building2,
  ChevronRight,
  Eye,
  Link2,
  Plus,
  Search,
  X,
} from "lucide-react";
import api, { jobsApi } from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";
import { useCapabilities } from "@/hooks/useCapability";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { JobPreviewDetails } from "@/components/v2/jobs/JobPreviewDetails";
import { JobReadinessDock } from "@/components/v2/jobs/JobReadinessDock";
import {
  JobCategoryShortBadge,
  JobDeadlineCell,
  JobRecruiterCell,
  RequestStageBadge,
  SimilarJobsIconButton,
  JobStageCounts,
  JobStageCountsHeader,
  STAGE_COUNTS_LEGEND,
  jobOpenedDate,
} from "@/components/v2/jobs/JobListCells";
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";
import { priorityLevelOf, type PriorityLevel } from "@/lib/request-priority";
import { hasRole, useAuthStore } from "@/store/auth";
import {
  JOB_SCOPE_VALUES,
  deadlineQueryParams,
  defaultScopeForUser,
  defaultSortForScope,
  effectiveScopeOverride,
  encodeJobsListUrl,
  initialDeadlineFromUrl,
  initialDeadlineRangeFromUrl,
  initialFlagFromUrl,
  initialIdsFromUrl,
  initialOpenedRangeFromUrl,
  initialPriorityLevelsFromUrl,
  initialSearchFromUrl,
  initialSentFromUrl,
  openedQueryParams,
  resolveScope,
  scopeOverrideFromUrl,
  scopeQueryFlags,
  sentQueryParams,
  sortOverrideFromUrl,
  type CategoryScopeState,
  type JobDeadlinePreset,
  type JobDeadlineRange,
  type JobOpenedRange,
  type JobScope,
  type JobSentFilterValue,
  type JobSortFilterValue,
} from "@/lib/jobs-url-filters";
import { jobDisplayTitle } from "@/lib/job-names";
import { jobRowTitle, jobWorkModeParts } from "@/lib/job-row-summary";
import { stageSummaryOf } from "@/lib/job-pipeline-funnel";
import { WIDE_TABLE_CONTAINER } from "@/lib/wide-table";
import type {
  PriorityChannel,
  PriorityRank,
} from "@/lib/priority-work-api";

// Bez `title` na przyciskach: w Chrome `title` potrafi przejąć nazwę dostępną
// przycisku, a nazwa ma zostać „Otwarte 318". Opis idzie w `aria-describedby`.
const SCOPE_META: Record<JobScope, { label: string; hint: string }> = {
  mine: { label: "Moje", hint: "Jestem Rekruterem albo Delivery Leadem." },
  // Tylko widok: rekrutacje z mojej kategorii kompetencji, które mogę wziąć.
  // Opcja jest na przełączniku wyłącznie u osoby, która ma kategorię.
  category: {
    label: "Moja kategoria",
    hint: "Niezamknięte rekrutacje z mojej kategorii kompetencji — do wzięcia, niekoniecznie moje.",
  },
  open: { label: "Otwarte", hint: "Wszystkie poza zamkniętymi (otwarte i szkice)." },
  all: { label: "Wszystkie", hint: "Cały rejestr, także zamknięte." },
};

type JobSortValue = JobSortFilterValue;

const SORT_OPTIONS: { value: JobSortValue; label: string }[] = [
  // `sort=attention`: najpierw rekrutacje z największą liczbą kandydatów
  // czekających na ruch rekrutera (backend: `needs_action_count` DESC).
  { value: "attention", label: "Wymaga uwagi" },
  { value: "newest", label: "Od najnowszej" },
  { value: "oldest", label: "Od najstarszej" },
  // Termin rosnąco, bez terminu na końcu (backend `sort=deadline`).
  { value: "deadline", label: "Najbliższy termin" },
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

const EMPTY_FILTERS: JobsFilterBarValue = {
  clientIds: [],
  deliveryLeadIds: [],
  workedBy: [],
  nobodyWorking: false,
  ccIds: [],
  deadline: "any",
  deadlineRange: {},
  sent: "any",
  priorityLevels: [],
  openedRange: {},
};

/**
 * Klucze react-query listy — eksportowane, żeby harness `/preview/jobs-list-v3`
 * zasiewał cache TYM SAMYM kluczem, którego używa komponent. Ręcznie przepisany
 * klucz rozjeżdża się przy pierwszym dołożonym filtrze, a niezasiany klucz
 * uruchamia `queryFn` → 401 → przerzut na /login.
 */
export interface JobsListQueryState {
  search: string;
  mine: boolean;
  /** Zakres „Moja kategoria” (`my_category=true`) — idzie bez `mine` i `open_only`. */
  myCategory?: boolean;
  openOnly: boolean;
  sort: JobSortFilterValue;
  page: number;
  /** Pigułki „Stan requestu” (`request_stage`, LUB) — pusty = wszystkie. */
  stages: readonly RequestStage[];
  clientIds: readonly number[];
  ccIds: readonly number[];
  /** Delivery Lead rekrutacji (`delivery_lead_id`, LUB). */
  deliveryLeadIds: readonly number[];
  /** „Rekruter” — id osób (`worked_by`, LUB). */
  workedBy: readonly number[];
  /** „Bez rekrutera” (`nobody_working=true`). */
  nobodyWorking: boolean;
  deadline: JobDeadlinePreset;
  /** Granice presetu terminu `range` — brak = bez zakresu. */
  deadlineRange?: JobDeadlineRange;
  /** „Wysłanych do klienta" — brak = dowolnie. */
  sent?: JobSentFilterValue;
  /** „Priorytet” (`priority_level`, LUB) — pusty = dowolny. */
  priorityLevels?: readonly PriorityLevel[];
  /** „Data otwarcia” (`opened_from` / `opened_to`). */
  openedRange?: JobOpenedRange;
}

export function jobsListQueryKey(state: JobsListQueryState): unknown[] {
  return [
    "jobs-v2",
    state.search,
    state.mine ? 1 : 0,
    state.openOnly ? 1 : 0,
    state.sort,
    state.page,
    state.stages,
    state.clientIds,
    state.ccIds,
    state.deliveryLeadIds,
    state.workedBy,
    state.nobodyWorking ? 1 : 0,
    state.deadline,
    state.deadline === "range"
      ? [state.deadlineRange?.from ?? "", state.deadlineRange?.to ?? ""]
      : [],
    state.sent ?? "any",
    state.myCategory ? 1 : 0,
    state.priorityLevels ?? [],
    // Daty, które NAPRAWDĘ idą do serwera: odwrócony albo niedokończony
    // zakres nie zmienia klucza, więc lista nie migocze w trakcie wpisywania.
    openedKey(state.openedRange),
  ];
}

function openedKey(range: JobOpenedRange | undefined): string[] {
  const sent = openedQueryParams(range);
  return [sent.opened_from ?? "", sent.opened_to ?? ""];
}

/**
 * Liczniki pigułek i przełączników. Okno „Po terminie” (termin do wczoraj)
 * liczy przeglądarka — ta sama data co filtr, żeby licznik i lista się zgadzały.
 */
export function jobsQuickCountsQueryKey(): unknown[] {
  return ["jobs-quick-counts", deadlineQueryParams("overdue").deadline_to];
}

// Laptop (tabela poniżej 1100 px): węższe odstępy w krótkich kolumnach, żeby
// lista mieściła się w oknie 1280 px bez poziomego przewijania (pomiar
// 02.10.2026: 11 px ponad szerokość przy rozwiniętym menu).
const NARROW_CELL = "@max-[1099px]:px-2";

/** Tabela listy rekrutacji — jedyny widok (kafelki usunięte 02.10.2026). */
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
  /** Okno „Podobne rekrutacje" (0341) — ikona w kolumnie akcji. */
  onSimilar: (id: number) => void;
}) {
  return (
    // Jeden układ dla każdej szerokości (02.10.2026): wiersz to nazwa stanowiska,
    // a pod nią kategoria, klient i tryb pracy. Wymagania, nazwa od klienta,
    // numery i data otwarcia stoją w Podglądzie (`JobPreviewDetails`).
    // `@container` zostaje dla `NARROW_CELL`.
    <div className={WIDE_TABLE_CONTAINER}>
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {/* Telefon: tabela przewija się w poziomie, więc kolumna „Rekrutacja"
              stoi przyklejona — bez niej po przewinięciu nie wiadomo, czyj to
              status i termin. */}
          <TableHead className="max-md:sticky max-md:left-0 max-md:z-20 max-md:bg-background">Rekrutacja</TableHead>
          <TableHead className={cn("w-[136px]", NARROW_CELL)}>Status</TableHead>
          <TableHead className="w-[244px] px-2 py-1.5" title={STAGE_COUNTS_LEGEND}>
            <span className="sr-only">Etapy</span>
            <JobStageCountsHeader />
          </TableHead>
          <TableHead className={cn("w-[108px]", NARROW_CELL)}>Termin</TableHead>
          {/* Delivery Lead stoi drobnym drukiem pod osobami — bez własnej kolumny. */}
          <TableHead className={cn("w-[120px]", NARROW_CELL)}>Rekruter</TableHead>
          <TableHead className={cn("w-[96px]", NARROW_CELL)} />
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
          // `can_open === false`: rejestr pokazuje tę rekrutację (jest świadomie
          // ogólnofirmowy), ale detal odpowie 403. Wiersz zostaje
          // czytelny, ale nie udaje klikalnego (detal zwróciłby 403).
          const locked = job.can_open === false;
          const workMode = jobWorkModeParts(job);
          const opened = jobOpenedDate(job);
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
              {/* `md:w-full md:max-w-0`: kolumna bierze resztę szerokości, a długa
                  nazwa przycina się wielokropkiem zamiast rozpychać tabelę.
                  Minimum 200 px: z otwartym Podglądem na laptopie tabela
                  przewija się w poziomie, zamiast ściskać nazwę do kilku liter. */}
              <TableCell className="overflow-hidden md:w-full md:min-w-[200px] md:max-w-0 max-md:sticky max-md:left-0 max-md:z-10 max-md:w-[200px] max-md:max-w-[200px] max-md:border-r max-md:border-border/60 max-md:bg-card">
                {/* Priorytet stoi przy tytule (P2 nie ma plakietki), bez
                    osobnej kolumny. */}
                <div className="flex min-w-0 items-center gap-1.5">
                <RequestPriorityChip level={priorityLevelOf(job)} className="shrink-0" />
                {/* Pełny tytuł roboczy w dymku stoi na opakowaniu: `title` na
                    samym linku przejąłby w Chrome jego nazwę dostępną. */}
                <span className="block min-w-0 truncate" title={jobDisplayTitle(job)}>
                {/* `can_open === false`: rekrutacja
                    jest w rejestrze, ale detal odpowie 403, więc tytuł nie
                    udaje linku (tabela do 09.2026 prowadziła prosto w ścianę). */}
                {job.can_open === false ? (
                  <span
                    aria-disabled="true"
                    title="Nie masz dostępu do tej rekrutacji — poproś o dodanie Cię do jej zespołu."
                    className="font-medium leading-snug text-muted-foreground"
                  >
                    {jobRowTitle(job)}
                  </span>
                ) : (
                  <Link
                    href={`/jobs/${job.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="font-medium leading-snug text-foreground hover:text-primary hover:underline"
                  >
                    {jobRowTitle(job)}
                  </Link>
                )}
                </span>
                </div>
                <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <JobCategoryShortBadge categoryId={job.competence_category_id} />
                  {job.client_name && (
                    <span
                      className="inline-flex min-w-0 items-center gap-1"
                      title={`Klient: ${job.client_name}`}
                      data-testid="job-row-client"
                    >
                      <Building2 className="h-3 w-3 shrink-0" />
                      <span className="truncate">{job.client_name}</span>
                    </span>
                  )}
                  {/* Gdy brakuje miejsca, najpierw przycina się miasto, potem
                      klient; nazwa trybu zostaje cała. */}
                  {(workMode.mode || workMode.city) && (
                    <>
                      {job.client_name && <span aria-hidden="true">·</span>}
                      <span className="contents" data-testid="job-row-work-mode">
                        {workMode.mode && (
                          <span
                            className="shrink-0 whitespace-nowrap"
                            title={`Tryb pracy: ${[workMode.mode, workMode.city].filter(Boolean).join(" · ")}`}
                          >
                            {workMode.mode}
                          </span>
                        )}{" "}
                        {workMode.city && (
                          <span
                            className="min-w-0 shrink-[1000] truncate"
                            title={`Miasto: ${workMode.city}`}
                          >
                            {workMode.mode ? "· " : ""}
                            {workMode.city}
                          </span>
                        )}
                      </span>
                    </>
                  )}
                </div>
              </TableCell>
              <TableCell className={NARROW_CELL}>
                <RequestStageBadge
                  stage={job.request_stage}
                  fallbackStatus={job.request_status}
                />
              </TableCell>
              <TableCell className="px-2">
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
              {/* Dymek: data otwarcia, a bez niej data dodania — ta sama
                  (`opened_effective_at`), po której filtruje „Data otwarcia”. */}
              <TableCell
                className={NARROW_CELL}
                title={opened ? `Otwarta ${formatDate(opened)}` : undefined}
              >
                <JobDeadlineCell deadline={job.deadline} deadlineTime={job.deadline_time} />
              </TableCell>
              <TableCell className={NARROW_CELL}>
                <JobRecruiterCell job={job} />
              </TableCell>
              <TableCell className={NARROW_CELL}>
                <div className="flex items-center justify-end gap-0.5">
                  <SimilarJobsIconButton
                    similar={job.similar}
                    disabled={locked}
                    onOpen={() => onSimilar(job.id)}
                  />
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
    </div>
  );
}

export function JobsListV2() {
  // Stan początkowy z URL-a, czytany raz przy montowaniu, a potem ZAPISYWANY
  // z powrotem (efekt niżej) — F5 i „Wstecz" z profilu rekrutacji nie gubią
  // zawężenia. Klucze kolumny filtrów sprzed 25.09.2026 (typ, status, osoba
  // odpowiedzialna, „Szybkie”, Priority Work, `rs`/`ws`) nie są już filtrem:
  // `rs`/`ws` mapują się na pigułki stanu, reszta znika z adresu.
  const searchParams = useSearchParams();
  const [search, setSearch] = useState(() => initialSearchFromUrl(searchParams));
  // Zakres i sortowanie trzymamy jako NADPISANIA (`null` = „bez wyboru"):
  // zakres obowiązujący to jawny wybór albo domyślny roli, a sortowanie bez
  // wyboru idzie za zakresem. Dzięki temu lista reaguje na hydratację store'u
  // (rola znana dopiero po mount) bez gubienia jawnego `mine=0/1` z adresu.
  const authUser = useAuthStore((s) => s.user);
  const authHydrated = useAuthStore((s) => s.hydrated);

  // Liczniki zakresu, pigułek stanu i trzech przełączników — JEDNO zapytanie
  // (`/api/jobs/quick-counts`, marker parytetu „quick-counts”), niezależne od
  // stronicowania i od pozostałych filtrów. Datę „Po terminie” liczy
  // PRZEGLĄDARKA — ta sama, którą dostaje filtr terminu. Stoi przed zakresem,
  // bo to z liczników wiadomo, czy osoba ma kategorię („Moja kategoria”).
  const overdueTo = deadlineQueryParams("overdue").deadline_to;
  const { data: quickCounts, isPending: quickCountsPending } = useQuery({
    queryKey: jobsQuickCountsQueryKey(),
    queryFn: () => jobsApi.quickCounts({ overdue_to: overdueTo }).then((r) => r.data),
    staleTime: 60_000,
  });
  // Liczba = osoba ma kategorię kompetencji; `null` albo brak pola = nie ma.
  const categoryCount =
    typeof quickCounts?.my_category === "number" ? quickCounts.my_category : null;
  const categoryState: CategoryScopeState =
    categoryCount !== null ? "available" : quickCountsPending ? "pending" : "unavailable";

  // Zakres: „Moje" | „Moja kategoria" | „Otwarte" | „Wszystkie". Role
  // prowadzące startują w „Moich", nadzorujące (admin, HoR, Finanse, viewer) —
  // w „Otwartych", nie w całym rejestrze z tysiącami zamkniętych.
  const defaultScope = defaultScopeForUser(authUser);
  const [scopeChoice, setScopeChoice] = useState<JobScope | null>(() =>
    scopeOverrideFromUrl(searchParams),
  );
  // `?mycat=1` u osoby bez kategorii = brak wyboru (zakres domyślny roli).
  const scopeOverride = effectiveScopeOverride(scopeChoice, categoryState);
  const scope = resolveScope(scopeOverride, authUser);
  // Wejście z `?mycat=1`, zanim przyszły liczniki: jeszcze nie wiadomo, czy
  // ten zakres w ogóle obowiązuje — lista czeka, zamiast pytać dwa razy.
  const scopePending = scopeChoice === "category" && categoryState === "pending";
  const { mine, myCategory, openOnly } = scopeQueryFlags(scope);
  const [stages, setStages] = useState<RequestStage[]>(() =>
    initialStagesFromUrl(searchParams),
  );
  const [filterValue, setFilterValue] = useState<JobsFilterBarValue>(() => ({
    clientIds: initialIdsFromUrl(searchParams, "client"),
    deliveryLeadIds: initialIdsFromUrl(searchParams, "lead"),
    workedBy: initialIdsFromUrl(searchParams, "who"),
    nobodyWorking: initialFlagFromUrl(searchParams, "nobody"),
    ccIds: initialIdsFromUrl(searchParams, "cc"),
    deadline: initialDeadlineFromUrl(searchParams),
    deadlineRange: initialDeadlineRangeFromUrl(searchParams),
    sent: initialSentFromUrl(searchParams),
    priorityLevels: initialPriorityLevelsFromUrl(searchParams),
    openedRange: initialOpenedRangeFromUrl(searchParams),
  }));
  const [sortOverride, setSort] = useState<JobSortValue | null>(() =>
    sortOverrideFromUrl(searchParams),
  );
  const sort: JobSortValue = sortOverride ?? defaultSortForScope(scope);
  const [page, setPage] = useState(1);
  const patchFilters = (patch: Partial<JobsFilterBarValue>) => {
    setFilterValue((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };
  const [similarForJob, setSimilarForJob] = useState<number | null>(null);
  const [inviteModalForJob, setInviteModalForJob] = useState<number | null>(null);
  // Dok podglądu (gotowość rekrutacji) otwiera ikona „Podgląd" w wierszu —
  // klik w wiersz OTWIERA rekrutację (rekrutacja v3). `null` = dok zamknięty,
  // lista ma pełną szerokość. Zaznaczenie liczone WZGLĘDEM widocznej listy
  // (patrz `effPreviewJobId` niżej): rekrutacja odfiltrowana albo spoza strony
  // zamyka dok, zamiast zostawić go bez podświetlonego wiersza.
  const [previewJobId, setPreviewJobId] = useState<number | null>(null);
  const router = useRouter();
  // Sortowanie bez jawnego wyboru samo idzie za zakresem; jawnie wybrane
  // zostaje. `null` = powrót do domyślnego zakresu roli („Wyczyść").
  const changeScope = (nextScope: JobScope | null) => {
    setScopeChoice(nextScope);
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
        scope,
        defaultScope,
        deadline: filterValue.deadline,
        deadlineRange: filterValue.deadlineRange,
        sort,
        q: debouncedSearch,
        stages,
        clientIds: filterValue.clientIds,
        ccIds: filterValue.ccIds,
        deliveryLeadIds: filterValue.deliveryLeadIds,
        workedBy: filterValue.workedBy,
        nobodyWorking: filterValue.nobodyWorking,
        sent: filterValue.sent,
        priorityLevels: filterValue.priorityLevels,
        openedRange: filterValue.openedRange,
      },
      new URLSearchParams(window.location.search),
    );
    const target = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    if (target !== `${window.location.pathname}${window.location.search}`) {
      window.history.replaceState(window.history.state, "", target);
    }
  }, [scope, defaultScope, sort, debouncedSearch, stages, filterValue]);

  // Runda 10 (R10-N15-12): „Rekrutacje” z menu na przefiltrowanej liście to
  // miękka nawigacja na goły `/jobs` — komponent zostaje, a stan filtrów
  // czytany był tylko przy montowaniu. Goły adres = ta sama lista co po F5
  // (lustro `CandidatesListV2`). Własne zapisy adresu dają goły adres tylko
  // przy stanie domyślnym, więc reset jest wtedy bez skutku.
  const routeQuery = searchParams?.toString() ?? "";
  const [seenRouteQuery, setSeenRouteQuery] = useState(routeQuery);
  if (routeQuery !== seenRouteQuery) {
    setSeenRouteQuery(routeQuery);
    if (routeQuery === "") {
      setSearch("");
      setScopeChoice(null);
      setStages([]);
      setFilterValue(EMPTY_FILTERS);
      setSort(null);
      setPage(1);
    }
  }

  const dl =deadlineQueryParams(filterValue.deadline, filterValue.deadlineRange);

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
    enabled: authHydrated && !scopePending,
    queryKey: jobsListQueryKey({
      search: debouncedSearch,
      mine,
      myCategory,
      openOnly,
      sort,
      page,
      stages,
      clientIds: filterValue.clientIds,
      ccIds: filterValue.ccIds,
      deliveryLeadIds: filterValue.deliveryLeadIds,
      workedBy: filterValue.workedBy,
      nobodyWorking: filterValue.nobodyWorking,
      deadline: filterValue.deadline,
      deadlineRange: filterValue.deadlineRange,
      sent: filterValue.sent,
      priorityLevels: filterValue.priorityLevels,
      openedRange: filterValue.openedRange,
    }),
    queryFn: () =>
      api
        .get("/api/jobs", {
          params: {
            q: debouncedSearch || undefined,
            mine: mine ? true : undefined,
            // „Moja kategoria” idzie sama — serwer sam pomija zamknięte.
            my_category: myCategory ? true : undefined,
            open_only: openOnly ? true : undefined,
            request_stage: stages.length ? stages : undefined,
            client_id: filterValue.clientIds.length ? filterValue.clientIds : undefined,
            competence_category_id: filterValue.ccIds.length ? filterValue.ccIds : undefined,
            delivery_lead_id: filterValue.deliveryLeadIds.length
              ? filterValue.deliveryLeadIds
              : undefined,
            worked_by: filterValue.workedBy.length ? filterValue.workedBy : undefined,
            nobody_working: filterValue.nobodyWorking ? true : undefined,
            priority_level: filterValue.priorityLevels.length
              ? filterValue.priorityLevels
              : undefined,
            sort,
            ...dl,
            ...sentQueryParams(filterValue.sent),
            // Odwrócony zakres nie idzie wcale (serwer odpowiada 422).
            ...openedQueryParams(filterValue.openedRange),
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

  // Liczby przełączników i pigułek stanu są policzone dla „Moich” i dla
  // rejestru. „Wszystkie” nie ma liczb przełączników (objęłyby archiwum),
  // a „Moja kategoria” nie ma żadnych: serwer liczy dla niej tylko zakres,
  // a liczby całego rejestru pod jej nagłówkiem byłyby nieprawdą.
  const attentionCounts =
    scope === "mine"
      ? quickCounts?.attention_mine
      : scope === "open"
        ? quickCounts?.attention
        : undefined;
  const stageCounts =
    scope === "mine"
      ? quickCounts?.request_stage_mine
      : scope === "category"
        ? undefined
        : quickCounts?.request_stage;
  const scopeCounts: Record<JobScope, number | null | undefined> = {
    mine: quickCounts?.mine,
    category: categoryCount,
    open: quickCounts?.open,
    all: quickCounts?.all,
  };
  // „Moja kategoria” jest na przełączniku tylko u osoby, która ma kategorię.
  const scopeOptions = JOB_SCOPE_VALUES.filter(
    (value) => value !== "category" || categoryState === "available",
  );

  const isLoading = queryLoading || !authHydrated || scopePending;
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

  // Ile zawężeń jest ustawionych (pusty stan „Brak wyników dla filtrów”
  // i „Wyczyść filtry (N)”). Zakres i szukajka poza liczbą — widać je zawsze.
  const activeFilterCount = jobsActiveFilterCount({ ...filterValue, stages });

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
    setStages([]);
    // „Wyczyść" wraca do domyślnego zakresu ROLI.
    changeScope(null);
    setFilterValue(EMPTY_FILTERS);
    setPage(1);
  };

  // Baner przepięć stoi w rzędzie „Stan requestu” od 1536 px; na węższym
  // oknie (laptop z Windows, 150%) spychał się tam do osobnej linii, więc
  // poniżej 1536 px stoi w rzędzie tytułu, gdzie jest wolne miejsce.
  const similarWithSuggestions = visibleItems.filter(
    (j: any) => j.similar?.suggested && j.can_open !== false,
  ).length;
  const similarBanner = (className: string, short = false) => {
    if (similarWithSuggestions === 0) return null;
    const onPage = total > visibleItems.length ? " na tej stronie" : "";
    // Liczone z wierszy na ekranie — przy wielu stronach mówimy to wprost,
    // inaczej liczba wyglądała na sumę całej listy.
    const full = `≈ ${similarWithSuggestions} ${pluralPl(similarWithSuggestions, "rekrutacja", "rekrutacje", "rekrutacji")}${onPage} ${pluralPl(similarWithSuggestions, "ma", "mają", "ma")} podobne z osobami u klienta — przepnij je`;
    return (
      <span
        className={cn(
          "items-center gap-1 rounded-md border border-dashed border-primary/40 px-2 py-1 text-xs font-medium text-primary",
          className,
        )}
        title={short ? full : undefined}
      >
        {/* Poniżej 1536 px w rzędzie tytułu krótko — pełne zdanie łamało
            ten rząd na dwie linie (produkcja 29.09.2026). */}
        {short ? `≈ ${similarWithSuggestions} z podobnymi — przepnij` : full}
      </span>
    );
  };

  return (
    // `pb-24`: maskotka Jarvisa w prawym dolnym rogu zasłaniała ikony akcji
    // ostatnich wierszy — lista musi dać się przewinąć nad nią (audyt 24.09.2026).
    <div className="space-y-3 pb-24" data-testid="jobs-list-page">
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
        {similarBanner("inline-flex 2xl:hidden", true)}
        <div className="ml-auto flex items-center gap-2">
          {/* Stany requestów ustawia DL (lustro bramki strony i API
              `request_work_states`) — bez tego linku ekran był osiągalny
              wyłącznie z kafelka pulpitu, którego nikt jeszcze nie miał. */}
          {hasRole(authUser, "admin", "delivery_lead", "head_of_recruitment") && (
            <Button size="sm" variant="outline" asChild>
              <Link href="/jobs/review-states">Porządek w requestach</Link>
            </Button>
          )}
          {/* Capability `job.create` = backendowy TacPlus (POST /api/jobs). */}
          {canCreateJob && (
            <Button size="sm" variant="primary" onClick={() => router.push("/jobs/new")} data-help="jobs.list.new">
              <Plus className="h-4 w-4" /> Nowa rekrutacja
            </Button>
          )}
        </div>
      </div>

      {/* Lista + dok gotowości. Filtry stoją paskiem nad tabelą (25.09.2026)
          — lewa kolumna zabierała tabeli 230 px i znikała przy otwartym doku. */}
      <div
        className={cn(
          "grid grid-cols-1 gap-4",
          dockOpen && "xl:grid-cols-[minmax(0,1fr)_360px]",
        )}
      >
        {/* ── Środek: wyszukiwarka, sortowanie, lista ───────── */}
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {/* Zakres: domyślny zależy od roli („Moje" albo „Otwarte"); jawny
                wybór żyje w adresie (`mine=1` / `open=1` / `mine=0`). Liczniki
                są GLOBALNE (`/api/jobs/quick-counts`), a ich brak to brak
                liczby, nie zero. */}
            {/* Cztery pozycje z licznikami nie mieszczą się w 328 px telefonu —
                tam przełącznik łamie się na dwa rzędy, zamiast rozpychać stronę. */}
            <div
              className="relative flex flex-wrap items-center overflow-hidden rounded-md border border-border"
              role="group"
              aria-label="Zakres rekrutacji"
              data-help="jobs.list.scope"
            >
              {scopeOptions.map((value) => {
                const count = scopeCounts[value];
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => changeScope(value)}
                    aria-pressed={scope === value}
                    aria-describedby={`jobs-scope-hint-${value}`}
                    className={cn(
                      "flex h-9 grow items-center justify-center gap-1.5 whitespace-nowrap px-3 text-sm transition-colors",
                      scope === value
                        ? "bg-primary font-medium text-primary-foreground"
                        : "text-muted-foreground hover:bg-primary/10",
                    )}
                  >
                    {SCOPE_META[value].label}
                    {count != null && (
                      <span className="text-xs tabular-nums opacity-80">
                        {count.toLocaleString("pl-PL")}
                      </span>
                    )}
                  </button>
                );
              })}
              {scopeOptions.map((value) => (
                <span key={value} id={`jobs-scope-hint-${value}`} className="sr-only">
                  {SCOPE_META[value].hint}
                </span>
              ))}
            </div>
            {/* Minimum 160 px: przy ~910 px listy (okno 1280 px, przypięte menu,
                pasek otwartych kart i pasek przewijania Windows) cały rząd
                narzędzi z czterema zakresami zostaje w jednej linii. */}
            <div className="min-w-[160px] max-w-lg flex-1" data-help="jobs.list.search">
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
          </div>

          {/* Stan requestu (25.09.2026) — JEDEN rząd zamiast „Status:” i „Praca:”.
              Serwer liczy jedną wartość na rekrutację (`request_stage`), więc
              kilka pigułek naraz to LUB. Liczby z `/quick-counts` tym samym
              wyrażeniem: w „Moich” — moje, poza nimi — cały rejestr (pigułki
              dotyczą wyłącznie niezamkniętych, więc to zarazem „Otwarte”). */}
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label="Stan requestu"
            data-help="jobs.list.status"
          >
            <span className="mr-1 text-xs text-muted-foreground">Stan requestu</span>
            {REQUEST_STAGE_CHIPS.map((value) => {
              const on = stages.includes(value);
              const count = stageCounts?.[value];
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={on}
                  title={REQUEST_STAGE_META[value].hint}
                  onClick={() => {
                    setStages((prev) =>
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
                  {REQUEST_STAGE_META[value].label}
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
            {similarBanner("hidden 2xl:ml-auto 2xl:inline-flex")}
          </div>

          <JobsFilterBar
            value={filterValue}
            onPatch={patchFilters}
            meId={authUser?.id ?? null}
            attention={attentionCounts}
            activeCount={activeFilterCount}
            canClear={activeFilterCount > 0 || scopeOverride !== null}
            onClearAll={resetFilters}
          />

          {/* Wyniki — tabela (widok kafelków usunięty 02.10.2026) */}
          {isLoading ? (
            <div className="rounded-lg border border-border bg-card divide-y divide-border/60">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-12 flex items-center px-4 animate-pulse">
                  <div className="h-3 bg-[hsl(var(--border))] rounded w-1/3" />
                </div>
              ))}
            </div>
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
                    ? "Nie masz teraz żadnej otwartej rekrutacji."
                    : scope === "category"
                      ? "W Twojej kategorii nie ma teraz otwartych rekrutacji."
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
          ) : (
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
              listDetails={
                previewListItem ? (
                  <JobPreviewDetails
                    job={previewListItem}
                    onSimilar={() => setSimilarForJob(previewListItem.id)}
                    extra={<JobPriorityWorkBadges job={previewListItem} />}
                  />
                ) : null
              }
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
