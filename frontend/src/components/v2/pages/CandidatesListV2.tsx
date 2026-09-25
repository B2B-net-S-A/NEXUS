"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ChevronDown,
  ChevronRight,
  Columns3,
  Download,
  FileArchive,
  FileText,
  History,
  Link as LinkIcon,
  Lock,
  Plus,
  Search,
  Sparkles,
  Upload,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import api, { savedSearchesApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { useToast } from "@/components/Toast";
import {
  BulkCvDownloadError,
  downloadBulkCvs,
} from "@/lib/bulk-cv-download";
import {
  buildCandidateExportRequest,
  downloadCandidateExport,
  type CandidateExportScope,
} from "@/lib/candidate-export";
import { filtersFromCandidateSavedSearch } from "@/lib/candidate-saved-search";
import { cn } from "@/lib/utils";
import { AddCandidateModal } from "@/components/AppShell";
import { ImportCandidatesV2 } from "@/components/v2/modals/ImportCandidatesV2";
import { AddCandidateFromCVModal } from "@/components/v2/modals/AddCandidateFromCVModal";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { CandidateQuickView } from "@/components/v2/pages/CandidateQuickView";
import {
  fetchCandidateListPage,
  getCandidateListIncludeFlags,
  getCandidateListViewState,
} from "@/components/v2/pages/candidate-list-query";
import { useCandidateSearchDebounce } from "@/hooks/useCandidateSearchDebounce";
import {
  carryImmediate,
  filterChangeCount,
  isBareListQuery,
  listSearchKeywords,
  listSearchLabel,
  resolveInitialListParams,
  sameCriteria,
} from "@/lib/candidate-list-staging";
import {
  clearJobSearch,
  clearListSearch,
  pushRecentSearch,
  readJobSearch,
  readListSearch,
  writeJobSearch,
  writeListSearch,
} from "@/lib/search-memory";
import { RecentSearchesMenu } from "@/components/v2/filters/RecentSearchesMenu";
import {
  FieldSnippets,
  MAX_FIELD_SNIPPETS,
  MatchSnippet,
  type FieldSnippet,
} from "@/components/v2/MatchSnippet";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { CANDIDATES_PAGE_SIZES, useUiStore, type CandidatesPageSize } from "@/store/ui";
import {
  CANDIDATE_JOB_SEARCH_PREFS_KEY,
  CANDIDATE_TABLE_PREFS_KEY,
  candidateGridLayout,
  selectableCandidateColumns,
  toggleCandidateColumn,
  visibleCandidateColumns,
} from "@/lib/candidate-table-columns";
import { useVisibleMatchScores } from "@/hooks/useVisibleMatchScores";
import { scoreBadgeClass } from "@/lib/match-score-badge";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { CandidateCvCell } from "@/components/v2/candidates/CandidateCvCell";
import { CandidatePhoneCell } from "@/components/v2/candidates/CandidatePhoneCell";
import { CandidateProcessCell } from "@/components/v2/candidates/CandidateProcessCell";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AvailabilityStatus, EmploymentInfo } from "@/components/v2/CandidateHighlights";
import { useAuthStore, hasRole, type UserRole } from "@/store/auth";
import { ActiveFilterChips } from "@/components/v2/filters/ActiveFilterChips";
import type { StageFilterValue } from "@/components/v2/filters/StageFilterPanel";
import {
  AddToRecruitmentDialog,
  addToRecruitmentSummary,
} from "@/components/v2/recruitment/AddToRecruitmentDialog";
import type { OpenToValue } from "@/lib/filter-options";
import {
  DEFAULT_FILTERS,
  decodeFilters,
  decodeSelectedIds,
  decodeSkillsExpr,
  effectiveSort,
  matchSortAvailable,
  encodeCompareHref,
  encodeFilterCriteria,
  encodeFilters,
  encodeNavContext,
  filtersEqual,
  filtersToApiParams,
  parseRateBound,
  parseYearBound,
  pickTraffitExtras,
  pickTraffitExtrasPatch,
  type TraffitExtraFilters,
  type AvailabilityFilter,
  type CandidateFilters,
  type CandidateStatusFilter,
  type EmploymentFilter,
  type PipelineStageFilter,
  type RecruitmentMatch,
  type RecentlyChangedJobs,
  type TextModeFilter,
} from "@/lib/url-filters";
import { classifyKeywords, mayBeSkillList } from "@/lib/keyword-suggest";
import {
  countSkillConstraints,
  parseSkillExpression,
  serializeSkillBuckets,
} from "@/lib/skill-expression";
import { looksLikePastedRequest, type SkillBucketsValue } from "@/lib/candidate-search-semantics";
import { ContactStatusBadge } from "@/components/candidate-contact/ContactStatusBadge";
import type { CandidateContactSummary } from "@/lib/candidate-contact";
import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import {
  candidateRowTestId,
  focusCandidateRow,
  formatCandidateLocation,
  getCandidateInitials,
  getCurrentCompany,
  getCurrentTitle,
  isRowActivationKey,
} from "@/components/v2/pages/candidate-list-helpers";
import { PinnedCandidatesBar } from "@/components/v2/filters/PinnedCandidatesBar";
import { SavedSearchesMenu } from "@/components/v2/filters/SavedSearchesMenu";
import type { SearchTextInterpretation } from "@/lib/candidate-search-api";
import { CandidateFilterBar } from "@/components/v2/candidates/CandidateFilterBar";
import { isChipShownOnFilterBar } from "@/lib/candidate-filter-groups";
import {
  ListSearchInterpretation,
  type ListTextModeApplied,
} from "@/components/v2/candidates/ListSearchInterpretation";
import { CandidateBulkBar } from "@/components/v2/candidates/CandidateBulkBar";
import { RequestSearchDialog } from "@/components/v2/candidates/RequestSearchDialog";
import {
  availabilityCellText,
  candidatesCountLabel,
  rateCellText,
} from "@/components/v2/candidates/candidate-row-format";
import type { TalentRadarInitialRequest } from "@/components/talent-radar/TalentRadarWorkspace";

/** Role z prawem eksportu (lustro `CANDIDATE_EXPORT_ROLES` w candidate_access.py). */
const EXPORT_ROLES: UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "finance",
];

/** Tylko „W procesie" potrzebuje wzbogacenia (aktywne rekrutacje). */
const LIST_COLUMN_IDS: ReadonlySet<string> = new Set(["process"]);
const ROW_HEIGHT = 64;
/** Wysokość nagłówka kolumn (`h-10`) — przesunięcie wierszy w kontenerze przewijania. */
const LIST_HEADER_HEIGHT = 40;

const SORT_LABELS: Record<CandidateFilters["sort"], string> = {
  relevance: "Trafność",
  newest: "Najnowsi",
  oldest: "Najstarsi",
  // Backend sortuje po NAZWISKU, potem imieniu, bez polskich znaków.
  name: "Nazwisko A–Z",
  // Podobieństwo do wierszy wymagań; w „Szukaj ręcznie” — do rekrutacji
  // (`sortLabel`). Backend: `services/candidate_match_order.py`.
  match: "Dopasowanie do wymagań",
};

function sortLabel(value: CandidateFilters["sort"], inRecruitment: boolean): string {
  return value === "match" && inRecruitment ? "Dopasowanie do rekrutacji" : SORT_LABELS[value];
}

// Deterministyczna kolorystyka awatara wg ID kandydata (ten sam kandydat =
// ten sam kolor między odświeżeniami).
const AVATAR_COLOR_CLASSES = [
  "bg-primary/10 text-primary ring-1 ring-primary/20",
  "bg-info-muted text-info-muted-foreground ring-1 ring-info/20",
  "bg-success-muted text-success-muted-foreground ring-1 ring-success/20",
  "bg-warning-muted text-warning-muted-foreground ring-1 ring-warning/20",
  "bg-accent text-accent-foreground ring-1 ring-border",
  "bg-secondary text-secondary-foreground ring-1 ring-border",
];

function avatarColorClass(id: number): string {
  return AVATAR_COLOR_CLASSES[Math.abs(id) % AVATAR_COLOR_CLASSES.length];
}

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
  status?: "active" | "passive" | "blacklisted";
  availability_status?: AvailabilityStatus;
  availability_date?: string | null;
  notice_period?: number | null;
  notice_period_unit?: "days" | "weeks" | "months" | null;
  employment?: EmploymentInfo;
  location?: string;
  city?: string | null;
  competence_category?: string | null;
  competence_category_id?: number | null;
  skills?: unknown;
  experience?: unknown;
  linkedin_current_company?: string | null;
  linkedin_current_title?: string | null;
  last_contacted_at?: string | null;
  years_it_experience?: number | null;
  /** Nazwa pliku głównego CV — kolumna „CV” (podgląd po kliknięciu). */
  cv_filename?: string | null;
  /** Czy jest zapisany dokument CV — to on decyduje o przycisku podglądu. */
  has_cv_document?: boolean | null;
  created_at?: string;
  updated_at?: string;
  match_snippet?: string | null;
  /** v2: każde pole z trafieniem słowa kluczowego (z zakresami pogrubień). */
  match_snippets?: FieldSnippet[] | null;
  active_recruitments?: Array<{
    job_id: number;
    job_title: string;
    client_name?: string | null;
    stage: string;
    moved_at?: string | null;
    moved_by_name?: string | null;
  }> | null;
  expected_rate_hourly?: number | string | null;
  expected_rate_currency?: string | null;
  contact_case?: CandidateContactSummary | null;
  /** Semantyka v2: filtry przejście wyłącznie przez brak danych. */
  unknown_fields?: string[];
}

interface CandidateListResponse {
  items: Candidate[];
  total: number;
  page: number;
  page_size: number;
  /** Jak lista odczytała `q` (dosłownie / po znaczeniu / brak tekstu). */
  text_mode_applied?: ListTextModeApplied | null;
  interpretation?: SearchTextInterpretation | null;
  /** Wyszukiwanie po znaczeniu nie odpowiedziało — wynik jest dosłowny. */
  search_degraded?: boolean;
  /** Pula wyników po znaczeniu jest przycięta. */
  result_cap_reached?: boolean;
  /** Kolejność faktycznie użyta (przy braku wektorów „match” → „newest”). */
  sort_applied?: string | null;
}

/**
 * Parametry `GET /api/candidates` dla strony listy — jedno źródło dla
 * komponentu i harnessu `/preview/candidates-list` (zasiew cache musi trafić
 * w dokładnie ten klucz).
 */
export function candidatesListApiParams(
  filters: CandidateFilters,
  page: number,
  pageSize: number,
): Record<string, unknown> {
  const { includeMatchStats, includeActiveRecruitments, includeLastActivity } =
    getCandidateListIncludeFlags("list", LIST_COLUMN_IDS);
  return filtersToApiParams(filters, page, {
    page_size: pageSize,
    include_match_stats: includeMatchStats || undefined,
    include_active_recruitments: includeActiveRecruitments,
    include_last_activity: includeLastActivity || undefined,
  });
}

export function candidatesListQueryKey(params: Record<string, unknown>) {
  return ["candidates-v2", params] as const;
}

/** Liczba całej bazy do nagłówka — jedno tanie zapytanie o 1 wiersz. */
export const CANDIDATES_BASE_TOTAL_QUERY_KEY = ["candidates-v2", "base-total"] as const;
const CANDIDATES_BASE_TOTAL_PARAMS = { page: 1, page_size: 1, semantics_version: 2 };

/** „22.09.2026” albo `null` dla braku / nieczytelnej daty. */
function formatShortDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return null;
  return new Date(ts).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** Wyszarzone „brak" — brak danych nie może wyglądać jak wartość. */
function Missing() {
  return <span className="text-xs text-muted-foreground/80">brak</span>;
}

/**
 * Dopasowanie do rekrutacji w „Szukaj ręcznie”. Wiersz wirtualizowanej
 * listy montuje się dopiero na ekranie, więc montaż = „wiersz widoczny”
 * i dopiero wtedy prosimy o wynik. Brak wyniku nigdy nie wygląda jak zero.
 */
function FitScoreCell({
  candidateId,
  score,
  failure,
  answered,
  onVisible,
  onRetry,
}: {
  candidateId: number;
  score: number | null | undefined;
  failure: "forbidden" | "retry" | undefined;
  answered: boolean;
  onVisible: (id: number) => void;
  onRetry: () => void;
}) {
  useEffect(() => {
    onVisible(candidateId);
  }, [candidateId, onVisible]);
  if (typeof score === "number") {
    return (
      <span
        className={cn(
          "inline-flex h-6 w-9 items-center justify-center rounded-md text-xs font-semibold tabular-nums",
          scoreBadgeClass(score),
        )}
        title="Dopasowanie do tej rekrutacji"
      >
        {Math.round(score)}
      </span>
    );
  }
  if (failure === "forbidden") {
    return <span className="text-xs text-muted-foreground">brak dostępu</span>;
  }
  if (failure === "retry") {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRetry();
        }}
        className="text-xs font-medium text-primary hover:underline"
      >
        ponów
      </button>
    );
  }
  if (answered) {
    return (
      <span className="text-xs text-muted-foreground" title="Ocena niepełna — brak zmierzonego dopasowania">
        niepełna
      </span>
    );
  }
  return <span className="text-xs text-muted-foreground">…</span>;
}

/** Ścieżka, pod którą lista pisze swój stan do adresu. */
const CANDIDATES_LIST_PATH = "/candidates";

/**
 * Czy zmiana stanu listy NIE jest krokiem historii przeglądarki. Pisanie w polu
 * wyszukiwania i zmiana strony tylko
 * podmieniają bieżący wpis; zmiana filtra, sortowania albo zapisanego
 * wyszukiwania dodaje nowy, żeby „Wstecz" cofało filtr.
 */
export function isHistoryNeutralChange(
 previous: CandidateFilters,
 next: CandidateFilters,
): boolean {
 const neutral = { q: "", page: 1, view: "list" } as const;
 return filtersEqual({ ...previous, ...neutral }, { ...next, ...neutral });
}

/**
 * „Szukaj ręcznie” z rekrutacji (25.09.2026) — ta sama lista, osadzona
 * w oknie rekrutacji. Filtry startują z rekrutacji zamiast z adresu, osoby
 * już w rekrutacji są ukryte na stałe (poza chipami i „Wyczyść”), w tabeli
 * dochodzi dopasowanie do tej rekrutacji, a „Przypisz” dodaje wprost do
 * „Nowych”. Adres strony rekrutacji nie jest ani czytany, ani pisany.
 */
export interface CandidatesListEmbed {
  jobId: number;
  jobTitle: string;
  initialFilters: CandidateFilters;
  readOnly?: boolean;
  /** Po udanym dodaniu (np. odświeżenie tablicy rekrutacji). */
  onAdded?: () => void;
  /** Zdanie nad słowami kluczowymi, gdy wiersze przyszły z rekrutacji. */
  keywordsNote?: string;
}

export interface CandidatesListV2Props {
  /**
   * „Z requestu": dane z okna idą do rodzica (ekran „Kandydaci"), który
   * pokazuje wyniki. Bez tego przycisk się nie renderuje.
   */
  onRequestSearch?: (request: TalentRadarInitialRequest) => void;
  embed?: CandidatesListEmbed;
}

/** Filtry zapytania listy; w trybie osadzonym z ukryciem osób z rekrutacji. */
export function candidatesListFiltersForQuery(
  filters: CandidateFilters,
  embed: Pick<CandidatesListEmbed, "jobId"> | null | undefined,
): CandidateFilters {
  if (!embed) return filters;
  return { ...filters, recruitmentIds: [embed.jobId], recruitmentMatch: "not_assigned" };
}

export function CandidatesListV2({ onRequestSearch, embed }: CandidatesListV2Props = {}) {
  const router = useRouter();
  const { showSuccess, showError } = useToast();
  const routeSearchParams = useSearchParams();
  // W trybie osadzonym stan startuje z filtrów rekrutacji — nie z adresu
  // strony rekrutacji (tam `q`, `page`, `sel` znaczą co innego). Jednorazowo,
  // jak odczyt adresu przy montowaniu.
  const [embedSeed] = useState(() => (embed ? encodeFilters(embed.initialFilters) : null));
  // Pamięć wyszukiwania (`search-memory`): lista — goły adres (menu, „Wróć”,
  // inna strona) wraca do ostatniego wyszukiwania karty; okno rekrutacji —
  // ostatnie wyszukiwanie tej osoby w tej rekrutacji. Pamięć listy nigdy nie
  // trafia do okna rekrutacji i odwrotnie.
  const [initialList] = useState(() => {
    if (embed) {
      const userId = useAuthStore.getState().user?.id ?? null;
      const saved = readJobSearch(userId, embed.jobId);
      const query = typeof saved?.request.query === "string" ? saved.request.query : null;
      // Pamięć niesie odcisk filtrów startowych rekrutacji: inny odcisk =
      // DL zmienił wymagania po ostatnim wyszukiwaniu tej osoby. Zostaje jej
      // wyszukiwanie (decyzja 25.09.2026), baner mówi o zmianie.
      const seed = saved?.request.seed;
      return {
        params: query !== null ? new URLSearchParams(query) : (embedSeed as URLSearchParams),
        restored: query !== null,
        restoredAt: query !== null ? saved?.at ?? null : null,
        seedChanged:
          query !== null && typeof seed === "string" && seed !== embedSeed?.toString(),
        memory: null,
      };
    }
    const memory = readListSearch();
    return {
      ...resolveInitialListParams(new URLSearchParams(routeSearchParams?.toString() ?? ""), memory),
      restoredAt: null,
      seedChanged: false,
      memory,
    };
  });
  const searchParams: Pick<URLSearchParams, "get" | "getAll" | "toString"> = initialList.params;
  const routeParams = routeSearchParams;
  const [restoredBanner, setRestoredBanner] = useState(initialList.restored);
  const forJob = Boolean(embed);
  const columnPrefsKey = forJob ? CANDIDATE_JOB_SEARCH_PREFS_KEY : CANDIDATE_TABLE_PREFS_KEY;
  const candidatesPageSize = useUiStore((s) => s.candidatesPageSize);
  const setCandidatesPageSize = useUiStore((s) => s.setCandidatesPageSize);
  // Kolumny tabeli — wybór każdej osoby (lista ukrytych, w przeglądarce).
  const hiddenColumns = useUiStore(
    (s) => s.columnPreferences[columnPrefsKey] ?? null,
  );
  const setColumnPreference = useUiStore((s) => s.setColumnPreference);
  const clearColumnPreference = useUiStore((s) => s.clearColumnPreference);
  const visibleColumns = useMemo(
    () => visibleCandidateColumns(hiddenColumns, { forJob }),
    [hiddenColumns, forJob],
  );
  const gridLayout = useMemo(() => candidateGridLayout(visibleColumns), [visibleColumns]);
  const parentRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();
  const contactFeature = useCandidateContactFeature();
  const [requestOpen, setRequestOpen] = useState(false);

 // URL state ---------------------------------------------------
 const [search, setSearch] = useState(searchParams.get("q") ??"");
 const [searchDraft, setSearchDraft] = useState(searchParams.get("q") ??"");
 const [statusFilter, setStatusFilter] = useState<CandidateStatusFilter[]>(
 parseEnumCsv(
 searchParams.get("status"),
 ["active","passive","blacklisted"] as const,
 ),
 );
 const [sortBy, setSortBy] = useState<CandidateFilters["sort"]>(() => {
 const raw = searchParams.get("sort");
 return raw === "oldest" || raw === "name" || raw === "relevance" || raw === "match"
 ? raw
 : "newest";
 });
 // Jawne „Najnowsi" (w adresie `sort=newest`) — bez niego wpisany tekst
 // szereguje po trafności (patrz `effectiveSort`).
 const [sortExplicit, setSortExplicit] = useState<boolean>(
 searchParams.get("sort") === "newest",
 );
 // Tryb tekstu: auto (backend decyduje) / dosłownie / po znaczeniu. URL `tm`.
 const [textMode, setTextMode] = useState<TextModeFilter>(() => {
 const raw = searchParams.get("tm");
 return raw === "literal" || raw === "semantic" ? raw : "auto";
 });
 // Języki (`en:B2`), ten sam dekoder co chipy i zapisane wyszukiwania.
 const [languages, setLanguages] = useState<string[]>(
 () => decodeFilters(new URLSearchParams(searchParams.toString())).languages,
 );
 const [page, setPage] = useState(Number(searchParams.get("page") ??"1"));
 const [remoteFilter, setRemoteFilter] = useState<string[]>(
 searchParams.get("remote")?.split(",").filter(Boolean) ?? []
 );
 // Boolean skill expression behind the „Musi mieć"/„Wyklucz" buckets —
 // drives the query + URL. Seeded from the URL (`skills_q`,
 // with legacy `skills`/`skill_combine` reconstruction).
 const [skillExpr, setSkillExpr] = useState<string>(() =>
 decodeSkillsExpr(new URLSearchParams(searchParams.toString())),
 );
 const skillBuckets = useMemo(
 () => parseSkillExpression(skillExpr),
 [skillExpr],
 );
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
 // Ten sam dekoder co chipy, zapisane wyszukiwania i API — osobna lista etapów
 // pomijała „posting”, więc filtr „Ogłoszenia” znikał po odświeżeniu strony.
 const [pipelineStageFilter, setPipelineStageFilter] = useState<PipelineStageFilter[]>(
 () => decodeFilters(new URLSearchParams(searchParams.toString())).pipelineStage,
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
 const [competenceCategoryIds, setCompetenceCategoryIds] = useState<number[]>(
 (searchParams.get("cc") ??"")
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
 const [tagsFilter, setTagsFilter] = useState<string[]>(
 (searchParams.get("tags") ??"").split("|").filter(Boolean)
 );
 // Lata doświadczenia (min–max). null bound = open. Parsed with the same
 // clamp as decodeFilters so URL → state and saved searches agree.
 const [experienceMin, setExperienceMin] = useState<number | null>(
 parseYearBound(searchParams.get("exp_min"))
 );
 const [experienceMax, setExperienceMax] = useState<number | null>(
 parseYearBound(searchParams.get("exp_max"))
 );
 // Oczekiwana stawka godzinowa (B2B, PLN/h). null bound = open. Parsed with the
 // same clamp as decodeFilters so URL → state and saved searches agree.
 const [rateMin, setRateMin] = useState<number | null>(
 parseRateBound(searchParams.get("rate_min"))
 );
 const [rateMax, setRateMax] = useState<number | null>(
 parseRateBound(searchParams.get("rate_max"))
 );
 const [workedAtClientIds, setWorkedAtClientIds] = useState<number[]>(
 (searchParams.get("client_hist") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 // Przynależność do rekrutacji — przypisany (lub NIE) do wybranych rekrutacji.
 const [recruitmentIds, setRecruitmentIds] = useState<number[]>(
 (searchParams.get("recr") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 const [recruitmentMatch, setRecruitmentMatch] = useState<RecruitmentMatch>(
 searchParams.get("recr_mode") === "not_assigned" ? "not_assigned" : "assigned"
 );
 // Stage-move filters — "kto dodał na etap i kiedy". Correlated with
 // `pipelineStageFilter` on the backend (matched stage move's mover + date).
 const [stageMovedByIds, setStageMovedByIds] = useState<number[]>(
 (searchParams.get("stage_by") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 const [stageMovedAfter, setStageMovedAfter] = useState<string>(
 searchParams.get("stage_from") ??""
 );
 const [stageMovedBefore, setStageMovedBefore] = useState<string>(
 searchParams.get("stage_to") ??""
 );
 // Etap — client owning the job on which the matched stage move happened
 // (correlated with `pipelineStageFilter` + who/when). Distinct from
 // `workedAtClientIds` (hired/contract history).
 const [stageClientIds, setStageClientIds] = useState<number[]>(
 (searchParams.get("stage_client") ??"")
 .split(",")
 .map((x) => Number.parseInt(x, 10))
 .filter((n) => Number.isFinite(n))
 );
 // „Data wysłania do klienta" — zakres dat rekomendacji kandydata do klienta
 // (przejście na etap `cv_sent`). Niezależny od rodziny `stage*`, historyczny.
 const [sentToClientFrom, setSentToClientFrom] = useState<string>(
 searchParams.get("sent_from") ??""
 );
 const [sentToClientTo, setSentToClientTo] = useState<string>(
 searchParams.get("sent_to") ??""
 );
 // "Aktualny etap" toggle — force current-stage matching even with a
 // who/when/client move-filter. Off (default) lets the backend auto-resolve.
 const [stageCurrentOnly, setStageCurrentOnly] = useState<boolean>(
 searchParams.get("stage_current") === "1"
 );
 // LinkedIn-detected job change window —"1","2", or"3" months. Empty = off.
 const [recentlyChangedJobs, setRecentlyChangedJobs] =
 useState<RecentlyChangedJobs>(() => {
 const raw = Number.parseInt(searchParams.get("rcj") ?? "", 10);
 return raw === 1 || raw === 2 || raw === 3 ? raw : null;
 });
 // Filtry z porównania z Traffitem (22.09.2026): zakres słów kluczowych,
 // promień w km, województwa i kontakt — jeden obiekt stanu, bo zawsze
 // chodzą razem przez adres, „Wyczyść" i „Wstecz".
 const [traffitExtras, setTraffitExtras] = useState<TraffitExtraFilters>(() =>
 pickTraffitExtras(decodeFilters(new URLSearchParams(searchParams.toString()))),
 );
 // Wersja semantyki filtrów: domyślnie 2 (jedna semantyka z wyszukiwarką,
 // decyzja 21.09.2026), także dla starych zakładek bez `sv`. `sv=1` niesie
 // tylko zapis przypięty do dawnych zasad. Bez kontrolki w UI — „Wyczyść"
 // wraca do v2.
 const [semanticsVersion, setSemanticsVersion] = useState<1 | 2>(
 searchParams.get("sv") === "1" ? 1 : 2,
 );
 // „Mile widziane" (tylko kolejność) i „Ukryj osoby bez danych".
 const [skillsPreferred, setSkillsPreferred] = useState<string[]>(() =>
 searchParams
 .getAll("skills_pref")
 .map((x) => x.trim())
 .filter(Boolean),
 );
 const [hideUnknown, setHideUnknown] = useState<boolean>(
 searchParams.get("hu") === "1",
 );
 // CAND-06: zakres lokalizacji z migrowanego zapisu (`ls=location_only`).
 const [locationScope, setLocationScope] = useState<
 CandidateFilters["locationScope"]
 >(searchParams.get("ls") === "location_only" ? "location_only" : "");
 // Engagement openness — any of {side_projects, sales_support, expert_consult}, OR-combined.
 const [openToFilter, setOpenToFilter] = useState<OpenToValue[]>(
 searchParams
 .getAll("open_to")
 .flatMap((value) => value.split(","))
 .filter((v): v is OpenToValue =>
 v === "side_projects" || v === "sales_support" || v === "expert_consult"
 )
 );
 // Słowa kluczowe = lista wymagań (`lib/keyword-requirements`). Adres czyta
 // jeden parser (`decodeFilters`) — stare `q_all` wraca jako wiersze na
 // początku, więc kolejność wierszy i licznik zmian są te same co w adresie.
 const [initialKeywords] = useState(() =>
 decodeFilters(new URLSearchParams(searchParams.toString())),
 );
 const [qAll, setQAll] = useState<string[]>(initialKeywords.qAll);
 const [qAny, setQAny] = useState<string[][]>(initialKeywords.qAny);
 const [qNone, setQNone] = useState<string[]>(initialKeywords.qNone);
 // Cleaned ANY OR-groups: drop empty strings + empty groups. The popover may
 // hold a transient empty group (an open input row); strip those before they
 // reach the URL, the API query, or the active-filter count.
 const qAnyGroups = useMemo(
 () => qAny.map((g) => g.filter(Boolean)).filter((g) => g.length > 0),
 [qAny],
 );
 // Boolean-search panel visibility. Opens automatically when the URL arrives
 // with any q_all/q_any/q_none — the user has filters and needs to see them.
 // Otherwise opt-in via the `Boolean` toggle next to the search input. Persists
 // across reloads via `?boolean=1` once opened so the recruiter doesn't lose
 // their workspace.
 const currentUser = useAuthStore((s) => s.user);

 // Draft wyszukiwarki reaguje natychmiast, ale nie wysyła requestu na każdy
 // znak. Enter w polu wywołuje ten sam commit bez oczekiwania na debounce.
 const commitSearchValue = useCallback((value: string) => {
 setSearch(value);
 setPage(1);
 }, []);
 useCandidateSearchDebounce({
 draft: searchDraft,
 committed: search,
 onCommit: commitSearchValue,
 });

 // Saved-search alerty — aktywny zapisany search (z menu „Zapisane” lub z
 // linku powiadomienia `?ss=`) + znacznik czasu sprzed bieżącego otwarcia
 // (previous last_viewed_at z POST /saved-searches/{id}/viewed). Kandydaci
 // utworzeni po znaczniku dostają badge „Nowy” + podświetlenie wiersza.
 const [activeSavedSearchId, setActiveSavedSearchId] = useState<number | null>(
 () => {
 const raw = searchParams.get("ss");
 const n = raw ? Number.parseInt(raw, 10) : NaN;
 return Number.isFinite(n) && n > 0 ? n : null;
 }
 );
 const [newSince, setNewSince] = useState<string | null>(null);
 // Kto WSZEDŁ do wyniku zapisanego wyszukiwania od ostatniego otwarcia (log
 // skanera alertów) — także osoba, która była w bazie, a zaczęła pasować po
 // nowym CV albo notatce.
 const [newMatchIds, setNewMatchIds] = useState<ReadonlySet<number>>(() => new Set());
 const ssInitRef = useRef(false);
 useEffect(() => {
 // Wejście z linku powiadomienia (?ss=ID bez przejścia przez menu) —
 // dociągnij własny saved search, zresetuj badge i ustaw znacznik „Nowy”.
 if (ssInitRef.current || activeSavedSearchId === null || !currentUser) return;
 ssInitRef.current = true;
 (async () => {
 try {
 const rows = (await savedSearchesApi.list("candidates")).data;
 const row = rows.find((r) => r.id === activeSavedSearchId);
 if (!row || row.user_id !== currentUser.id) return;
 const r = await savedSearchesApi.markViewed(row.id);
 setNewSince(r.data.previous_viewed_at);
 setNewMatchIds(new Set(r.data.new_candidate_ids ?? []));
 queryClient.invalidateQueries({
 queryKey: ["saved-searches","candidates"],
 });
 } catch {
 // best-effort — brak wyróżnienia nie może blokować listy
 }
 })();
 }, [activeSavedSearchId, currentUser, queryClient]);
 const newSinceTs = useMemo(() => {
 if (!newSince) return null;
 // Defensive: dołóż 'Z' gdyby backend zwrócił naive ISO (bez strefy).
 const iso = /[zZ]|[+-]\d{2}:\d{2}$/.test(newSince) ? newSince : `${newSince}Z`;
 const ts = Date.parse(iso);
 return Number.isFinite(ts) ? ts : null;
 }, [newSince]);

 // Jeden kanoniczny snapshot zasila URL, API, chipy, zapisane wyszukiwania i
 // nawigację poprzedni/następny. Lokalne kontrolki są tylko adapterami UI.
 const filtersSnapshot: CandidateFilters = useMemo(
 () => ({
 q: search,
 status: statusFilter,
 employment: employmentFilter,
 availability: availabilityFilter,
 pipelineStage: pipelineStageFilter,
 sort: sortBy,
 sortExplicit,
 textMode,
 languages,
 page,
 remote: remoteFilter as CandidateFilters["remote"],
 skillsExpr: skillExpr,
 skillsPreferred,
 hideUnknown,
 locationScope,
 location: locationFilter,
 poolIds,
 competenceCategoryIds,
 addedByIds,
 currentCompany: currentCompanyFilter,
 pastCompany: pastCompanyFilter,
 currentTitle: currentTitleFilter,
 tags: tagsFilter,
 workedAtClientIds,
 recruitmentIds,
 recruitmentMatch,
 experienceMin,
 experienceMax,
 rateMin,
 rateMax,
 stageMovedByIds,
 stageMovedAfter,
 stageMovedBefore,
 stageClientIds,
 sentToClientFrom,
 sentToClientTo,
 stageCurrentOnly,
 openTo: openToFilter,
 recentlyChangedJobs,
 semanticsVersion,
 view: "list",
 savedSearchId: activeSavedSearchId,
 qAll,
 qAny: qAnyGroups,
 qNone,
 ...traffitExtras,
 }),
 [
 traffitExtras,
 search,
 statusFilter,
 employmentFilter,
 availabilityFilter,
 pipelineStageFilter,
 sortBy,
 sortExplicit,
 textMode,
 languages,
 page,
 remoteFilter,
 skillExpr,
 skillsPreferred,
 hideUnknown,
 locationScope,
 locationFilter,
 poolIds,
 competenceCategoryIds,
 addedByIds,
 currentCompanyFilter,
 pastCompanyFilter,
 currentTitleFilter,
 tagsFilter,
 workedAtClientIds,
 recruitmentIds,
 recruitmentMatch,
 experienceMin,
 experienceMax,
 rateMin,
 rateMax,
 stageMovedByIds,
 stageMovedAfter,
 stageMovedBefore,
 stageClientIds,
 sentToClientFrom,
 sentToClientTo,
 stageCurrentOnly,
 openToFilter,
 recentlyChangedJobs,
 semanticsVersion,
 activeSavedSearchId,
 qAll,
 qAnyGroups,
 qNone,
 ],
 );

 // Filtry robocze (`filtersSnapshot`) kontra zastosowane (`applied`): zmiany
 // czekają na „Szukaj” (decyzja 25.09.2026). Od razu działa tylko sortowanie
 // i strona przy tych samych kryteriach (`carryImmediate`). Zapytanie, adres,
 // eksport, zapis wyszukiwania i linki do profilu czytają `applied`.
 const [applied, setApplied] = useState<CandidateFilters>(filtersSnapshot);
 const [applyTick, setApplyTick] = useState(0);
 const applyRequestedRef = useRef(false);
 // Okno rekrutacji zapisuje pamięć dopiero po działaniu osoby — nietknięte
 // filtry z rekrutacji nie mogą przykryć nowych wymagań Championa.
 const rememberRef = useRef(false);
 const requestApply = useCallback(() => {
 rememberRef.current = true;
 applyRequestedRef.current = true;
 setApplyTick((t) => t + 1);
 }, []);
 useEffect(() => {
 if (applyRequestedRef.current) {
 applyRequestedRef.current = false;
 setApplied(filtersSnapshot);
 return;
 }
 setApplied((prev) => carryImmediate(prev, filtersSnapshot));
 }, [filtersSnapshot, applyTick]);
 const resultsPage = applied.page;
 const goToPage = useCallback((next: number) => {
 rememberRef.current = true;
 setPage(next);
 setApplied((prev) => ({ ...prev, page: next }));
 }, []);
 const draftForCompare = useMemo(
 () => ({ ...filtersSnapshot, q: searchDraft }),
 [filtersSnapshot, searchDraft],
 );
 const pendingCount = useMemo(
 () => filterChangeCount(draftForCompare, applied),
 [draftForCompare, applied],
 );
 // Górne pole: same nazwy technologii → wiersze wymagań (decyzja 25.09.2026).
 const [convertedText, setConvertedText] = useState<{
 text: string;
 skills: string[];
 previousRows: string[][];
 } | null>(null);
 const runSearch = async () => {
 let text = searchDraft;
 let rows = qAny;
 setConvertedText(null);
 if (textMode === "auto" && mayBeSkillList(text)) {
 const result = await classifyKeywords(text.trim());
 if (result?.as_requirements && result.skills.length > 0) {
 const existing = new Set(qAny.flat().map((word) => word.toLowerCase()));
 const added = result.skills
 .filter((skill) => !existing.has(skill.toLowerCase()))
 .map((skill) => [skill]);
 setConvertedText({ text, skills: result.skills, previousRows: qAny });
 rows = [...qAny, ...added];
 setQAny(rows);
 setSearchDraft("");
 text = "";
 }
 }
 if (text !== search) setSearch(text);
 setPage(1);
 requestApply();
 const next = { ...filtersSnapshot, q: text, qAny: rows, page: 1 };
 pushRecentSearch(currentUser?.id, {
 kind: embed ? "job" : "list",
 jobId: embed?.jobId ?? null,
 label: listSearchLabel(next),
 query: encodeFilterCriteria(next).toString(),
 keywords: listSearchKeywords(next),
 total: null,
 });
 };
 const searchByMeaning = () => {
 if (!convertedText) return;
 setQAny(convertedText.previousRows);
 setSearchDraft(convertedText.text);
 setSearch(convertedText.text);
 setTextMode("semantic");
 setConvertedText(null);
 setPage(1);
 requestApply();
 };
 const undoPending = () => {
 setSearchDraft(applied.q);
 applyFiltersPatch({ ...applied });
 };

 // Pamięć tej karty: ostatnie zastosowane wyszukiwanie (powrót z profilu).
 const memoryQuery = useMemo(
 () => encodeFilters({ ...applied, savedSearchId: null, view: "list" }).toString(),
 [applied],
 );
 const embedMemoryJobId = embed?.jobId ?? null;
 useEffect(() => {
 if (embedMemoryJobId === null) {
 writeListSearch({ query: memoryQuery });
 return;
 }
 if (!rememberRef.current) return;
 writeJobSearch(currentUser?.id, embedMemoryJobId, {
 query: memoryQuery,
 seed: embedSeed?.toString() ?? null,
 });
 }, [memoryQuery, embedMemoryJobId, currentUser?.id, embedSeed]);
 // Menu „Kandydaci” na otwartej liście zdejmuje parametry z adresu, ale
 // komponent zostaje — oddajemy adres zamiast rozjazdu z tym, co widać.
 const skipRouteRestoreRef = useRef(false);
 useEffect(() => {
 if (skipRouteRestoreRef.current) {
 skipRouteRestoreRef.current = false;
 return;
 }
 if (typeof window === "undefined" || window.location.pathname !== CANDIDATES_LIST_PATH) return;
 const route = new URLSearchParams(routeParams?.toString() ?? "");
 if (!isBareListQuery(route) || !memoryQuery) return;
 window.history.replaceState(null, "", `${CANDIDATES_LIST_PATH}?${encodeFilters(applied).toString()}`);
 setRestoredBanner(true);
 // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [routeParams]);
 // Baner listy mówi „Filtry… są takie, jak je zostawiłeś” — po zastosowaniu
 // innych kryteriów (zapis z „Zapisanych”, „Szukaj”, „Wstecz”) przestałby mówić
 // prawdę. Strona i sortowanie go nie zdejmują. Okno rekrutacji zostawia swój
 // baner: „Przywrócono…” opisuje zdarzenie, a „Wróć do filtrów z rekrutacji”
 // jest jedyną drogą do filtrów startowych.
 const restoredCriteriaRef = useRef<CandidateFilters | null>(null);
 useEffect(() => {
 if (!restoredBanner || forJob) {
 restoredCriteriaRef.current = null;
 return;
 }
 if (restoredCriteriaRef.current === null) {
 restoredCriteriaRef.current = applied;
 return;
 }
 if (!sameCriteria(restoredCriteriaRef.current, applied)) setRestoredBanner(false);
 }, [applied, restoredBanner, forJob]);
 // Przewinięcie listy i ostatnio otwarta osoba — przywracane po powrocie.
 const [lastOpenedId] = useState<number | null>(() =>
 initialList.restored || initialList.memory?.query === encodeFilters({ ...filtersSnapshot, savedSearchId: null, view: "list" }).toString()
 ? initialList.memory?.lastOpenedId ?? null
 : null,
 );
 const scrollSavedAtRef = useRef(0);
 const onListScroll = (event: UIEvent<HTMLDivElement>) => {
 if (embed) return;
 const now = Date.now();
 if (now - scrollSavedAtRef.current < 200) return;
 scrollSavedAtRef.current = now;
 writeListSearch({ query: memoryQuery, scrollTop: event.currentTarget.scrollTop });
 };
 const startNewSearch = () => {
 setRestoredBanner(false);
 if (embed) {
 // „Wróć do filtrów z rekrutacji”: pamięć tej rekrutacji znika.
 clearJobSearch(currentUser?.id, embed.jobId);
 applyFiltersPatch({ ...embed.initialFilters, page: 1 });
 requestApply();
 rememberRef.current = false;
 return;
 }
 clearListSearch();
 resetAllFilters();
 requestApply();
 };

 // Sync URL -----------------------------------------------------
 // Pierwszy zapis i zmiany „neutralne" (pole wyszukiwania, strona, widok) →
 // replaceState; zmiana filtra/sortowania → pushState, więc „Wstecz" cofa
 // filtr. Pierwszy zapis podmienia wpis, więc zdejmuje też `?sel=` (patrz
 // odczyt zaznaczenia niżej). Dane stanu `null`, nie `window.history.state`:
 // łatka Next.js dokleja wtedy własny stan routera ORAZ aktualizuje jego URL;
 // stan z `__NA` pomija tę synchronizację i router mógłby później przywrócić
 // stary adres.
 const lastSyncedFiltersRef = useRef<CandidateFilters | null>(null);
 // Ustawiany przez `popstate` — przywrócenie wpisu nie może dodać nowego.
 const restoringHistoryRef = useRef(false);
 useEffect(() => {
 const previous = lastSyncedFiltersRef.current;
 lastSyncedFiltersRef.current = applied;
 const restoring = restoringHistoryRef.current;
 restoringHistoryRef.current = false;
 // Lista mogła zostać opuszczona (Wstecz do profilu) — nie nadpisujemy
 // cudzego adresu.
 if (window.location.pathname !== CANDIDATES_LIST_PATH) return;
 const qs = encodeFilters(applied).toString();
 const target = qs ? `${CANDIDATES_LIST_PATH}?${qs}` : CANDIDATES_LIST_PATH;
 const current = `${window.location.pathname}${window.location.search}`;
 if (
 previous === null ||
 restoring ||
 target === current ||
 isHistoryNeutralChange(previous, applied)
 ) {
 window.history.replaceState(null, "", target);
 } else {
 window.history.pushState(null, "", target);
 }
 }, [applied]);

 // Data --------------------------------------------------------
 const embedJobId = embed?.jobId ?? null;
 // Filtry, którymi lista NAPRAWDĘ pyta API — w oknie rekrutacji z ukryciem
 // osób z tej rekrutacji. Te same idą do podglądu (poprzedni/następny)
 // i linku profilu, inaczej sąsiednia strona pokazałaby osoby z rekrutacji.
 const queryFilters = useMemo(
 () =>
 candidatesListFiltersForQuery(
 applied,
 embedJobId != null ? { jobId: embedJobId } : null,
 ),
 [applied, embedJobId],
 );
 const candidatesApiParams = useMemo(
 () => candidatesListApiParams(queryFilters, queryFilters.page, candidatesPageSize),
 [queryFilters, candidatesPageSize],
 );
 const {
 data,
 isLoading,
 isFetching,
 isError,
 error: candidatesError,
 refetch: refetchCandidates,
 } = useQuery({
 queryKey: candidatesListQueryKey(candidatesApiParams),
 queryFn: ({ signal }) =>
 fetchCandidateListPage<CandidateListResponse>(candidatesApiParams, signal),
 placeholderData: keepPreviousData,
 staleTime: 30_000,
 // Wynik zmienia tylko „Szukaj” albo strona; powrót na kartę nie ma
 // powodu liczyć wyszukiwania od nowa (audyt szybkości 25.09.2026).
 refetchOnWindowFocus: false,
 });

 const items: Candidate[] = data?.items ?? [];
 const listViewState = getCandidateListViewState({
 isLoading,
 isError,
 itemCount: items.length,
 });
 const total = data?.total ?? 0;
 const pageSize = data?.page_size ?? candidatesPageSize;
 const totalPages = Math.max(1, Math.ceil(total / pageSize));
 // Strona spoza zakresu (stary link, usunięci kandydaci) — cofamy do ostatniej
 // strony zamiast pokazywać „0 wyników” bez paginacji. Liczymy wyłącznie z
 // odpowiedzi dla tej strony (nie z danych zastępczych w trakcie pobierania).
 useEffect(() => {
 if (!data || isFetching || data.items.length > 0 || data.total <= 0) return;
 const lastPage = Math.max(1, Math.ceil(data.total / data.page_size));
 if (data.page > lastPage) goToPage(lastPage);
 }, [data, isFetching, goToPage]);
 // Powrót do listy: przewinięcie z pamięci tej karty, raz, po pierwszych danych.
 const scrollRestoredRef = useRef(false);
 useEffect(() => {
 if (scrollRestoredRef.current || !data || isFetching) return;
 scrollRestoredRef.current = true;
 const memory = initialList.memory;
 if (!memory || memory.scrollTop <= 0 || memory.query !== memoryQuery) return;
 const el = parentRef.current;
 if (el) el.scrollTop = memory.scrollTop;
 // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [data, isFetching]);

 // Płaska, odduplikowana lista fraz wyszukiwania (q + q_all + q_any) — używana
 // do podświetlenia <mark> w snippetach CV. `q_none` celowo pomijamy: fraz
 // wykluczających nie podświetlamy. Tokeny <2 znaki odpadają (zaśmiecają mark).
 const searchTerms = useMemo(() => {
 const raw = [...applied.q.split(/\s+/), ...applied.qAll, ...applied.qAny.flat()];
 const seen = new Set<string>();
 const out: string[] = [];
 for (const term of raw) {
 const norm = term.trim();
 if (norm.length < 2) continue;
 const key = norm.toLowerCase();
 if (seen.has(key)) continue;
 seen.add(key);
 out.push(norm);
 }
 return out;
 }, [applied]);
 const hasSearchTerms = searchTerms.length > 0;

 // Virtualization ---------------------------------------------
 // Bazowa wysokość wiersza: stałe 64px (tabela bez przełącznika gęstości).
 // Gdy wyszukiwanie jest aktywne i kandydat ma dopasowany fragment CV
 // (`match_snippet`), wiersz rośnie o SNIPPET_AREA, by zmieścić snippet pod
 // danymi — recruiter od razu widzi, z czego wynika dopasowanie (parytet Traffit).
 // Snippet pokrywa WSZYSTKIE frazy z search (q_all), więc bywa dłuższy niż jedna
 // fraza — 3 linie (line-clamp-3 niżej) mieszczą kilka okien „pole: …fragment…".
 // 66px = 3 linie text-xs/leading-normal (3×18=54) + hairline (border-t, 1px)
 // + pt-1/pb-1.5 (10px) — czytelny snippet bez ucinania trzeciej linii.
 const rowHeight = ROW_HEIGHT;
 const SNIPPET_AREA = 66;
 // v2: jedna linia na pole (18px) + odstępy (11px). Wysokość musi być
 // dokładna — wiersze są pozycjonowane przez wirtualizację.
 const snippetAreaFor = (c: Candidate | undefined): number => {
 const fields = c?.match_snippets?.length ?? 0;
 if (fields > 0) return 11 + 18 * Math.min(fields, MAX_FIELD_SNIPPETS);
 return c?.match_snippet ? SNIPPET_AREA : 0;
 };
 const virtualizer = useVirtualizer({
 count: items.length,
 getScrollElement: () => parentRef.current,
 // Nagłówek kolumn siedzi w tym samym kontenerze przewijania (przyklejony
 // u góry), więc pierwszy wiersz zaczyna się pod nim.
 scrollMargin: LIST_HEADER_HEIGHT,
 estimateSize: (index) => {
 const c = items[index];
 return rowHeight + (hasSearchTerms ? snippetAreaFor(c) : 0);
 },
 overscan: 10,
 });
 // estimateSize zależy od danych (snippet); react-virtual czyta
 // estimateSize na nowo dopiero po `measure()` (resecie cache rozmiarów), więc
 // wymuszamy je po każdej zmianie wyników / aktywności wyszukiwania.
 // Klucz to stabilna referencja `data` z react-query (NIE `items`, które są
 // świeżą tablicą co render → pętla re-measure).
 useEffect(() => {
 virtualizer.measure();
 }, [virtualizer, data, hasSearchTerms]);

 // Selection ---------------------------------------------------
 // `?sel=` odtwarza zaznaczenie po powrocie z porównania (UAT B21) — czytane
 // przy montowaniu, jak reszta stanu listy; `encodeFilters` go nie zapisuje,
 // więc pierwszy zapis adresu (zawsze replaceState, wyżej) zdejmuje parametr.
 const [selectedIds, setSelectedIds] = useState<Set<number>>(
 () => new Set(decodeSelectedIds(new URLSearchParams(searchParams.toString())))
 );
 const toggleId = useCallback((id: number) => {
 setSelectedIds((prev) => {
 const next = new Set(prev);
 if (next.has(id)) next.delete(id);
 else next.add(id);
 return next;
 });
 }, []);
 const clearSelection = () => setSelectedIds(new Set());

 // „Szukaj ręcznie” z rekrutacji: dopasowanie do TEJ rekrutacji (tylko
 // wiersze na ekranie, paczki po 20) i dodanie wprost do „Nowych” — ta sama
 // trasa co wyszukiwarka dotąd (`proposals/bulk`, źródło `manual_search`).
 const matchScores = useVisibleMatchScores(embedJobId, embed ? items : null);
 const [addingIds, setAddingIds] = useState<ReadonlySet<number>>(() => new Set());
 const embedOnAdded = embed?.onAdded;
 const addToEmbedJob = useCallback(
 async (candidateIds: number[]) => {
 if (embedJobId == null || candidateIds.length === 0) return;
 setAddingIds((prev) => new Set([...prev, ...candidateIds]));
 try {
 const result = await proposalsBulkApi.add(embedJobId, {
 candidate_ids: candidateIds,
 initial_stage_legacy: "new",
 source: "manual_search",
 });
 const summary = summarizeBulkResult(result);
 const parts = [
 result.total_added > 0
 ? `Dodano do Nowych: ${result.total_added}.`
 : "Nikogo nie dodano.",
 ];
 if (summary.skipped.length > 0) {
 parts.push(`Pominięto: ${formatReasonCounts(summary.skipped)}.`);
 }
 if (summary.warnings.length > 0) {
 parts.push(`Uwaga: ${formatReasonCounts(summary.warnings)}.`);
 }
 if (result.total_added > 0) showSuccess(parts.join(" "));
 else showError(parts.join(" "));
 setSelectedIds((prev) => {
 const next = new Set(prev);
 for (const id of result.added) next.delete(id);
 return next;
 });
 void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
 void queryClient.invalidateQueries({ queryKey: ["kanban", String(embedJobId)] });
 void queryClient.invalidateQueries({ queryKey: ["kanban", embedJobId] });
 void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
 if (result.total_added > 0) embedOnAdded?.();
 } catch (err) {
 showError(apiErrorMessage(err, "Nie udało się dodać kandydatów do rekrutacji."));
 } finally {
 setAddingIds((prev) => {
 const next = new Set(prev);
 for (const id of candidateIds) next.delete(id);
 return next;
 });
 }
 },
 [embedJobId, embedOnAdded, queryClient, showError, showSuccess],
 );
 const selectionCriteriaKey = useMemo(
 () =>
 encodeFilterCriteria({
 ...applied,
 sort: "newest",
 }).toString(),
 [applied],
 );
 const previousSelectionCriteria = useRef(selectionCriteriaKey);
 useEffect(() => {
 if (previousSelectionCriteria.current === selectionCriteriaKey) return;
 previousSelectionCriteria.current = selectionCriteriaKey;
 setSelectedIds(new Set());
 }, [selectionCriteriaKey]);

 const visibleSelectedCount = items.reduce(
 (count, item) => count + (selectedIds.has(item.id) ? 1 : 0),
 0,
 );
 const allVisibleSelected =
 items.length > 0 && visibleSelectedCount === items.length;
 const selectAllVisible = () => {
 setSelectedIds((previous) => {
 const next = new Set(previous);
 if (allVisibleSelected) {
 items.forEach((item) => next.delete(item.id));
 } else {
 items.forEach((item) => next.add(item.id));
 }
 return next;
 });
 };

 // Modals + assigns -------------------------------------------
 const [showAdd, setShowAdd] = useState(false);
 const [showImport, setShowImport] = useState(false);
 const [showAddFromCV, setShowAddFromCV] = useState(false);
 const [showInvite, setShowInvite] = useState(false);
 const [showBulkPool, setShowBulkPool] = useState(false);
 const [showBulkRecruitment, setShowBulkRecruitment] = useState(false);
 const [bulkPoolPending, setBulkPoolPending] = useState(false);
 const [assignFor, setAssignFor] = useState<{ id: number; name: string } | null>(null);
 const [detailId, setDetailId] = useState<number | null>(null);
 // Ostatnio oglądany kandydat — cel powrotu fokusu po zamknięciu podglądu
 // (UAT B22). Ref, bo przy zamykaniu `detailId` jest już `null`.
 const lastDetailIdRef = useRef<number | null>(null);
 useEffect(() => {
 if (detailId !== null) lastDetailIdRef.current = detailId;
 }, [detailId]);
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
 toastOnSuccess(apiErrorMessage(e, "Nie udało się dodać do puli"));
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
 const doExport = async (
 format: "csv" | "xlsx",
 scope: CandidateExportScope = "filtered",
 ) => {
 if (scope === "selected" && selectedIds.size === 0) return;
 try {
 const request = buildCandidateExportRequest(
 applied,
 format,
 scope,
 selectedIds,
 );
 await downloadCandidateExport(request);
 toastOnSuccess(
 scope === "selected"
 ? `Wyeksportowano ${selectedIds.size} zaznaczonych kandydatów.`
 : "Eksport wyników został przygotowany.",
 );
 } catch (error) {
 const fallback = "Eksport nie powiódł się. Spróbuj ponownie.";
 const response = (
 error as { response?: { status?: number; data?: unknown } }
 ).response;
 let message = apiErrorMessage(error, fallback);
 if (response?.data instanceof Blob) {
 try {
 // Eksport pobiera Bloba, więc ciało błędu też jest Blobem — odtwarzamy
 // odpowiedź, żeby `detail` przeszedł przez to samo tłumaczenie.
 const data: unknown = JSON.parse(await response.data.text());
 message = apiErrorMessage({ response: { status: response.status, data } }, fallback);
 } catch {
 // Nieczytelna odpowiedź (np. zerwane połączenie) — zachowaj fallback.
 }
 }
 toastOnSuccess(message);
 }
 };

 // Umiejętności w trzech kubełkach. „Musi mieć" i „Wyklucz" żyją w wyrażeniu
 // (`skills_q` — stare zakładki otwierają się bez zmian), „Mile widziane"
 // w osobnym parametrze. Pozycja `a|b` z „Musi mieć" to grupa „którakolwiek".
 const applySkillBuckets = (next: {
 required: string[];
 preferred: string[];
 excluded: string[];
 }) => {
 const must: string[] = [];
 const anyGroups: string[][] = [];
 for (const entry of next.required) {
 const parts = entry
 .split("|")
 .map((part) => part.trim())
 .filter(Boolean);
 if (parts.length > 1) anyGroups.push(parts);
 else if (parts.length === 1) must.push(parts[0]);
 }
 setSkillExpr(
 serializeSkillBuckets({ must, anyGroups, none: next.excluded }),
 );
 setSkillsPreferred(next.preferred);
 setPage(1);
 };

 // Łączna liczba aktywnych filtrów (bez prostego „q" i sortowania) —
 // napędza licznik na przycisku „Filtry" oraz stan „Wyczyść wszystko".
 const totalActiveFilters =
 statusFilter.length +
 employmentFilter.length +
 availabilityFilter.length +
 pipelineStageFilter.length +
 openToFilter.length +
 remoteFilter.length +
 countSkillConstraints(skillBuckets) +
 skillsPreferred.length +
 (hideUnknown ? 1 : 0) +
 (locationFilter ? 1 : 0) +
 poolIds.length +
 competenceCategoryIds.length +
 addedByIds.length +
 currentCompanyFilter.length +
 pastCompanyFilter.length +
 currentTitleFilter.length +
 tagsFilter.length +
 workedAtClientIds.length +
 recruitmentIds.length +
 (experienceMin !== null || experienceMax !== null ? 1 : 0) +
 (rateMin !== null || rateMax !== null ? 1 : 0) +
 stageMovedByIds.length +
 (stageMovedAfter || stageMovedBefore ? 1 : 0) +
 stageClientIds.length +
 (sentToClientFrom || sentToClientTo ? 1 : 0) +
 (stageCurrentOnly ? 1 : 0) +
 (recentlyChangedJobs ? 1 : 0) +
 qAll.length +
 qAnyGroups.flat().length +
 qNone.length +
 languages.length +
 (traffitExtras.locationRadiusKm !== null && locationFilter ? 1 : 0) +
 traffitExtras.voivodeships.length +
 (traffitExtras.contacted ? 1 : 0) +
 (traffitExtras.contacted ? traffitExtras.contactedByIds.length : 0);

 const applyFiltersPatch = (patch: Partial<CandidateFilters>) => {
 if (patch.q !== undefined) {
 setSearch(patch.q);
 setSearchDraft(patch.q);
 }
 if (patch.status !== undefined) setStatusFilter(patch.status);
 if (patch.employment !== undefined) setEmploymentFilter(patch.employment);
 if (patch.availability !== undefined) setAvailabilityFilter(patch.availability);
 if (patch.pipelineStage !== undefined) setPipelineStageFilter(patch.pipelineStage);
 if (patch.sort !== undefined) setSortBy(patch.sort);
 if (patch.sortExplicit !== undefined) setSortExplicit(patch.sortExplicit);
 if (patch.textMode !== undefined) setTextMode(patch.textMode);
 if (patch.languages !== undefined) setLanguages(patch.languages);
 if (patch.page !== undefined) setPage(patch.page);
 if (patch.remote !== undefined) setRemoteFilter(patch.remote);
 if (patch.skillsExpr !== undefined) {
 setSkillExpr(patch.skillsExpr);
 }
 if (patch.skillsPreferred !== undefined) setSkillsPreferred(patch.skillsPreferred);
 if (patch.hideUnknown !== undefined) setHideUnknown(patch.hideUnknown);
 if (patch.locationScope !== undefined) setLocationScope(patch.locationScope);
 if (patch.location !== undefined) setLocationFilter(patch.location);
 if (patch.poolIds !== undefined) setPoolIds(patch.poolIds);
 if (patch.competenceCategoryIds !== undefined)
 setCompetenceCategoryIds(patch.competenceCategoryIds);
 if (patch.addedByIds !== undefined) setAddedByIds(patch.addedByIds);
 if (patch.currentCompany !== undefined) setCurrentCompanyFilter(patch.currentCompany);
 if (patch.pastCompany !== undefined) setPastCompanyFilter(patch.pastCompany);
 if (patch.currentTitle !== undefined) setCurrentTitleFilter(patch.currentTitle);
 if (patch.tags !== undefined) setTagsFilter(patch.tags);
 if (patch.workedAtClientIds !== undefined)
 setWorkedAtClientIds(patch.workedAtClientIds);
 if (patch.recruitmentIds !== undefined) setRecruitmentIds(patch.recruitmentIds);
 if (patch.recruitmentMatch !== undefined)
 setRecruitmentMatch(patch.recruitmentMatch);
 if (patch.experienceMin !== undefined) setExperienceMin(patch.experienceMin);
 if (patch.experienceMax !== undefined) setExperienceMax(patch.experienceMax);
 if (patch.rateMin !== undefined) setRateMin(patch.rateMin);
 if (patch.rateMax !== undefined) setRateMax(patch.rateMax);
 if (patch.stageMovedByIds !== undefined) setStageMovedByIds(patch.stageMovedByIds);
 if (patch.stageMovedAfter !== undefined) setStageMovedAfter(patch.stageMovedAfter);
 if (patch.stageMovedBefore !== undefined)
 setStageMovedBefore(patch.stageMovedBefore);
 if (patch.stageClientIds !== undefined) setStageClientIds(patch.stageClientIds);
 if (patch.sentToClientFrom !== undefined)
 setSentToClientFrom(patch.sentToClientFrom);
 if (patch.sentToClientTo !== undefined)
 setSentToClientTo(patch.sentToClientTo);
 if (patch.stageCurrentOnly !== undefined)
 setStageCurrentOnly(patch.stageCurrentOnly);
 if (patch.openTo !== undefined) setOpenToFilter(patch.openTo);
 if (patch.recentlyChangedJobs !== undefined)
 setRecentlyChangedJobs(patch.recentlyChangedJobs);
 if (patch.semanticsVersion !== undefined)
 setSemanticsVersion(patch.semanticsVersion);
 if (patch.savedSearchId !== undefined)
 setActiveSavedSearchId(patch.savedSearchId);
 if (patch.qAll !== undefined) setQAll(patch.qAll);
 if (patch.qAny !== undefined) setQAny(patch.qAny);
 if (patch.qNone !== undefined) setQNone(patch.qNone);
 const extras = pickTraffitExtrasPatch(patch);
 if (extras) setTraffitExtras((prev) => ({ ...prev, ...extras }));
 };

 // „Wstecz"/„Dalej" w przeglądarce przywraca filtry z adresu wpisu.
 const applyFiltersPatchRef = useRef(applyFiltersPatch);
 applyFiltersPatchRef.current = applyFiltersPatch;
 useEffect(() => {
 const onPopState = () => {
 if (window.location.pathname !== CANDIDATES_LIST_PATH) return;
 const decoded: Partial<CandidateFilters> = decodeFilters(
 new URLSearchParams(window.location.search),
 );
 delete decoded.view;
 const current = lastSyncedFiltersRef.current;
 if (current && filtersEqual({ ...current, ...decoded }, current)) return;
 restoringHistoryRef.current = true;
 // „Wstecz” do gołego wpisu listy to cofnięcie filtra, nie powrót z innej strony.
 skipRouteRestoreRef.current = true;
 applyFiltersPatchRef.current(decoded);
 requestApply();
 };
 window.addEventListener("popstate", onPopState);
 return () => window.removeEventListener("popstate", onPopState);
 }, [requestApply]);

 // Współdzielone przez szufladę „Filtry" i skróty w pasku narzędzi.
 const patchFiltersFromFields = (patch: Partial<CandidateFilters>) =>
 applyFiltersPatch({ ...patch, page: 1 });
 const stageFilterValue: StageFilterValue = {
 stages: pipelineStageFilter,
 currentOnly: stageCurrentOnly,
 clientIds: stageClientIds,
 movedByIds: stageMovedByIds,
 movedAfter: stageMovedAfter,
 movedBefore: stageMovedBefore,
 };
 const onStageFilterChange = (patch: Partial<StageFilterValue>) => {
 if (patch.stages !== undefined) setPipelineStageFilter(patch.stages);
 if (patch.currentOnly !== undefined) setStageCurrentOnly(patch.currentOnly);
 if (patch.clientIds !== undefined) setStageClientIds(patch.clientIds);
 if (patch.movedByIds !== undefined) setStageMovedByIds(patch.movedByIds);
 if (patch.movedAfter !== undefined) setStageMovedAfter(patch.movedAfter);
 if (patch.movedBefore !== undefined) setStageMovedBefore(patch.movedBefore);
 setPage(1);
 };
 const hasActiveCriteria = Boolean(search) || totalActiveFilters > 0;

 // Reset kompletu filtrów („Wyczyść wszystko" w panelu). Obejmuje też pola
 // spoza CandidateFilters (open_to, recently_changed_jobs) oraz proste „q".
 // Sortowanie i ustawienia widoku zostają bez zmian.
 const resetAllFilters = () => {
 setSearch("");
 setSearchDraft("");
 setStatusFilter([]);
 setEmploymentFilter([]);
 setAvailabilityFilter([]);
 setPipelineStageFilter([]);
 setOpenToFilter([]);
 setRemoteFilter([]);
 setSkillExpr("");
 setSkillsPreferred([]);
 setHideUnknown(false);
 setLocationScope("");
 setLocationFilter("");
 setPoolIds([]);
 setCompetenceCategoryIds([]);
 setAddedByIds([]);
 setCurrentCompanyFilter([]);
 setPastCompanyFilter([]);
 setCurrentTitleFilter([]);
 setWorkedAtClientIds([]);
 setRecruitmentIds([]);
 setRecruitmentMatch("assigned");
 setExperienceMin(null);
 setExperienceMax(null);
 setRateMin(null);
 setRateMax(null);
 setStageMovedByIds([]);
 setStageMovedAfter("");
 setStageMovedBefore("");
 setStageClientIds([]);
 setSentToClientFrom("");
 setSentToClientTo("");
 setStageCurrentOnly(false);
 setRecentlyChangedJobs(null);
 setSemanticsVersion(2);
 setLanguages([]);
 setTextMode("auto");
 setQAll([]);
 setQAny([]);
 setQNone([]);
 setTraffitExtras(pickTraffitExtras(DEFAULT_FILTERS));
 // Wyczyszczone filtry to już nie jest zapisane wyszukiwanie — „Nowy" gaśnie.
 setNewMatchIds(new Set());
 setNewSince(null);
 setPage(1);
 };

 // Memo: tłumaczenie `detail` loguje surowy błąd walidacji — raz na błąd, nie
 // przy każdym renderze. Tekst, nigdy obiekt: tablica z 422 wywracała listę (React #31).
 const queryErrorDetail = useMemo(
 () =>
 apiErrorMessage(
 candidatesError,
 "Nie udało się pobrać kandydatów. Sprawdź połączenie i spróbuj ponownie.",
 ),
 [candidatesError],
 );
 const queryErrorPanel = (
 <div
 role="alert"
 className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center"
 >
 <XCircle className="h-9 w-9 text-destructive" aria-hidden="true" />
 <div>
 <p className="font-medium text-foreground">Nie udało się wczytać listy</p>
 <p className="mt-1 max-w-lg text-sm text-muted-foreground">
 {queryErrorDetail}
 </p>
 </div>
 <Button variant="outline" size="sm" onClick={() => void refetchCandidates()}>
 Spróbuj ponownie
 </Button>
 </div>
 );
 // Pusty wynik: przy aktywnych filtrach mówimy wprost, że to one zawęziły
 // listę, i dajemy jedno kliknięcie do ich zdjęcia.
 const emptyState = (
 <div className="py-16 text-center text-sm text-muted-foreground">
 <Users className="kids-hidden h-12 w-12 mx-auto mb-3 text-muted-foreground" />
 <span className="kids-only justify-center text-5xl mb-3 kids-anim-float" aria-hidden>🤖</span>
 {hasActiveCriteria ? (
 <>
 <p>Brak kandydatów spełniających filtry.</p>
 <Button
 variant="outline"
 size="sm"
 className="mt-3"
 onClick={() => {
 resetAllFilters();
 requestApply();
 }}
 >
 Wyczyść filtry
 </Button>
 </>
 ) : (
 <>
 Brak wyników. Zmień filtry lub{" "}
 <button
 className="text-primary hover:underline"
 onClick={() => setShowAdd(true)}
 >
 dodaj nowego kandydata
 </button>
 .
 </>
 )}
 </div>
 );
 const loadingRows = (
 <div className="space-y-1 p-3" aria-busy="true" aria-label="Ładowanie kandydatów">
 {Array.from({ length: 7 }, (_, index) => (
 <div key={index} className="flex items-center gap-4 rounded-md px-2 py-3">
 <Skeleton className="h-4 w-4" />
 <Skeleton className="h-10 w-10 rounded-full" />
 <div className="min-w-0 flex-1 space-y-2">
 <Skeleton className="h-4 w-48 max-w-full" />
 <Skeleton className="h-3 w-72 max-w-full" />
 </div>
 <Skeleton className="hidden h-8 w-32 sm:block" />
 <Skeleton className="hidden h-8 w-40 lg:block" />
 </div>
 ))}
 </div>
 );
  // Liczba całej bazy do nagłówka — osobne, tanie zapytanie (1 wiersz).
  // W oknie „Szukaj ręcznie” nagłówka nie ma, więc nie pytamy.
  const { data: baseTotalData } = useQuery({
    queryKey: CANDIDATES_BASE_TOTAL_QUERY_KEY,
    queryFn: ({ signal }) =>
      fetchCandidateListPage<CandidateListResponse>(CANDIDATES_BASE_TOTAL_PARAMS, signal),
    enabled: !embed,
    refetchOnWindowFocus: false,
    staleTime: 5 * 60_000,
  });
  const baseTotal = baseTotalData?.total ?? null;

  const skillBucketsValue: SkillBucketsValue = {
    required: [
      ...skillBuckets.must,
      ...skillBuckets.anyGroups.map((g) => g.join("|")),
    ],
    preferred: skillsPreferred,
    excluded: skillBuckets.none,
  };
  const canExport = hasRole(currentUser, ...EXPORT_ROLES);
  const sortContext = candidatesListFiltersForQuery(
    filtersSnapshot,
    embedJobId != null ? { jobId: embedJobId } : null,
  );
  const shownSort = effectiveSort(sortContext);
  const hasText = applied.q.trim().length >= 2;
  const canMatch = matchSortAvailable(sortContext);
  const sortOptions = (["match", "relevance", "newest", "oldest", "name"] as const).filter(
    (value) =>
      (value !== "relevance" || hasText || sortBy === "relevance") &&
      (value !== "match" || canMatch || sortBy === "match"),
  );
  const pastedRequest = looksLikePastedRequest(searchDraft);

  const openDetailAt = (candidateId: number) => {
    setDetailId(candidateId);
    const idx = items.findIndex((c) => c.id === candidateId);
    if (idx >= 0) setDetailPosition((resultsPage - 1) * pageSize + idx + 1);
  };

  const filterBar = (
    <CandidateFilterBar
      filters={filtersSnapshot}
      onPatch={patchFiltersFromFields}
      currentUserId={currentUser?.id ?? null}
      skills={skillBucketsValue}
      onSkillsChange={applySkillBuckets}
      stage={stageFilterValue}
      onStageChange={onStageFilterChange}
      phrases={{ all: qAll, any: qAny, none: qNone }}
      activeCount={totalActiveFilters}
      onClearAll={resetAllFilters}
      resultLabel={isLoading ? undefined : candidatesCountLabel(total)}
      pendingCount={pendingCount}
      onSearch={runSearch}
      recruitmentFilterLocked={forJob}
      keywordsSourceNote={embed?.keywordsNote}
    />
  );

  return (
    <div className="mx-auto max-w-[2400px] space-y-4">
      {!embed && (
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Kandydaci</h1>
          {baseTotal !== null && (
            <span className="text-sm text-muted-foreground">
              {baseTotal.toLocaleString("pl-PL")} w bazie
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline">
                <Upload className="h-4 w-4" /> Importuj <ChevronDown className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-60">
              <DropdownMenuItem onSelect={() => setShowImport(true)}>
                <Upload className="h-4 w-4" /> Import CSV
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setShowAddFromCV(true)}>
                <Sparkles className="h-4 w-4" /> Dodaj z CV
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link href="/candidates/bulk-import">
                  <FileArchive className="h-4 w-4" /> Masowy import CV
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setShowInvite(true)}>
                <LinkIcon className="h-4 w-4" /> Wygeneruj link
              </DropdownMenuItem>
              {canExport && (
                <>
                  {/* Eksport CAŁEGO wyniku (nie tylko zaznaczenia) — role jak w
                      `CANDIDATE_EXPORT_ROLES`; backend zwraca 403 pozostałym. */}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => void doExport("csv", "filtered")}>
                    <Download className="h-4 w-4" /> Eksportuj wyniki (CSV)
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => void doExport("xlsx", "filtered")}>
                    <FileText className="h-4 w-4" /> Eksportuj wyniki (XLSX)
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" variant="primary" onClick={() => setShowAdd(true)}>
            <Plus className="h-4 w-4" />
            Dodaj kandydata
          </Button>
        </div>
      </div>
      )}

      <div>
        <div className="min-w-0 space-y-3">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <div className="min-w-[240px] flex-1">
                <Input
                  leadingIcon={<Search className="h-4 w-4" />}
                  placeholder="Nazwisko, e-mail, telefon albo opis, kogo szukasz…"
                  aria-label="Szukaj kandydatów"
                  className="h-10 rounded-lg"
                  value={searchDraft}
                  onChange={(e) => setSearchDraft(e.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") runSearch();
                  }}
                />
              </div>
              {onRequestSearch && (
                <Button
                  variant="outline"
                  className="h-10"
                  onClick={() => setRequestOpen(true)}
                  title="Wklej request klienta, wgraj profil Championa albo wybierz rekrutację"
                  data-help="candidates.list.request"
                >
                  <FileText className="h-4 w-4" /> Z requestu
                </Button>
              )}
            </div>
            {pastedRequest && onRequestSearch ? (
              <p className="text-xs text-muted-foreground">
                To wygląda na treść requestu.{" "}
                <button
                  type="button"
                  className="font-medium text-primary underline-offset-2 hover:underline"
                  onClick={() => setRequestOpen(true)}
                >
                  Szukaj z requestu
                </button>
              </p>
            ) : hasText && data ? (
              <ListSearchInterpretation
                applied={data.text_mode_applied}
                interpretation={data.interpretation}
                degraded={data.search_degraded === true}
                capReached={data.result_cap_reached === true}
                textMode={textMode}
                onTextModeChange={(mode) => {
                  setTextMode(mode);
                  setPage(1);
                  requestApply();
                }}
              />
            ) : null}
            {data?.sort_applied === "newest" && effectiveSort(queryFilters) === "match" ? (
              <p className="text-xs text-muted-foreground" role="status">
                Kolejność według dopasowania jest chwilowo niedostępna — pokazujemy najnowszych.
              </p>
            ) : null}
            {convertedText && applied.q === "" ? (
              <p className="text-xs text-muted-foreground" role="status">
                Czytam jako wymagania: {convertedText.skills.join(", ")}.{" "}
                <button
                  type="button"
                  className="font-medium text-primary underline-offset-2 hover:underline"
                  onClick={searchByMeaning}
                >
                  Szukaj „{convertedText.text}” po znaczeniu
                </button>
              </p>
            ) : null}
          </div>

          {restoredBanner && (
            <div
              role="status"
              className={cn(
                "flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm",
                initialList.seedChanged
                  ? "border-warning/40 bg-warning-muted text-warning-muted-foreground"
                  : "border-success/30 bg-success-muted text-success-muted-foreground",
              )}
            >
              <History className="h-4 w-4 shrink-0" aria-hidden />
              {embed ? (
                <span className="min-w-0 flex-1">
                  <strong className="font-semibold">
                    Przywrócono Twoje ostatnie wyszukiwanie w tej rekrutacji
                  </strong>
                  {initialList.restoredAt
                    ? ` (${new Date(initialList.restoredAt).toLocaleString("pl-PL", {
                        day: "2-digit",
                        month: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                      })})`
                    : ""}
                  .
                  {initialList.seedChanged &&
                    " Wymagania rekrutacji zmieniły się od tego czasu."}
                </span>
              ) : (
                <span className="min-w-0 flex-1">
                  <strong className="font-semibold">Wróciłeś do swojego wyszukiwania.</strong>{" "}
                  Filtry, strona i miejsce na liście są takie, jak je zostawiłeś.
                </span>
              )}
              <Button variant="outline" size="sm" onClick={startNewSearch}>
                {embed ? "Wróć do filtrów z rekrutacji" : "Nowe wyszukiwanie"}
              </Button>
              <button
                type="button"
                aria-label="Zamknij informację"
                onClick={() => setRestoredBanner(false)}
                className="hit-area rounded-sm p-0.5 hover:bg-foreground/10"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          )}

          {filterBar}

          {pendingCount > 0 && (
            <div
              role="status"
              className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              <span className="min-w-0 flex-1">
                <strong className="font-semibold">
                  {pendingCount === 1
                    ? "1 zmiana czeka na „Szukaj”"
                    : `${pendingCount} zmian${pendingCount < 5 ? "y czekają" : " czeka"} na „Szukaj”`}
                </strong>{" "}
                — tabela pokazuje jeszcze wyniki dla poprzednich filtrów.
              </span>
              <Button variant="outline" size="sm" onClick={undoPending}>
                Cofnij zmiany
              </Button>
              <Button variant="primary" size="sm" onClick={runSearch}>
                <Search className="h-4 w-4" aria-hidden /> Szukaj
              </Button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2" aria-live="polite">
            <span className="text-sm font-medium text-foreground">
              {isLoading
                ? "Ładowanie…"
                : isError && items.length === 0
                  ? "Nie udało się pobrać danych"
                  : candidatesCountLabel(total)}
            </span>
            {isFetching && !isLoading && (
              <span className="text-xs text-muted-foreground">aktualizuję…</span>
            )}
            <ActiveFilterChips
              filters={filtersSnapshot}
              onUpdate={applyFiltersPatch}
              omitKey={isChipShownOnFilterBar}
            />
            <div className="ml-auto flex flex-wrap items-center gap-2" data-help="candidates.list.saved">
              <RecentSearchesMenu
                kind={embed ? "job" : "list"}
                jobId={embedJobId}
                onPick={(entry) => {
                  const decoded: Partial<CandidateFilters> = decodeFilters(
                    new URLSearchParams(entry.query),
                  );
                  delete decoded.view;
                  applyFiltersPatch({ ...decoded, page: 1, savedSearchId: null });
                  requestApply();
                  clearSelection();
                }}
              />
              {!embed && (
              <SavedSearchesMenu
                currentQs={encodeFilterCriteria(applied).toString()}
                onApply={(qs, ssId, previousViewedAt, newCandidateIds) => {
                  setNewSince(previousViewedAt);
                  setNewMatchIds(new Set(newCandidateIds));
                  const decoded = filtersFromCandidateSavedSearch({ qs }, "list");
                  applyFiltersPatch({
                    ...decoded,
                    page: 1,
                    savedSearchId: ssId,
                  });
                  requestApply();
                  clearSelection();
                }}
              />
              )}
              <Select
                value={shownSort}
                onValueChange={(value) => {
                  const next = value as CandidateFilters["sort"];
                  rememberRef.current = true;
                  setSortBy(next);
                  setSortExplicit(next === "newest");
                }}
              >
                <SelectTrigger aria-label="Sortowanie kandydatów" className="h-9 w-[170px] rounded-md">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sortOptions.map((value) => (
                    <SelectItem key={value} value={value}>
                      {sortLabel(value, embedJobId != null)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="md" aria-label="Wybierz kolumny tabeli" data-help="candidates.list.columns">
                    <Columns3 className="h-4 w-4" aria-hidden />
                    Kolumny
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  <DropdownMenuLabel>Kolumny w tabeli</DropdownMenuLabel>
                  {selectableCandidateColumns({ forJob }).filter((col) => !col.required).map((col) => (
                    <DropdownMenuCheckboxItem
                      key={col.id}
                      checked={visibleColumns.some((v) => v.id === col.id)}
                      // Menu zostaje otwarte — zwykle przełącza się kilka kolumn naraz.
                      onSelect={(e) => e.preventDefault()}
                      onCheckedChange={() =>
                        setColumnPreference(
                          columnPrefsKey,
                          toggleCandidateColumn(hiddenColumns, col.id, { forJob }),
                        )
                      }
                    >
                      {col.label}
                    </DropdownMenuCheckboxItem>
                  ))}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onSelect={() => clearColumnPreference(columnPrefsKey)}>
                    Przywróć domyślne
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

          {!embed && (
          <PinnedCandidatesBar
            onOpenCandidate={(id) => {
              setDetailId(id);
              const idx = items.findIndex((c) => c.id === id);
              // Przypięty spoza bieżącej strony nie ma pozycji na liście —
              // podgląd bez „poprzedni/następny".
              setDetailPosition(idx >= 0 ? (resultsPage - 1) * pageSize + idx + 1 : 0);
            }}
          />
          )}

          {listViewState === "refresh-error" && (
            <div
              role="alert"
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm"
            >
              <span className="text-destructive">
                Nie udało się odświeżyć wyników. Wyświetlam poprzednie dane.
              </span>
              <Button variant="outline" size="sm" onClick={() => void refetchCandidates()}>
                Spróbuj ponownie
              </Button>
            </div>
          )}

          <div
            className={cn(
              "overflow-hidden rounded-lg border border-border bg-card transition-opacity",
              pendingCount > 0 && "opacity-50",
            )}
          >
            {/* Jeden kontener przewija w obu osiach: nagłówek jest przyklejony
                u góry, kolumna „Kandydat” (poniżej lg) przy lewej krawędzi.
                Na telefonie kontener nie ma własnej wysokości — przewija się
                strona, a nie zagnieżdżony obszar. */}
            <div
              ref={parentRef}
              data-testid="candidate-list-scroll"
              onScroll={onListScroll}
              className="relative overflow-auto md:h-[calc(100dvh-300px)] md:min-h-[360px]"
            >
            {/* Nagłówek kolumn to zwykłe etykiety, bez ról tabeli: wiersze są
                `role="group"` (checkbox i przyciski w środku), a połowiczne
                role `row`/`columnheader` bez `table` łamią ARIA (axe:
                aria-required-parent / aria-required-children). */}
            <div
              className="sticky top-0 z-20 bg-card"
              style={{ minWidth: `${gridLayout.minWidth}px` }}
            >
            <div
              data-testid="candidate-list-header"
              className="grid h-10 items-center gap-3 border-b border-border bg-muted/60 px-4 text-xs font-semibold text-muted-foreground"
              style={{ gridTemplateColumns: gridLayout.template }}
            >
              <div className="flex items-center">
                <Checkbox
                  checked={
                    allVisibleSelected ? true : visibleSelectedCount > 0 ? "indeterminate" : false
                  }
                  onCheckedChange={selectAllVisible}
                  aria-label="Zaznacz stronę"
                />
              </div>
              {visibleColumns.map((col) => (
                <div
                  key={col.id}
                  data-column-header
                  className={cn(
                    "truncate",
                    col.id === "candidate" &&
                      "max-lg:sticky max-lg:left-0 max-lg:z-[1] max-lg:-ml-2 max-lg:self-stretch max-lg:bg-muted max-lg:pl-2 max-lg:leading-10",
                  )}
                >
                  {col.label}
                </div>
              ))}
            </div>
            </div>

              {listViewState === "initial-loading" ? (
                loadingRows
              ) : listViewState === "error" ? (
                queryErrorPanel
              ) : listViewState === "empty" ? (
                emptyState
              ) : (
                <div
                  style={{
                    height: `${virtualizer.getTotalSize()}px`,
                    width: "100%",
                    minWidth: `${gridLayout.minWidth}px`,
                    position: "relative",
                  }}
                >
                  {virtualizer.getVirtualItems().map((virtualRow) => {
                    const candidate = items[virtualRow.index];
                    const fullName =
                      `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() || "Kandydat";
                    const initials = getCandidateInitials(candidate) || "?";
                    const isSelected = selectedIds.has(candidate.id);
                    // Wiersz nowy od ostatniego otwarcia zapisanego wyszukiwania —
                    // nowy kandydat albo istniejący, który wszedł do zbioru (log
                    // alertów). Samo `updated_at` odpadło: nocny import Traffita
                    // rusza tysiące wierszy i każdy świecił jako „Nowy”.
                    const isNewMatch =
                      newMatchIds.has(candidate.id) ||
                      (newSinceTs !== null &&
                        !!candidate.created_at &&
                        Date.parse(candidate.created_at) > newSinceTs);
                    const position = (resultsPage - 1) * pageSize + virtualRow.index + 1;
                    const openDetail = () => openDetailAt(candidate.id);
                    const snippet = hasSearchTerms ? candidate.match_snippet : null;
                    const fieldSnippets = hasSearchTerms ? candidate.match_snippets ?? [] : [];
                    const jobTitle = getCurrentTitle(candidate);
                    const company = getCurrentCompany(candidate);
                    const location = formatCandidateLocation(candidate.city ?? candidate.location ?? null);
                    const availability = availabilityCellText(candidate);
                    const rate = rateCellText(candidate);
                    return (
                      <div
                        key={candidate.id}
                        data-testid={candidateRowTestId(candidate.id)}
                        data-index={virtualRow.index}
                        onClick={openDetail}
                        // Wiersz jest celem klawiatury (UAT B22): Enter/Spacja
                        // otwiera podgląd, po zamknięciu fokus tu wraca.
                        role="group"
                        aria-label={`${fullName} — Enter otwiera podgląd`}
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.target !== e.currentTarget || !isRowActivationKey(e.key)) return;
                          e.preventDefault();
                          openDetail();
                        }}
                        style={{
                          position: "absolute",
                          top: 0,
                          left: 0,
                          width: "100%",
                          height: `${virtualRow.size}px`,
                          transform: `translateY(${virtualRow.start - LIST_HEADER_HEIGHT}px)`,
                        }}
                        className={cn(
                          // `overflow-clip`, nie `hidden`: `hidden` robi z wiersza
                          // kontener przewijania i przyklejona kolumna „Kandydat”
                          // przestawała się przyklejać.
                          "group flex cursor-pointer flex-col overflow-clip border-b border-border transition-colors",
                          "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                          isNewMatch ? "bg-success-muted/40" : "bg-card",
                          candidate.id === lastOpenedId && "bg-primary/5 shadow-[inset_3px_0_0_var(--primary)]",
                          "hover:bg-muted/50",
                          isSelected && "bg-primary/5!",
                        )}
                      >
                        <div
                          className="grid shrink-0 items-center gap-3 px-4"
                          style={{ gridTemplateColumns: gridLayout.template, height: `${ROW_HEIGHT}px` }}
                        >
                          <div className="flex items-center" onClick={(e) => e.stopPropagation()}>
                            <Checkbox
                              checked={isSelected}
                              onCheckedChange={() => toggleId(candidate.id)}
                              aria-label={`Zaznacz ${fullName}`}
                            />
                          </div>
                          {visibleColumns.map((col) => {
                            const cell = (() => {
                              switch (col.id) {
                                case "candidate":
                                  return (
// Poniżej lg kolumna „Kandydat” jest przyklejona przy lewej krawędzi —
// po przewinięciu w bok dalej widać, czyj to telefon i stawka.
<div className="flex min-w-0 items-center gap-3 max-lg:sticky max-lg:left-0 max-lg:z-[1] max-lg:-ml-2 max-lg:self-stretch max-lg:bg-card max-lg:pl-2">
                            <Avatar size="sm">
                              <AvatarFallback className={avatarColorClass(candidate.id)}>
                                {initials}
                              </AvatarFallback>
                            </Avatar>
                            <div className="min-w-0">
                              <div className="flex min-w-0 items-center gap-1.5">
                                <Link
                                  href={`/candidates/${candidate.id}?${encodeNavContext(queryFilters, position).toString()}`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    if (!embed) {
                                      writeListSearch({ query: memoryQuery, lastOpenedId: candidate.id });
                                    }
                                  }}
                                  className="min-w-0 truncate font-medium text-foreground hover:text-primary hover:underline"
                                  title={fullName}
                                >
                                  {fullName}
                                </Link>
                                {/* Kategoria kompetencji jest w podglądzie i profilu —
                                    w wierszu zabierała miejsce nazwisku. */}
                                {isNewMatch ? (
                                  <Badge size="sm" variant="success" className="shrink-0">
                                    Nowy
                                  </Badge>
                                ) : null}
                                {candidate.id === lastOpenedId ? (
                                  <Badge size="sm" variant="info" className="shrink-0">
                                    Ostatnio otwarta
                                  </Badge>
                                ) : null}
                                {contactFeature.enabled ? (
                                  <ContactStatusBadge contactCase={candidate.contact_case} className="shrink-0" />
                                ) : null}
                              </div>
                              <p className="truncate text-xs text-muted-foreground" title={location ?? undefined}>
                                {location ?? "brak lokalizacji"}
                              </p>
                            </div>
                          </div>
                                  );
                                case "position":
                                  return (
<div className="min-w-0">
                            {jobTitle ? (
                              <>
                                <p className="truncate text-sm text-foreground" title={jobTitle}>
                                  {jobTitle}
                                </p>
                                {company && (
                                  <p className="truncate text-xs text-muted-foreground" title={company}>
                                    {company}
                                  </p>
                                )}
                              </>
                            ) : (
                              <Missing />
                            )}
                          </div>
                                  );
                                case "phone":
                                  return (
<div className="min-w-0">
                            <CandidatePhoneCell phone={candidate.phone} candidateName={fullName} />
                          </div>
                                  );
                                case "rate":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground" title="Stawka z profilu kandydata">
                            {rate ?? <Missing />}
                          </div>
                                  );
                                case "availability":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground">
                            {availability ?? <Missing />}
                          </div>
                                  );
                                case "process":
                                  return (
<div className="min-w-0" onClick={(e) => e.stopPropagation()}>
                            <CandidateProcessCell
                              candidateName={fullName}
                              employment={candidate.employment}
                              recruitments={candidate.active_recruitments}
                            />
                          </div>
                                  );
                                case "cv":
                                  return (
<div className="min-w-0">
                            <CandidateCvCell
                              candidateId={candidate.id}
                              candidateName={fullName}
                              hasCv={candidate.has_cv_document ?? Boolean(candidate.cv_filename)}
                            />
                          </div>
                                  );
                                case "fit":
                                  return (
<div className="flex">
                            <FitScoreCell
                              candidateId={candidate.id}
                              score={matchScores.scores[String(candidate.id)]}
                              failure={matchScores.failures[String(candidate.id)]}
                              answered={Boolean(matchScores.breakdowns[String(candidate.id)])}
                              onVisible={matchScores.onRowVisible}
                              onRetry={matchScores.retry}
                            />
                          </div>
                                  );
                                case "assign":
                                  return embed ? (
<div className="flex">
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 gap-1 border-primary/40 bg-primary/5 px-2 text-primary hover:bg-primary hover:text-primary-foreground"
                              disabled={embed.readOnly || addingIds.has(candidate.id)}
                              onClick={(e) => {
                                e.stopPropagation();
                                void addToEmbedJob([candidate.id]);
                              }}
                              aria-label={`Dodaj ${fullName} do Nowych`}
                              title={`Dodaj do „Nowych” w „${embed.jobTitle}”`}
                            >
                              <UserPlus className="h-3.5 w-3.5" aria-hidden />
                              {addingIds.has(candidate.id) ? "Dodaję…" : "Dodaj"}
                            </Button>
                          </div>
                                  ) : (
<div className="flex">
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 gap-1 border-primary/40 bg-primary/5 px-2 text-primary hover:bg-primary hover:text-primary-foreground"
                              onClick={(e) => {
                                e.stopPropagation();
                                setAssignFor({ id: candidate.id, name: fullName });
                              }}
                              aria-label={`Przypisz ${fullName} do rekrutacji`}
                              title="Przypisz do rekrutacji"
                            >
                              <UserPlus className="h-3.5 w-3.5" aria-hidden />
                              Rekrutacja
                            </Button>
                          </div>
                                  );
                                case "email":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground" title={candidate.email ?? undefined}>
                            {candidate.email ?? <Missing />}
                          </div>
                                  );
                                case "location":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground" title={location ?? undefined}>
                            {location ?? <Missing />}
                          </div>
                                  );
                                case "experience":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground">
                            {candidate.years_it_experience != null ? `${candidate.years_it_experience} lat` : <Missing />}
                          </div>
                                  );
                                case "last_contact":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground">
                            {formatShortDate(candidate.last_contacted_at) ?? <Missing />}
                          </div>
                                  );
                                case "added":
                                  return (
<div className="min-w-0 truncate text-sm text-foreground">
                            {formatShortDate(candidate.created_at) ?? <Missing />}
                          </div>
                                  );
                              }
                            })();
                            return <Fragment key={col.id}>{cell}</Fragment>;
                          })}
                        </div>
                        {/* Fragment CV, który dopasował wyszukiwanie — pod nazwiskiem. */}
                        {fieldSnippets.length > 0 ? (
                          <button
                            type="button"
                            onClick={openDetail}
                            aria-label={`${fullName} — gdzie padły szukane słowa`}
                            className="min-h-0 flex-1 overflow-hidden border-t border-border/40 px-4 pb-1.5 pt-1 text-left"
                          >
                            <FieldSnippets snippets={fieldSnippets} className="pl-12" />
                          </button>
                        ) : snippet ? (
                          <button
                            type="button"
                            onClick={openDetail}
                            className="min-h-0 flex-1 overflow-hidden border-t border-border/40 px-4 pb-1.5 pt-1 text-left"
                          >
                            <MatchSnippet
                              snippet={snippet}
                              terms={searchTerms}
                              className="block pl-12 line-clamp-3"
                            />
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {!isLoading && items.length > 0 && (
              <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-border bg-muted/40 px-4 py-2 text-sm">
                <span className="whitespace-nowrap text-muted-foreground">
                  {(resultsPage - 1) * pageSize + 1}–{Math.min(resultsPage * pageSize, total)} z{" "}
                  {total.toLocaleString("pl-PL")}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    value={String(candidatesPageSize)}
                    onValueChange={(value) => {
                      const next = Number(value) as CandidatesPageSize;
                      if (!CANDIDATES_PAGE_SIZES.includes(next)) return;
                      setCandidatesPageSize(next);
                      goToPage(1);
                    }}
                  >
                    <SelectTrigger aria-label="Liczba kandydatów na stronie" className="h-9 w-auto whitespace-nowrap rounded-md sm:h-8 sm:w-[152px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CANDIDATES_PAGE_SIZES.map((size) => (
                        <SelectItem key={size} value={String(size)}>
                          {size} na stronie
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={resultsPage <= 1}
                    onClick={() => goToPage(Math.max(1, resultsPage - 1))}
                  >
                    Poprzednia
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={resultsPage >= totalPages}
                    onClick={() => goToPage(resultsPage + 1)}
                  >
                    Następna <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {embed ? (
        selectedIds.size > 0 ? (
          <div
            role="region"
            aria-label="Akcje zaznaczonych kandydatów"
            className="sticky bottom-0 z-30 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 shadow-md"
          >
            <span className="text-sm">
              <span className="font-semibold">{selectedIds.size}</span> zaznaczonych
            </span>
            <Button
              size="sm"
              variant="primary"
              className="ml-auto"
              disabled={embed.readOnly || addingIds.size > 0}
              onClick={() => void addToEmbedJob(Array.from(selectedIds))}
            >
              <UserPlus className="h-3.5 w-3.5" aria-hidden /> Dodaj {selectedIds.size} do Nowych
            </Button>
            <Button size="sm" variant="ghost" onClick={clearSelection}>
              Wyczyść
            </Button>
          </div>
        ) : null
      ) : (
      <CandidateBulkBar
        count={selectedIds.size}
        onAddToRecruitment={() => setShowBulkRecruitment(true)}
        onCompare={() =>
          // Link niesie kontekst listy — „Wróć do kandydatów" oddaje filtry,
          // stronę i zaznaczenie (UAT B21).
          router.push(encodeCompareHref(applied, Array.from(selectedIds)))
        }
        onDownloadCvs={() => void doBulkDownloadCvs()}
        downloadingCvs={isDownloadingZip}
        onAddToPool={() => setShowBulkPool(true)}
        addingToPool={bulkPoolPending}
        onExportSelected={canExport ? () => void doExport("csv", "selected") : undefined}
        onClear={clearSelection}
      />
      )}

      <AddToRecruitmentDialog
        open={showBulkRecruitment}
        onOpenChange={setShowBulkRecruitment}
        candidateIds={Array.from(selectedIds)}
        source="candidate_list"
        onAdded={(result) => {
          showSuccess(addToRecruitmentSummary(result));
          clearSelection();
          // Kolumna „W procesie" pokazuje rekrutacje kandydata.
          void queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
        }}
      />

      {showBulkPool && (
        <BulkAddToPoolModal
          selectedCount={selectedIds.size}
          onCancel={() => setShowBulkPool(false)}
          onConfirm={doBulkAddToPool}
          pending={bulkPoolPending}
        />
      )}

      {onRequestSearch && (
        <RequestSearchDialog
          open={requestOpen}
          onOpenChange={setRequestOpen}
          initialText={pastedRequest ? searchDraft : ""}
          onSubmit={onRequestSearch}
        />
      )}

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
        candidateName={assignFor?.name ?? ""}
        onAssigned={() => toastOnSuccess("Kandydat przypisany.")}
      />

      {/* Szybki podgląd kandydata. */}
      <Sheet open={detailId !== null} onOpenChange={(v) => !v && setDetailId(null)}>
        <SheetContent
          side="right"
          size="lg"
          className="p-0!"
          hideClose
          // Podgląd otwiera się programowo, więc fokus wraca na wiersz ostatnio
          // oglądanego kandydata — także po nawigacji w podglądzie (UAT B22).
          onCloseAutoFocus={(e) => {
            if (focusCandidateRow(lastDetailIdRef.current)) e.preventDefault();
          }}
        >
          {detailId !== null && (
            <CandidateQuickView
              candidateId={detailId}
              onClose={() => setDetailId(null)}
              rateLookup={(id) => {
                const row = items.find((c) => c.id === id);
                return row ? rateCellText(row) : undefined;
              }}
              navigation={
                detailPosition <= 0
                  ? undefined
                  : {
                      filters: queryFilters,
                      position: detailPosition,
                      pageItems: items.map((c) => ({
                        id: c.id,
                        name: c.name,
                        lastname: c.lastname,
                      })),
                      total,
                      // Przy keepPreviousData strona odpowiedzi może być inna niż
                      // strona kontrolek — nawigacja liczy z odpowiedzi.
                      pageNumber: data?.page ?? resultsPage,
                      pageSize,
                      onNavigate: ({ candidateId, position }) => {
                        setDetailId(candidateId);
                        setDetailPosition(position);
                        // Lista idzie za nawigacją, żeby po zamknięciu podglądu
                        // stała na stronie, na której ta się skończyła.
                        const nextListPage = Math.floor((position - 1) / pageSize) + 1;
                        if (nextListPage !== resultsPage) goToPage(nextListPage);
                      },
                    }
              }
            />
          )}
        </SheetContent>
      </Sheet>

      {showToast && (
        <div className="fixed bottom-4 right-4 z-9999 rounded-lg bg-card px-4 py-3 text-sm text-foreground shadow-md">
          {showToast}
        </div>
      )}
    </div>
  );
}

// ── Bulk add-to-pool modal (Phase „Otwartość" Faza 2.5) ─────────────────────

export function BulkAddToPoolModal({
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
 const currentUser = useAuthStore((s) => s.user);
 const isAdmin = hasRole(currentUser, "admin");
 const { data, isLoading, isError, error, isSuccess, refetch } = useQuery({
 queryKey: ["talent-pools","bulk-modal"],
 queryFn: () => api.get("/api/talent-pools").then((r) => r.data),
 });
 const pools: Array<{
 id: number;
 name: string;
 candidate_count: number;
 is_personal?: boolean;
 owner_id?: number | null;
 owner_name?: string | null;
 }> = Array.isArray(data) ? data : data?.items ?? [];
 // Pula osobista innego usera = tylko podgląd (backend zwróci 403 na bulk-add).
 // Pokazujemy ją (jest team-visible), ale wyłączoną + z oznaczeniem właściciela.
 const canUsePool = (p: { is_personal?: boolean; owner_id?: number | null }) =>
 !p.is_personal || isAdmin || p.owner_id === (currentUser?.id ?? -1);
 const filtered = pools.filter((p) =>
 p.name.toLowerCase().includes(filter.toLowerCase())
 );
 // Awaria pobrania NIE może wyglądać jak „Brak pul” — pusta lista czyta się
 // jak brak danych, a rekruter zakładałby duplikat puli.
 const poolsView = resolveViewState({
 isLoading,
 isError,
 error,
 isEmpty: pools.length === 0,
 isSuccess,
 });

 return (
 <div
 className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/50 p-4"
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
 <div className="max-h-[50dvh] overflow-y-auto space-y-1">
 {poolsView === "loading" && (
 <div className="text-xs text-muted-foreground py-4 text-center">Ładowanie pul…</div>
 )}
 {isBlockingViewState(poolsView) && (
 <QueryStateNotice
 state={poolsView as "forbidden" | "not_found" | "error"}
 description={
 poolsView === "error"
 ? "Nie udało się pobrać listy pul. Pule mogą istnieć — spróbuj ponownie."
 : undefined
 }
 onRetry={() => void refetch()}
 className="py-6"
 />
 )}
 {(poolsView === "empty" || poolsView === "ready") && filtered.length === 0 && (
 <div className="text-xs text-muted-foreground py-4 text-center">
 {pools.length === 0 ? "Nie ma jeszcze żadnej puli." : `Brak pul dla „${filter}".`}{" "}
 <Link href="/talents" className="underline">Stwórz nową</Link>.
 </div>
 )}
 {(poolsView === "empty" || poolsView === "ready") && filtered.map((p) => {
 const usable = canUsePool(p);
 return (
 <button
 key={p.id}
 type="button"
 onClick={() => usable && onConfirm(p.id)}
 disabled={pending || !usable}
 title={
 usable
 ? undefined
 : `Pula osobista${p.owner_name ? ` — ${p.owner_name}` : ""} (tylko podgląd)`
 }
 className="w-full text-left text-sm px-3 py-2 rounded hover:bg-muted dark:hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-between gap-2"
 >
 <span className="flex items-center gap-1.5 min-w-0">
 {!usable && <Lock className="w-3 h-3 shrink-0 text-muted-foreground" />}
 <span className="truncate">{p.name}</span>
 {p.is_personal && p.owner_name && (
 <span className="text-[11px] text-muted-foreground shrink-0">
 · {p.owner_name}
 </span>
 )}
 </span>
 <span className="text-xs text-muted-foreground shrink-0">
 {p.candidate_count} {p.candidate_count === 1 ?"kandydat" :"kandydatów"}
 </span>
 </button>
 );
 })}
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
