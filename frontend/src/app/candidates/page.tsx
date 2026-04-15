"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import api from "@/lib/api";
import { SearchBar } from "@/components/SearchBar";
import { AddCandidateModal } from "@/components/AppShell";
import { ImportCandidatesModal } from "@/components/ImportCandidatesModal";
import { UserPlus, Linkedin, Globe, User2, Users, ChevronRight, Upload, GitCompare } from "lucide-react";
import { cn, formatRelativeTime } from "@/lib/utils";
import { Suspense } from "react";

// ── Constants ────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-100 text-green-700",
  passive: "bg-yellow-100 text-yellow-700",
  blacklisted: "bg-red-100 text-red-700",
};

const STATUS_LABELS: Record<string, string> = {
  active: "Aktywny",
  passive: "Pasywny",
  blacklisted: "Zablokowany",
};

const AVATAR_COLORS = [
  "bg-blue-600", "bg-violet-600", "bg-emerald-600",
  "bg-rose-500", "bg-amber-500", "bg-cyan-600",
];

function getAvatarColor(name: string): string {
  const code = (name?.charCodeAt(0) ?? 0) + (name?.charCodeAt(1) ?? 0);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

function SourceIcon({ source }: { source: string }) {
  if (source === "linkedin") return <Linkedin className="w-3.5 h-3.5" style={{ color: "#0A66C2" }} />;
  if (source === "pracuj") return <span className="text-[10px] font-bold leading-none" style={{ color: "#FF6600" }}>P</span>;
  if (source === "manual") return <User2 className="w-3.5 h-3.5 text-gray-400" />;
  return <Globe className="w-3 h-3 text-gray-400" />;
}

// ── Candidate list item ───────────────────────────────────────────────────────

function CandidateListItem({
  candidate,
  selected,
  checked,
  onCheck,
  onClick,
}: {
  candidate: any;
  selected: boolean;
  checked: boolean;
  onCheck: (e: React.MouseEvent) => void;
  onClick: () => void;
}) {
  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const initials = fullName.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase();
  const avatarColor = getAvatarColor(fullName);
  const source = candidate.source || "manual";
  const tags: string[] = (candidate.tags ?? []).slice(0, 3);

  return (
    <div
      className={cn(
        "w-full text-left flex items-start gap-3 px-4 py-3.5 border-b border-gray-100 dark:border-gray-700 transition-all duration-100 cursor-pointer",
        selected
          ? "bg-blue-50 dark:bg-blue-900/20 border-l-2 border-l-blue-600"
          : "hover:bg-gray-50 dark:hover:bg-gray-800 border-l-2 border-l-transparent"
      )}
      onClick={onClick}
    >
      {/* Checkbox */}
      <div
        className="flex-shrink-0 mt-2.5"
        onClick={onCheck}
      >
        <input
          type="checkbox"
          checked={checked}
          onChange={() => {}}
          className="w-3.5 h-3.5 rounded accent-blue-600 cursor-pointer"
        />
      </div>

      {/* Avatar */}
      <div
        className={cn(
          "w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold text-sm flex-shrink-0 mt-0.5",
          avatarColor
        )}
      >
        {initials || "?"}
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className={cn("font-semibold text-sm truncate", selected ? "text-blue-700" : "text-gray-900")}>
            {fullName || "Brak nazwy"}
          </span>
          <span className="text-[10px] text-gray-400 flex-shrink-0">
            {formatRelativeTime(candidate.updated_at || candidate.created_at)}
          </span>
        </div>

        {/* Position / company */}
        {(candidate.current_position || candidate.current_employer) && (
          <p className="text-xs text-gray-500 truncate mt-0.5">
            {[candidate.current_position, candidate.current_employer].filter(Boolean).join(" · ")}
          </p>
        )}

        {/* Bottom row */}
        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
          <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", STATUS_COLORS[candidate.status] ?? "bg-gray-100 text-gray-500")}>
            {STATUS_LABELS[candidate.status] ?? candidate.status}
          </span>
          {tags.map((tag: string) => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded-full">
              {tag}
            </span>
          ))}
          <span className="ml-auto flex-shrink-0 flex items-center" title={source}>
            <SourceIcon source={source} />
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Empty detail state ────────────────────────────────────────────────────────

function EmptyDetailState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center py-20 px-8">
      <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
        <Users className="w-8 h-8 text-gray-300" />
      </div>
      <p className="text-gray-500 font-medium">Wybierz kandydata z listy</p>
      <p className="text-sm text-gray-400 mt-1">Kliknij kandydata po lewej, aby zobaczyć jego profil</p>
    </div>
  );
}

// ── Inline detail frame ───────────────────────────────────────────────────────

function CandidateDetailFrame({ candidateId }: { candidateId: number }) {
  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <div className="p-6">
        <iframe
          key={candidateId}
          src={`/candidates/${candidateId}?embed=1`}
          className="w-full h-full border-0"
          style={{ minHeight: "calc(100vh - 120px)" }}
        />
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function CandidatesPageInner() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState("newest");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [compareIds, setCompareIds] = useState<number[]>([]);

  const { data, isLoading } = useQuery({
    queryKey: ["candidates", search, statusFilter, page, sortBy],
    queryFn: () =>
      api
        .get("/api/candidates", {
          params: {
            q: search || undefined,
            status: statusFilter || undefined,
            page,
          },
        })
        .then((r) => r.data),
  });

  // Select candidate in panel; update URL shallowly
  const handleSelect = useCallback((id: number) => {
    setSelectedId(id);
    window.history.replaceState(null, "", `/candidates?id=${id}`);
  }, []);

  const handleToggleCompare = useCallback((e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    setCompareIds(prev => {
      if (prev.includes(id)) return prev.filter(x => x !== id);
      if (prev.length >= 3) return prev; // max 3
      return [...prev, id];
    });
  }, []);

  return (
    <div className="-m-6 flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
      {/* Page header */}
      <div className="px-4 md:px-6 py-4 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Kandydaci</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">{data?.total ?? 0} w bazie</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowImportModal(true)}
            className="flex items-center gap-2 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 px-3 py-2 rounded-lg text-sm font-medium transition-all"
          >
            <Upload className="w-4 h-4" />
            Import CSV
          </button>
          {compareIds.length >= 2 && (
            <button
              onClick={() => router.push(`/candidates/compare?ids=${compareIds.join(",")}`)}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-sm"
            >
              <GitCompare className="w-4 h-4" />
              Porównaj ({compareIds.length})
            </button>
          )}
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 hover:scale-[1.02] active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-sm"
          >
            <UserPlus className="w-4 h-4" />
            Dodaj kandydata
          </button>
        </div>
        {showAddModal && (
          <AddCandidateModal
            onClose={() => setShowAddModal(false)}
            onSuccess={(msg) => {
              queryClient.invalidateQueries({ queryKey: ["candidates"] });
              setShowAddModal(false);
            }}
          />
        )}
        {showImportModal && (
          <ImportCandidatesModal
            onClose={() => setShowImportModal(false)}
          />
        )}
      </div>

      {/* Two-panel master-detail */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Left: list panel ── */}
        <div className="w-full md:w-[380px] md:min-w-[280px] flex-shrink-0 flex flex-col border-r border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 overflow-hidden">
          {/* Search & filters */}
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 space-y-2 flex-shrink-0 bg-white dark:bg-gray-900">
            <SearchBar
              value={search}
              onChange={(v) => { setSearch(v); setPage(1); }}
              placeholder="Szukaj po imieniu, emailu..."
              className="w-full"
            />
            <div className="flex gap-2">
              <select
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                className="flex-1 px-2 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 dark:text-gray-100"
              >
                <option value="">Wszystkie statusy</option>
                <option value="active">Aktywny</option>
                <option value="passive">Pasywny</option>
                <option value="blacklisted">Blacklisted</option>
              </select>
              <select
                value={sortBy}
                onChange={(e) => { setSortBy(e.target.value); setPage(1); }}
                className="flex-1 px-2 py-1.5 border border-gray-200 dark:border-gray-600 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 dark:text-gray-100"
              >
                <option value="newest">Najnowsi</option>
                <option value="name_asc">Nazwa A–Z</option>
              </select>
            </div>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-100 dark:border-gray-700 bg-white dark:bg-gray-900">
                  <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-700 animate-pulse flex-shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded animate-pulse w-3/4" />
                    <div className="h-3 bg-gray-100 dark:bg-gray-700 rounded animate-pulse w-1/2" />
                  </div>
                </div>
              ))
            ) : (data?.items ?? []).length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 px-6 text-center bg-white dark:bg-gray-900">
                <p className="text-gray-400 dark:text-gray-500 text-sm">Brak kandydatów</p>
              </div>
            ) : (
              (data?.items ?? []).map((candidate: any) => (
                <CandidateListItem
                  key={candidate.id}
                  candidate={candidate}
                  selected={selectedId === candidate.id}
                  checked={compareIds.includes(candidate.id)}
                  onCheck={(e) => handleToggleCompare(e, candidate.id)}
                  onClick={() => handleSelect(candidate.id)}
                />
              ))
            )}

            {/* Pagination */}
            {data && data.total > 20 && (
              <div className="flex justify-between items-center px-4 py-3 border-t border-gray-100 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-900">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="disabled:opacity-40 hover:text-blue-600 transition-colors"
                >
                  ← Poprzednia
                </button>
                <span>Strona {page} / {Math.ceil(data.total / 20)}</span>
                <button
                  disabled={page >= Math.ceil(data.total / 20)}
                  onClick={() => setPage((p) => p + 1)}
                  className="disabled:opacity-40 hover:text-blue-600 transition-colors"
                >
                  Następna →
                </button>
              </div>
            )}
          </div>
        </div>

        {/* ── Right: detail panel ── */}
        <div className="hidden md:flex flex-1 overflow-hidden bg-gray-50 dark:bg-gray-950">
          {selectedId ? (
            <CandidateDetailFrame candidateId={selectedId} />
          ) : (
            <div className="flex items-center justify-center h-full">
              <EmptyDetailState />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CandidatesPage() {
  return (
    <Suspense>
      <CandidatesPageInner />
    </Suspense>
  );
}
