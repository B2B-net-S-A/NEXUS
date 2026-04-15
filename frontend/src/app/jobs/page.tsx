"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { SearchBar } from "@/components/SearchBar";
import { AddJobModal } from "@/components/AppShell";
import { Briefcase, Plus, Users, Clock, TrendingUp, BarChart2 } from "lucide-react";
import { cn, formatDate } from "@/lib/utils";

// ── Constants ────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  draft:     "bg-gray-100 text-gray-600",
  published: "bg-green-100 text-green-700",
  closed:    "bg-red-100 text-red-700",
};

const STATUS_LABELS: Record<string, string> = {
  draft:     "Draft",
  published: "Opublikowana",
  closed:    "Zamknięta",
};

const PRIORITY_COLORS: Record<string, string> = {
  low:    "text-gray-400",
  medium: "text-blue-500",
  high:   "text-orange-500",
  urgent: "text-red-600",
};

const RECRUITMENT_TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  body_leasing:  { label: "Body Leasing", color: "bg-blue-100 text-blue-700" },
  sales_project: { label: "Sprzedaż",    color: "bg-green-100 text-green-700" },
  tender:        { label: "Przetarg",    color: "bg-orange-100 text-orange-700" },
};

type RecruitmentTypeFilter = "" | "body_leasing" | "sales_project" | "tender";

const FILTER_TABS: { value: RecruitmentTypeFilter; label: string }[] = [
  { value: "",              label: "Wszystkie" },
  { value: "body_leasing",  label: "Body Leasing" },
  { value: "sales_project", label: "Sprzedaż" },
  { value: "tender",        label: "Przetargi" },
];

// ── Job Card ─────────────────────────────────────────────────────────────────

function JobCard({ job, onClick }: { job: any; onClick: () => void }) {
  const typeConfig = RECRUITMENT_TYPE_CONFIG[job.recruitment_type];
  const daysOpen = job.created_at
    ? Math.floor((Date.now() - new Date(job.created_at).getTime()) / 86400000)
    : null;

  const candidateCount = job.candidate_count ?? 0;
  const maxCandidates = 20; // progress bar reference
  const progress = Math.min(100, (candidateCount / maxCandidates) * 100);

  const statusCfg = { color: STATUS_COLORS[job.status] ?? "bg-gray-100 text-gray-600", label: STATUS_LABELS[job.status] ?? job.status };

  return (
    <div
      onClick={onClick}
      className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 hover:shadow-md hover:-translate-y-[1px] transition-all duration-200 cursor-pointer relative flex flex-col gap-4"
    >
      {/* Corner status badge */}
      <div className="absolute top-4 right-4">
        <span className={cn("text-[11px] px-2 py-0.5 rounded-full font-medium", statusCfg.color)}>
          {statusCfg.label}
        </span>
      </div>

      {/* Header */}
      <div className="pr-20">
        <h3 className="font-bold text-gray-900 dark:text-gray-100 text-base leading-tight">{job.title}</h3>
        {job.client_name && (
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{job.client_name}</p>
        )}
        {typeConfig && (
          <span className={cn("inline-block mt-2 text-[11px] px-2 py-0.5 rounded-full font-medium", typeConfig.color)}>
            {typeConfig.label}
          </span>
        )}
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-sm text-gray-600">
        <span className="flex items-center gap-1.5">
          <Users className="w-3.5 h-3.5 text-gray-400" />
          {candidateCount} kandydatów
        </span>
        {job.interview_count != null && (
          <span className="flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-gray-400" />
            {job.interview_count} rozmów
          </span>
        )}
        {daysOpen != null && (
          <span className="flex items-center gap-1.5 ml-auto text-xs text-gray-400">
            <Clock className="w-3 h-3" />
            {daysOpen}d
          </span>
        )}
      </div>

      {/* Pipeline progress bar */}
      {candidateCount > 0 && (
        <div>
          <div className="flex justify-between text-[10px] text-gray-400 mb-1">
            <span>Pipeline</span>
            <span>{candidateCount} / {maxCandidates}</span>
          </div>
          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Footer: salary + priority */}
      {(job.salary_min || job.priority) && (
        <div className="flex items-center justify-between text-xs text-gray-500 border-t border-gray-50 pt-3">
          {job.salary_min && job.salary_max ? (
            <span>{job.salary_min.toLocaleString()}–{job.salary_max.toLocaleString()} PLN</span>
          ) : <span />}
          {job.priority && (
            <span className={cn("font-medium capitalize", PRIORITY_COLORS[job.priority] ?? "text-gray-400")}>
              {job.priority === "urgent" ? "🔥 Pilne" : job.priority}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Skeleton card ─────────────────────────────────────────────────────────────

function JobCardSkeleton() {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 space-y-4 animate-pulse">
      <div className="h-5 bg-gray-200 rounded w-3/4" />
      <div className="h-4 bg-gray-100 rounded w-1/2" />
      <div className="h-3 bg-gray-100 rounded w-1/3" />
      <div className="h-2 bg-gray-100 rounded w-full" />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function JobsPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<RecruitmentTypeFilter>("");
  const [page, setPage] = useState(1);
  const [showAddModal, setShowAddModal] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["jobs", search, statusFilter, typeFilter, page],
    queryFn: () =>
      api
        .get("/api/jobs", {
          params: {
            q: search || undefined,
            status: statusFilter || undefined,
            recruitment_type: typeFilter || undefined,
            page,
          },
        })
        .then((r) => r.data),
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Oferty pracy</h1>
          <p className="text-sm text-gray-500">{data?.total ?? 0} ofert</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 hover:scale-[1.02] active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Nowa oferta
        </button>
        {showAddModal && (
          <AddJobModal
            onClose={() => setShowAddModal(false)}
            onSuccess={() => {
              queryClient.invalidateQueries({ queryKey: ["jobs"] });
              setShowAddModal(false);
            }}
          />
        )}
      </div>

      {/* Recruitment type filter tabs */}
      <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 w-fit">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => { setTypeFilter(tab.value); setPage(1); }}
            className={cn(
              "px-4 py-1.5 rounded-lg text-sm font-medium transition-all",
              typeFilter === tab.value
                ? "bg-white dark:bg-gray-700 shadow text-gray-900 dark:text-gray-100"
                : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search & status filter */}
      <div className="flex gap-3">
        <SearchBar
          value={search}
          onChange={(v) => { setSearch(v); setPage(1); }}
          placeholder="Szukaj ofert..."
          className="flex-1"
        />
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 dark:text-gray-100"
        >
          <option value="">Wszystkie statusy</option>
          <option value="draft">Draft</option>
          <option value="published">Opublikowane</option>
          <option value="closed">Zamknięte</option>
        </select>
      </div>

      {/* Card grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <JobCardSkeleton key={i} />)}
        </div>
      ) : (data?.items ?? []).length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
            <Briefcase className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-gray-500 dark:text-gray-400 font-medium">Brak ofert pracy</p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">Dodaj pierwszą ofertę aby rozpocząć rekrutację</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(data?.items ?? []).map((job: any) => (
              <JobCard
                key={job.id}
                job={job}
                onClick={() => router.push(`/jobs/${job.id}`)}
              />
            ))}
          </div>

          {/* Pagination */}
          {data && data.total > 20 && (
            <div className="flex justify-center items-center gap-4 text-sm text-gray-500">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
                className="disabled:opacity-40 hover:text-blue-600 transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-100"
              >
                ← Poprzednia
              </button>
              <span>Strona {page} / {Math.ceil(data.total / 20)}</span>
              <button
                disabled={page >= Math.ceil(data.total / 20)}
                onClick={() => setPage((p) => p + 1)}
                className="disabled:opacity-40 hover:text-blue-600 transition-colors px-3 py-1.5 rounded-lg hover:bg-gray-100"
              >
                Następna →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
