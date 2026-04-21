"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Briefcase,
  ChevronRight,
  Download,
  Filter,
  GitCompare,
  Globe,
  Linkedin,
  Plus,
  Rows3,
  Search,
  Target,
  Upload,
  Users,
  X,
} from "lucide-react";
import api from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import { AddCandidateModal } from "@/components/AppShell";
import { ImportCandidatesModal } from "@/components/ImportCandidatesModal";
import { QuickAssignModal } from "@/components/QuickAssignModal";
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
  status?: string;
  location?: string;
  created_at?: string;
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

export function CandidatesListV2() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const density = useUiStore((s) => s.density);
  const setDensity = useUiStore((s) => s.setDensity);
  const parentRef = useRef<HTMLDivElement>(null);

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

  // Sync URL -----------------------------------------------------
  useEffect(() => {
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    if (statusFilter) params.set("status", statusFilter);
    if (sortBy && sortBy !== "newest") params.set("sort", sortBy);
    if (page > 1) params.set("page", String(page));
    if (remoteFilter.length) params.set("remote", remoteFilter.join(","));
    if (skillsFilter.length) params.set("skills", skillsFilter.join(","));
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/candidates?${qs}` : "/candidates");
  }, [search, statusFilter, sortBy, page, remoteFilter, skillsFilter]);

  // Data --------------------------------------------------------
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["candidates-v2", search, statusFilter, page, sortBy, remoteFilter, skillsFilter],
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
  const [assignFor, setAssignFor] = useState<{ id: number; name: string } | null>(null);
  const [showToast, setToast] = useState<string | null>(null);
  const toastOnSuccess = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
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
    (remoteFilter.length > 0 ? 1 : 0) + (skillsFilter.length > 0 ? 1 : 0);

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
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setDensity(density === "cozy" ? "compact" : "cozy")}
            title="Przełącz gęstość"
            className="h-9 w-9 flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--text-title))]"
          >
            <Rows3 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Data grid (virtualized) */}
      <div className="rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] overflow-hidden">
        {/* Header row */}
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

        {/* Virtualized body */}
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
                    <Link
                      href={`/candidates/${candidate.id}`}
                      className="flex items-center gap-3 min-w-0"
                    >
                      <Avatar size={density === "compact" ? "sm" : "md"}>
                        <AvatarFallback>{initials}</AvatarFallback>
                      </Avatar>
                      <div className="min-w-0">
                        <div className="font-medium text-[hsl(var(--text-title))] truncate">
                          {fullName}
                        </div>
                        <div className="text-xs text-[hsl(var(--text-muted))] flex items-center gap-1.5 truncate">
                          {sourceIcon(candidate.source)}
                          <span className="truncate">
                            {candidate.email ?? candidate.location ?? "—"}
                          </span>
                        </div>
                      </div>
                    </Link>
                    <div className="min-w-0">
                      <span className="text-sm text-[hsl(var(--text-body))] truncate block">
                        {candidate.position ?? candidate.current_role ?? "—"}
                      </span>
                    </div>
                    <div>
                      {candidate.status && STATUS_LABELS[candidate.status] ? (
                        <Badge
                          size="sm"
                          variant={STATUS_VARIANT[candidate.status] ?? "neutral"}
                        >
                          {STATUS_LABELS[candidate.status]}
                        </Badge>
                      ) : (
                        <span className="text-xs text-[hsl(var(--text-muted))]">—</span>
                      )}
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
                    <div className="text-xs text-[hsl(var(--text-muted))] truncate">
                      {candidate.created_at ? formatRelativeTime(candidate.created_at) : "—"}
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
      {showImport && <ImportCandidatesModal onClose={() => setShowImport(false)} />}
      {assignFor && (
        <QuickAssignModal
          candidateId={assignFor.id}
          candidateName={assignFor.name}
          onClose={() => setAssignFor(null)}
          onAssigned={() => {
            toastOnSuccess("Kandydat przypisany.");
            setAssignFor(null);
          }}
        />
      )}

      {showToast && (
        <div className="fixed bottom-4 right-4 z-[9999] px-4 py-3 rounded-v2-m shadow-v2-xl text-sm bg-[hsl(var(--bg-chrome))] text-[hsl(var(--text-onchrome))]">
          {showToast}
        </div>
      )}
    </div>
  );
}
