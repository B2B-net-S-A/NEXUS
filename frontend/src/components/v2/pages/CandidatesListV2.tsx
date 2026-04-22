"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Briefcase,
  ChevronRight,
  Columns3,
  Download,
  FileArchive,
  Filter,
  GitCompare,
  Globe,
  LayoutGrid,
  Link as LinkIcon,
  Linkedin,
  Loader2,
  Plus,
  Rows3,
  Search,
  Sparkles,
  Table2,
  Target,
  Upload,
  Users,
  X,
} from "lucide-react";
import api from "@/lib/api";
import {
  BulkCvDownloadError,
  downloadBulkCvs,
} from "@/lib/bulk-cv-download";
import { cn, formatRelativeTime } from "@/lib/utils";
import { AddCandidateModal } from "@/components/AppShell";
import { ImportCandidatesV2 } from "@/components/v2/modals/ImportCandidatesV2";
import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import { CandidateDetailV2 } from "@/components/v2/pages/CandidateDetailV2";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useUiStore } from "@/store/ui";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Kbd } from "@/components/ui/kbd";
import {
  AVAILABILITY_OPTIONS,
  CandidateHighlights,
  EMPLOYMENT_FILTER_OPTIONS,
  type AvailabilityStatus,
  type EmploymentInfo,
} from "@/components/v2/CandidateHighlights";
import { useAuthStore } from "@/store/auth";
import { LocationInput } from "@/components/v2/filters/LocationInput";
import { TalentPoolMultiSelect } from "@/components/v2/filters/TalentPoolMultiSelect";
import { AddedByMultiSelect } from "@/components/v2/filters/AddedByMultiSelect";
import { ActiveFilterChips } from "@/components/v2/filters/ActiveFilterChips";
import { decodeFilters, encodeFilters, type CandidateFilters } from "@/lib/url-filters";
import { CandidatesTiles } from "@/components/v2/pages/CandidatesTiles";
import { RequireRole } from "@/components/RequireRole";
import { SavedSearchesMenu } from "@/components/v2/filters/SavedSearchesMenu";

const STATUS_LABELS: Record<string, string> = {
  active: "Aktywny",
  passive: "Pasywny",
  blacklisted: "Zablokowany",
};

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger"> = {
  active: "success",
  passive: "warning",
  blacklisted: "danger",
};

const SORT_OPTIONS = [
  { value: "newest", label: "Najnowsi" },
  { value: "oldest", label: "Najstarsi" },
  { value: "name", label: "Nazwisko (A-Z)" },
];

interface Candidate {
  id: number;
  name?: string;
  lastname?: string;
  email?: string;
  position?: string;
  current_role?: string;
  source?: string;
  status?: "active" | "passive" | "blacklisted";
  availability_status?: AvailabilityStatus;
  employment?: EmploymentInfo;
  location?: string;
  created_at?: string;
  created_by_user?: { id: number; name: string } | null;
  match_stats?: { open_count: number; total_open: number; top_score: number };
}

function sourceIcon(source?: string) {
  if (source === "linkedin")
    return <Linkedin className="h-3.5 w-3.5" style={{ color: "#0A66C2" }} />;
  if (source === "pracuj")
    return (
      <span className="text-[10px] font-bold leading-none" style={{ color: "#FF6600" }}>
        P
      </span>
    );
  return <Globe className="h-3 w-3 text-[hsl(var(--text-muted))]" />;
}

function matchBadgeVariant(
  topScore: number
): "success" | "soft" | "neutral" | "outline" {
  if (topScore >= 75) return "success";
  if (topScore >= 50) return "soft";
  return "neutral";
}

// All columns that can be shown/hidden via the "Kolumny" popover.
const ALL_COLUMNS = [
  { id: "candidate", label: "Kandydat", required: true },
  { id: "position", label: "Pozycja", required: false },
  { id: "status", label: "Status", required: false },
  { id: "match", label: "Match", required: false },
  { id: "created", label: "Dodano", required: false },
  { id: "added_by", label: "Dodał", required: false },
] as const;
type ColumnId = (typeof ALL_COLUMNS)[number]["id"];

const HARD_DEFAULT_COLUMNS: ColumnId[] = [
  "candidate",
  "position",
  "status",
  "match",
  "created",
];

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
    queryKey: ["settings", "candidates-columns"],
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

  const saveAsGlobalDefault = useMutation({
    mutationFn: (visibleIds: ColumnId[]) =>
      api
        .put("/api/settings/candidates-columns", { columns: visibleIds })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["settings", "candidates-columns"],
      });
      setToast?.("Zapisano jako domyślne dla wszystkich.");
    },
  });
  const resetToGlobalDefault = () =>
    useUiStore.getState().clearColumnPreference("candidates-v2");

  // URL state ---------------------------------------------------
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") ?? "");
  const [sortBy, setSortBy] = useState(searchParams.get("sort") ?? "newest");
  const [page, setPage] = useState(Number(searchParams.get("page") ?? "1"));
  const [remoteFilter, setRemoteFilter] = useState<string[]>(
    searchParams.get("remote")?.split(",").filter(Boolean) ?? []
  );
  const [skillsFilter, setSkillsFilter] = useState<string[]>(
    searchParams.get("skills")?.split(",").filter(Boolean) ?? []
  );
  const [skillInput, setSkillInput] = useState("");
  const [employmentFilter, setEmploymentFilter] = useState<string>(
    searchParams.get("employment") ?? ""
  );
  const [availabilityFilter, setAvailabilityFilter] = useState<string>(
    searchParams.get("avail") ?? ""
  );
  const [locationFilter, setLocationFilter] = useState<string>(
    searchParams.get("loc") ?? ""
  );
  const [poolIds, setPoolIds] = useState<number[]>(
    (searchParams.get("pool") ?? "")
      .split(",")
      .map((x) => Number.parseInt(x, 10))
      .filter((n) => Number.isFinite(n))
  );
  const [addedByIds, setAddedByIds] = useState<number[]>(
    (searchParams.get("added_by") ?? "")
      .split(",")
      .map((x) => Number.parseInt(x, 10))
      .filter((n) => Number.isFinite(n))
  );
  const currentUser = useAuthStore((s) => s.user);

  // Sync URL -----------------------------------------------------
  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    if (statusFilter) params.set("status", statusFilter);
    if (sortBy && sortBy !== "newest") params.set("sort", sortBy);
    if (page > 1) params.set("page", String(page));
    if (remoteFilter.length) params.set("remote", remoteFilter.join(","));
    if (skillsFilter.length) params.set("skills", skillsFilter.join(","));
    if (employmentFilter) params.set("employment", employmentFilter);
    if (availabilityFilter) params.set("avail", availabilityFilter);
    if (locationFilter) params.set("loc", locationFilter);
    if (poolIds.length) params.set("pool", poolIds.join(","));
    if (addedByIds.length) params.set("added_by", addedByIds.join(","));
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/candidates?${qs}` : "/candidates");
  }, [
    search,
    statusFilter,
    sortBy,
    page,
    remoteFilter,
    skillsFilter,
    employmentFilter,
    availabilityFilter,
    locationFilter,
    poolIds,
    addedByIds,
  ]);

  // Data --------------------------------------------------------
  const { data, isLoading, isFetching } = useQuery({
    queryKey: [
      "candidates-v2",
      search,
      statusFilter,
      page,
      sortBy,
      remoteFilter,
      skillsFilter,
      employmentFilter,
      availabilityFilter,
      locationFilter,
      poolIds,
      addedByIds,
    ],
    queryFn: () =>
      api
        .get("/api/candidates", {
          params: {
            q: search || undefined,
            status: statusFilter || undefined,
            page,
            include_match_stats: true,
            match_threshold: 35,
            skills: skillsFilter.length ? skillsFilter : undefined,
            skill_combine: skillsFilter.length > 1 ? "AND" : undefined,
            remote_policy: remoteFilter.length ? remoteFilter : undefined,
            employment: employmentFilter || undefined,
            availability: availabilityFilter || undefined,
            location: locationFilter || undefined,
            talent_pool_id: poolIds.length ? poolIds : undefined,
            added_by_user_id: addedByIds.length ? addedByIds : undefined,
          },
          paramsSerializer: { indexes: null },
        })
        .then((r) => r.data),
  });

  const items: Candidate[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

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
  const [showInvite, setShowInvite] = useState(false);
  const [assignFor, setAssignFor] = useState<{ id: number; name: string } | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [showToast, setToast] = useState<string | null>(null);
  const [isDownloadingZip, setIsDownloadingZip] = useState(false);
  const toastOnSuccess = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
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
          ? e.message
          : "Pobieranie nie powiodło się."
      );
    } finally {
      setIsDownloadingZip(false);
    }
  };

  // Export
  const doExport = async (format: "csv" | "xlsx") => {
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    if (statusFilter) params.set("status", statusFilter);
    params.set("format", format);
    const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
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
    (addedByIds.length > 0 ? 1 : 0);

  // Snapshot of filters used by <ActiveFilterChips> and saved-search plumbing.
  const filtersSnapshot: CandidateFilters = useMemo(
    () => ({
      q: search,
      status: statusFilter,
      sort: (sortBy as CandidateFilters["sort"]) || "newest",
      page,
      remote: remoteFilter as CandidateFilters["remote"],
      skills: skillsFilter,
      skillCombine: "and",
      location: locationFilter,
      poolIds,
      addedByIds,
      view: "list",
      savedSearchId: null,
    }),
    [
      search,
      statusFilter,
      sortBy,
      page,
      remoteFilter,
      skillsFilter,
      locationFilter,
      poolIds,
      addedByIds,
    ]
  );
  const applyFiltersPatch = (patch: Partial<CandidateFilters>) => {
    if (patch.q !== undefined) setSearch(patch.q);
    if (patch.status !== undefined) setStatusFilter(patch.status);
    if (patch.sort !== undefined) setSortBy(patch.sort);
    if (patch.page !== undefined) setPage(patch.page);
    if (patch.remote !== undefined) setRemoteFilter(patch.remote);
    if (patch.skills !== undefined) setSkillsFilter(patch.skills);
    if (patch.location !== undefined) setLocationFilter(patch.location);
    if (patch.poolIds !== undefined) setPoolIds(patch.poolIds);
    if (patch.addedByIds !== undefined) setAddedByIds(patch.addedByIds);
  };

  return (
    <div className="max-w-[1400px] mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[hsl(var(--accent))]">
            Sourcing · Kandydaci
          </p>
          <h1 className="font-display text-3xl font-extrabold tracking-[-0.02em] text-[hsl(var(--text-title))] mt-1">
            Kandydaci
          </h1>
          <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
            {isLoading ? "Ładowanie…" : `${total.toLocaleString("pl-PL")} w bazie`}
            {isFetching && !isLoading ? " · synchronizacja…" : ""}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setShowImport(true)}>
            <Upload className="h-4 w-4" /> Import CSV
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button size="sm" variant="outline">
                <Download className="h-4 w-4" /> Eksport
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-40 p-1">
              <button
                onClick={() => doExport("csv")}
                className="block w-full text-left px-3 py-1.5 text-sm rounded-v2-s hover:bg-[hsl(var(--accent-soft))]"
              >
                CSV
              </button>
              <button
                onClick={() => doExport("xlsx")}
                className="block w-full text-left px-3 py-1.5 text-sm rounded-v2-s hover:bg-[hsl(var(--accent-soft))]"
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
        <Select value={statusFilter || "all"} onValueChange={(v) => { setStatusFilter(v === "all" ? "" : v); setPage(1); }}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Wszystkie statusy" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Wszystkie statusy</SelectItem>
            <SelectItem value="active">Aktywni</SelectItem>
            <SelectItem value="passive">Pasywni</SelectItem>
            <SelectItem value="blacklisted">Zablokowani</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={employmentFilter || "all"}
          onValueChange={(v) => {
            setEmploymentFilter(v === "all" ? "" : v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-[180px]" title="Filtruj po stanie zatrudnienia">
            <SelectValue placeholder="Zatrudnienie" />
          </SelectTrigger>
          <SelectContent>
            {EMPLOYMENT_FILTER_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={availabilityFilter || "all"}
          onValueChange={(v) => {
            setAvailabilityFilter(v === "all" ? "" : v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-[170px]" title="Filtruj po dyspozycyjności">
            <SelectValue placeholder="Dyspozycyjność" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Dowolna</SelectItem>
            {AVAILABILITY_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            // Shortcut: show everyone who can realistically be sourced right now —
            // not at a client AND explicitly open to offers (or actively looking).
            setEmploymentFilter("available");
            setAvailabilityFilter("actively_looking");
            setPage(1);
          }}
          title="Bez projektu + aktywnie szukający"
        >
          <Sparkles className="h-4 w-4" /> Dostępni do sourcingu
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
          <PopoverContent align="end" className="w-80 space-y-3">
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
                Lokalizacja
              </h3>
              <LocationInput
                value={locationFilter}
                onChange={(v) => {
                  setLocationFilter(v);
                  setPage(1);
                }}
              />
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
                Talent pool
              </h3>
              <TalentPoolMultiSelect
                value={poolIds}
                onChange={(ids) => {
                  setPoolIds(ids);
                  setPage(1);
                }}
              />
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
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
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
                Tryb pracy
              </h3>
              <div className="flex gap-1.5 flex-wrap">
                {(["remote", "hybrid", "onsite"] as const).map((v) => {
                  const active = remoteFilter.includes(v);
                  return (
                    <button
                      key={v}
                      onClick={() =>
                        setRemoteFilter((p) =>
                          p.includes(v) ? p.filter((x) => x !== v) : [...p, v]
                        )
                      }
                      className={cn(
                        "px-2.5 py-1 text-xs rounded-v2-s border transition-colors",
                        active
                          ? "bg-[hsl(var(--accent))] text-white border-[hsl(var(--accent))]"
                          : "bg-[hsl(var(--bg-surface))] text-[hsl(var(--text-body))] border-[hsl(var(--border-subtle))] hover:border-[hsl(var(--accent))]"
                      )}
                    >
                      {v === "remote" ? "Zdalnie" : v === "hybrid" ? "Hybryda" : "Stacjonarnie"}
                    </button>
                  );
                })}
              </div>
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
                Umiejętności (AND)
              </h3>
              <div className="flex gap-1.5 flex-wrap mb-2">
                {skillsFilter.map((s) => (
                  <span
                    key={s}
                    className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-[hsl(var(--accent-soft))] text-[hsl(var(--accent))]"
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
              <p className="text-[10px] text-[hsl(var(--text-muted))] mt-1">
                Enter, aby dodać. {skillsFilter.length > 1 && "Wszystkie muszą być obecne (AND)."}
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
                  setPage(1);
                }}
                className="text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))]"
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
                ? "primary"
                : "outline"
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
              sort: decoded.sort,
              page: 1,
              remote: decoded.remote,
              skills: decoded.skills,
              location: decoded.location,
              poolIds: decoded.poolIds,
              addedByIds: decoded.addedByIds,
            });
          }}
        />

        <div className="ml-auto flex items-center gap-2">
          {/* Column customization popover */}
          <Popover>
            <PopoverTrigger asChild>
              <button
                title="Konfiguracja kolumn"
                className="h-9 w-9 flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--text-title))]"
              >
                <Columns3 className="h-4 w-4" />
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-64">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[hsl(var(--text-muted))] mb-2">
                Pokazuj kolumny
              </h3>
              <div className="space-y-1.5">
                {ALL_COLUMNS.map((col) => {
                  const shown = !hiddenColumns.has(col.id);
                  return (
                    <label
                      key={col.id}
                      className="flex items-center gap-2 text-sm cursor-pointer rounded-v2-s px-1.5 py-1 hover:bg-[hsl(var(--accent-soft))]"
                    >
                      <Checkbox
                        checked={shown}
                        disabled={col.required}
                        onCheckedChange={(v) => {
                          const next = new Set(hiddenColumns);
                          if (v) next.delete(col.id);
                          else next.add(col.id);
                          setColumnPref(
                            "candidates-v2",
                            Array.from(next) as ColumnId[]
                          );
                        }}
                      />
                      <span
                        className={
                          col.required
                            ? "text-[hsl(var(--text-muted))]"
                            : "text-[hsl(var(--text-body))]"
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
              <div className="mt-3 pt-2 border-t border-[hsl(var(--border-subtle))] flex flex-col gap-1.5">
                {userOverride && (
                  <button
                    type="button"
                    onClick={resetToGlobalDefault}
                    className="text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--accent))] text-left"
                  >
                    Przywróć domyślne
                  </button>
                )}
                <RequireRole roles={["admin"]}>
                  <button
                    type="button"
                    onClick={() => {
                      const visibleIds = ALL_COLUMNS.filter(
                        (c) => !hiddenColumns.has(c.id)
                      ).map((c) => c.id as ColumnId);
                      saveAsGlobalDefault.mutate(visibleIds);
                    }}
                    disabled={saveAsGlobalDefault.isPending}
                    className="text-xs text-[hsl(var(--accent))] hover:underline text-left disabled:opacity-50"
                    title="Zapisz bieżący układ jako domyślny dla wszystkich użytkowników"
                  >
                    {saveAsGlobalDefault.isPending
                      ? "Zapisywanie…"
                      : "💾 Zapisz jako domyślne (admin)"}
                  </button>
                </RequireRole>
              </div>
            </PopoverContent>
          </Popover>
          <div
            className="flex items-center rounded-v2-s border border-[hsl(var(--border-subtle))] overflow-hidden"
            role="group"
            aria-label="Widok listy"
          >
            <button
              onClick={() => setCandidatesView("list")}
              title="Widok tabeli"
              aria-pressed={candidatesView === "list"}
              className={cn(
                "h-9 w-9 flex items-center justify-center transition-colors",
                candidatesView === "list"
                  ? "bg-[hsl(var(--accent))] text-white"
                  : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))]"
              )}
            >
              <Table2 className="h-4 w-4" />
            </button>
            <button
              onClick={() => setCandidatesView("tiles")}
              title="Widok kafelków"
              aria-pressed={candidatesView === "tiles"}
              className={cn(
                "h-9 w-9 flex items-center justify-center transition-colors",
                candidatesView === "tiles"
                  ? "bg-[hsl(var(--accent))] text-white"
                  : "text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))]"
              )}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
          </div>
          <button
            onClick={() => setDensity(density === "cozy" ? "compact" : "cozy")}
            title="Przełącz gęstość"
            className="h-9 w-9 flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--text-title))]"
          >
            <Rows3 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Active filter chips */}
      <ActiveFilterChips filters={filtersSnapshot} onUpdate={applyFiltersPatch} />

      {/* Data grid (virtualized) */}
      <div className="rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] overflow-hidden">
        {/* Header row (list view only) */}
        {candidatesView === "list" && (
        <div
          className={cn(
            "grid items-center gap-4 px-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-[hsl(var(--text-muted))] bg-[hsl(var(--bg-canvas))]/60 border-b border-[hsl(var(--border-subtle))]",
            density === "compact" ? "h-9" : "h-10",
            "grid-cols-[32px_minmax(220px,2fr)_minmax(180px,1.5fr)_minmax(120px,1fr)_minmax(140px,1fr)_minmax(100px,1fr)_60px]"
          )}
        >
          <div className="flex items-center">
            <Checkbox
              checked={
                items.length > 0 && items.every((i) => selectedIds.has(i.id))
                  ? true
                  : selectedIds.size > 0
                    ? "indeterminate"
                    : false
              }
              onCheckedChange={(v) => (v ? selectAllVisible() : clearSelection())}
              aria-label="Zaznacz wszystkie"
            />
          </div>
          <div>Kandydat</div>
          <div>Pozycja</div>
          <div>Status</div>
          <div>Match</div>
          <div>Dodano</div>
          <div />
        </div>
        )}

        {/* Virtualized body — list or tiles */}
        {candidatesView === "tiles" ? (
          items.length === 0 && !isLoading ? (
            <div className="py-16 text-center text-sm text-[hsl(var(--text-muted))]">
              <Users className="h-10 w-10 mx-auto mb-2 opacity-40" />
              Brak wyników. Zmień filtry lub{" "}
              <button
                className="text-[hsl(var(--accent))] hover:underline"
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
              onOpenDetail={(id) => setDetailId(id)}
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
            <div className="py-16 text-center text-sm text-[hsl(var(--text-muted))]">
              Ładowanie kandydatów…
            </div>
          ) : items.length === 0 ? (
            <div className="py-16 text-center text-sm text-[hsl(var(--text-muted))]">
              <Users className="h-10 w-10 mx-auto mb-2 opacity-40" />
              Brak wyników. Zmień filtry lub{" "}
              <button
                className="text-[hsl(var(--accent))] hover:underline"
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
                  `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() ||
                  "Kandydat";
                const initials = fullName
                  .split(" ")
                  .map((w) => w[0])
                  .slice(0, 2)
                  .join("")
                  .toUpperCase();
                const isSelected = selectedIds.has(candidate.id);
                const stats = candidate.match_stats;
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
                    }}
                    className={cn(
                      "grid items-center gap-4 px-4 border-b border-[hsl(var(--border-subtle))]/50 transition-colors",
                      "grid-cols-[32px_minmax(220px,2fr)_minmax(180px,1.5fr)_minmax(120px,1fr)_minmax(140px,1fr)_minmax(100px,1fr)_60px]",
                      "hover:bg-[hsl(var(--accent-soft))]/40",
                      isSelected && "bg-[hsl(var(--accent-soft))] hover:bg-[hsl(var(--accent-soft))]"
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
                    <button
                      type="button"
                      onClick={() => setDetailId(candidate.id)}
                      className="flex items-center gap-3 min-w-0 text-left"
                    >
                      <Avatar size={density === "compact" ? "sm" : "md"}>
                        <AvatarFallback>{initials}</AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="font-medium text-[hsl(var(--text-title))] truncate hover:text-[hsl(var(--accent))]">
                          {fullName}
                        </div>
                        <div className="text-xs text-[hsl(var(--text-muted))] flex items-center gap-1.5 truncate">
                          {sourceIcon(candidate.source)}
                          <span className="truncate">
                            {candidate.email ?? candidate.location ?? "—"}
                          </span>
                        </div>
                      </div>
                    </button>
                    <div className="min-w-0">
                      <span className="text-sm text-[hsl(var(--text-body))] truncate block">
                        {candidate.position ?? candidate.current_role ?? "—"}
                      </span>
                    </div>
                    <div className="min-w-0">
                      <CandidateHighlights candidate={candidate} variant="compact" />
                    </div>
                    <div>
                      {stats && stats.open_count > 0 ? (
                        <Badge
                          size="sm"
                          variant={matchBadgeVariant(stats.top_score)}
                          className="gap-1"
                        >
                          <Target className="h-3 w-3" />
                          {stats.open_count}/{stats.total_open} · top {Math.round(stats.top_score)}
                        </Badge>
                      ) : (
                        <span className="text-xs text-[hsl(var(--text-muted))]">—</span>
                      )}
                    </div>
                    <div className="min-w-0 leading-tight">
                      <div className="text-xs text-[hsl(var(--text-muted))] truncate">
                        {candidate.created_at ? formatRelativeTime(candidate.created_at) : "—"}
                      </div>
                      {!hiddenColumns.has("added_by") && (
                        <div
                          className="text-[11px] text-[hsl(var(--text-muted))] opacity-80 truncate"
                          title={
                            candidate.created_by_user
                              ? `Dodał: ${candidate.created_by_user.name}`
                              : "Import systemowy"
                          }
                        >
                          Dodał:{" "}
                          {candidate.created_by_user
                            ? candidate.created_by_user.name
                            : "System"}
                        </div>
                      )}
                    </div>
                    <div className="flex justify-end">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setAssignFor({ id: candidate.id, name: fullName });
                        }}
                        title="Przypisz do oferty"
                        className="h-8 w-8 flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--accent))]"
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
          <div className="flex items-center justify-between gap-3 px-4 h-12 border-t border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-canvas))]/40 text-sm">
            <span className="text-[hsl(var(--text-muted))]">
              Strona <span className="font-semibold text-[hsl(var(--text-title))]">{page}</span> z {totalPages}
              {selectedIds.size > 0 && (
                <>
                  {" · "}
                  <span className="font-semibold text-[hsl(var(--accent))]">
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
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-40 bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))] rounded-v2-l shadow-v2-xl border border-white/10 px-4 py-2.5 flex items-center gap-3 animate-slide-in-bottom">
          <span className="text-xs">
            Zaznaczono: <span className="font-bold">{selectedIds.size}</span>
          </span>
          <div className="h-4 w-px bg-white/15" />
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
            )}{" "}
            Pobierz CV (ZIP)
          </Button>
          <button
            onClick={clearSelection}
            className="text-xs text-[hsl(var(--text-onchrome))]/70 hover:text-[hsl(var(--text-onchrome))] ml-1"
          >
            Wyczyść
          </button>
        </div>
      )}

      {/* Keyboard hints */}
      <div className="hidden md:flex items-center gap-3 text-[10px] text-[hsl(var(--text-muted))] justify-center">
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
      <GenerateInviteLinkV2 open={showInvite} onOpenChange={setShowInvite} />
      <QuickAssignV2
        open={!!assignFor}
        onOpenChange={(v) => !v && setAssignFor(null)}
        candidateId={assignFor?.id ?? 0}
        candidateName={assignFor?.name ?? ""}
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
              />
            </div>
          )}
        </SheetContent>
      </Sheet>

      {showToast && (
        <div className="fixed bottom-4 right-4 z-[9999] px-4 py-3 rounded-v2-m shadow-v2-xl text-sm bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))]">
          {showToast}
        </div>
      )}
    </div>
  );
}
