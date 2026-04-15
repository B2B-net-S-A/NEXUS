"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { talentPoolsApi } from "@/lib/api";
import {
  Star,
  Users,
  Plus,
  X,
  ChevronLeft,
  MapPin,
  Briefcase,
  UserMinus,
  AlertCircle,
  Clock,
  Tag,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { DeleteButton } from "@/components/ConfirmDialog";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TalentPool {
  id: number;
  name: string;
  description: string | null;
  candidate_count: number;
  created_at: string;
  criteria: Record<string, unknown> | null;
}

// Derive pool type badge from name keywords
function getPoolTypeBadge(name: string): { label: string; color: string } {
  const n = name.toLowerCase();
  if (n.includes("senior") || n.includes("lead") || n.includes("principal")) {
    return { label: "Senior", color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400" };
  }
  if (n.includes("junior") || n.includes("mid")) {
    return { label: "Junior/Mid", color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" };
  }
  if (n.includes("devops") || n.includes("cloud") || n.includes("infra")) {
    return { label: "DevOps/Cloud", color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400" };
  }
  if (n.includes("qa") || n.includes("test")) {
    return { label: "QA/Test", color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" };
  }
  if (n.includes("pm") || n.includes("project") || n.includes("manager")) {
    return { label: "PM", color: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400" };
  }
  if (n.includes("data") || n.includes("ml") || n.includes("ai")) {
    return { label: "Data/AI", color: "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400" };
  }
  return { label: "Technologia", color: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400" };
}

function formatRelativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return "dziś";
  if (days === 1) return "wczoraj";
  if (days < 7) return `${days} dni temu`;
  if (days < 30) return `${Math.floor(days / 7)} tyg. temu`;
  return new Date(iso).toLocaleDateString("pl-PL", { day: "numeric", month: "short" });
}

interface CandidateInPool {
  id: number;
  name: string;
  lastname: string;
  email: string | null;
  location: string | null;
  competence_category: string | null;
  skills: Array<{ name: string; level?: string; years?: number } | string> | null;
  status: string;
  added_at: string;
}

// ── Pool Card Colors ──────────────────────────────────────────────────────────

const POOL_COLORS = [
  "from-blue-500 to-blue-600",
  "from-violet-500 to-purple-600",
  "from-emerald-500 to-green-600",
  "from-orange-500 to-amber-600",
  "from-rose-500 to-red-600",
  "from-cyan-500 to-teal-600",
];

function getPoolColor(name: string): string {
  const code = name.charCodeAt(0) + (name.charCodeAt(1) || 0);
  return POOL_COLORS[code % POOL_COLORS.length];
}

// ── Create Pool Modal ─────────────────────────────────────────────────────────

function CreatePoolModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (data: { name: string; description: string }) =>
      talentPoolsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
      onClose();
    },
    onError: () => {
      setError("Nie udało się utworzyć puli. Spróbuj ponownie.");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    createMutation.mutate({ name: name.trim(), description: description.trim() });
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Nowa pula talentów</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:text-gray-300">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Nazwa puli <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="np. Senior Angular, DevOps Cloud, QA Automation"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Opis</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Opisz kryteria przynależności do tej puli..."
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 dark:bg-gray-900 text-gray-600 dark:text-gray-300"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={!name.trim() || createMutation.isPending}
              className="flex-1 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
            >
              {createMutation.isPending ? "Tworzę..." : "Utwórz pulę"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Pool Detail View ──────────────────────────────────────────────────────────

function PoolDetailView({
  pool,
  onBack,
}: {
  pool: TalentPool;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["talent-pool-candidates", pool.id],
    queryFn: () => talentPoolsApi.getCandidates(pool.id).then((r) => r.data),
  });

  const removeMutation = useMutation({
    mutationFn: (candidateId: number) =>
      talentPoolsApi.removeCandidate(pool.id, candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["talent-pool-candidates", pool.id] });
      queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
    },
  });

  const candidates: CandidateInPool[] = data?.candidates ?? [];
  const poolColor = getPoolColor(pool.name);

  return (
    <div className="space-y-4">
      {/* Header */}
      <button
        onClick={onBack}
        className="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-800 transition-colors"
      >
        <ChevronLeft className="w-4 h-4" /> Wróć do pul
      </button>

      <div
        className={cn(
          "bg-gradient-to-r rounded-2xl p-6 text-white shadow-sm",
          poolColor
        )}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Star className="w-5 h-5 fill-white text-white" />
              <span className="text-white/80 text-sm font-medium">Pula talentów</span>
            </div>
            <h1 className="text-2xl font-bold">{pool.name}</h1>
            {pool.description && (
              <p className="text-white/80 mt-1 text-sm">{pool.description}</p>
            )}
          </div>
          <div className="bg-white/20 rounded-xl px-4 py-2 text-center">
            <p className="text-2xl font-bold">{candidates.length}</p>
            <p className="text-white/80 text-xs">kandydatów</p>
          </div>
        </div>
      </div>

      {/* Candidates */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 dark:text-gray-100">
            Kandydaci w puli ({candidates.length})
          </h2>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-gray-400 gap-2">
            <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            Ładowanie...
          </div>
        ) : candidates.length === 0 ? (
          <div className="text-center py-12 text-gray-400">
            <Users className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Brak kandydatów w tej puli</p>
            <p className="text-xs mt-1 text-gray-400">
              Dodaj kandydatów przez profil kandydata
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {candidates.map((c) => {
              const skills = Array.isArray(c.skills) ? c.skills : [];
              const topSkills = skills
                .slice(0, 4)
                .map((s) => (typeof s === "object" ? s.name : s));

              return (
                <div
                  key={c.id}
                  className="flex items-center justify-between px-6 py-4 hover:bg-gray-50 dark:bg-gray-900 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    {/* Avatar */}
                    <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                      {c.name.charAt(0)}
                      {c.lastname.charAt(0)}
                    </div>
                    <div>
                      <Link
                        href={`/candidates/${c.id}`}
                        className="font-semibold text-gray-900 dark:text-gray-100 hover:text-blue-600 transition-colors"
                      >
                        {c.name} {c.lastname}
                      </Link>
                      <div className="flex flex-wrap items-center gap-2 mt-0.5">
                        {c.competence_category && (
                          <span className="text-xs text-blue-600 font-medium">
                            {c.competence_category}
                          </span>
                        )}
                        {c.location && (
                          <span className="text-xs text-gray-400 flex items-center gap-0.5">
                            <MapPin className="w-3 h-3" />
                            {c.location}
                          </span>
                        )}
                      </div>
                      {topSkills.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {topSkills.map((skill, i) => (
                            <span
                              key={i}
                              className="px-1.5 py-0.5 bg-gray-100 text-gray-600 dark:text-gray-300 rounded text-xs"
                            >
                              {skill}
                            </span>
                          ))}
                          {skills.length > 4 && (
                            <span className="text-xs text-gray-400">
                              +{skills.length - 4}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span
                      className={cn(
                        "text-xs px-2 py-0.5 rounded-full font-medium",
                        c.status === "active"
                          ? "bg-emerald-100 text-emerald-700"
                          : c.status === "passive"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-red-100 text-red-700"
                      )}
                    >
                      {c.status === "active"
                        ? "Aktywny"
                        : c.status === "passive"
                        ? "Pasywny"
                        : "Zablokowany"}
                    </span>
                    <DeleteButton onConfirm={() => removeMutation.mutate(c.id)} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TalentsPage() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedPool, setSelectedPool] = useState<TalentPool | null>(null);

  const { data: pools = [], isLoading } = useQuery<TalentPool[]>({
    queryKey: ["talent-pools"],
    queryFn: () => talentPoolsApi.list().then((r) => r.data),
  });

  if (selectedPool) {
    return (
      <PoolDetailView
        pool={selectedPool}
        onBack={() => setSelectedPool(null)}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            <Star className="w-6 h-6 text-amber-500 fill-amber-500" />
            Pule talentów
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Zarządzaj grupami kandydatów według technologii i specjalizacji
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Nowa pula
        </button>
      </div>

      {/* Pools Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-gray-400 gap-2">
          <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          Ładowanie pul talentów...
        </div>
      ) : pools.length === 0 ? (
        <div className="text-center py-20">
          <Star className="w-12 h-12 mx-auto mb-4 text-gray-200" />
          <h3 className="text-lg font-semibold text-gray-400 mb-2">
            Brak pul talentów
          </h3>
          <p className="text-sm text-gray-400 mb-4">
            Utwórz pierwszą pulę, aby grupować kandydatów
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
          >
            <Plus className="w-4 h-4" />
            Utwórz pierwszą pulę
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {pools.map((pool) => {
            const color = getPoolColor(pool.name);
            return (
              <button
                key={pool.id}
                onClick={() => setSelectedPool(pool)}
                className="text-left bg-white border border-gray-200 rounded-2xl shadow-sm hover:shadow-md hover:border-gray-300 transition-all overflow-hidden group"
              >
                {/* Color bar */}
                <div className={cn("h-1.5 bg-gradient-to-r", color)} />

                <div className="p-5">
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div
                      className={cn(
                        "w-10 h-10 rounded-xl bg-gradient-to-br flex items-center justify-center flex-shrink-0",
                        color
                      )}
                    >
                      <Star className="w-5 h-5 text-white fill-white" />
                    </div>
                    <div className="text-right">
                      <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                        {pool.candidate_count}
                      </p>
                      <p className="text-xs text-gray-400">kandydatów</p>
                    </div>
                  </div>

                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-bold text-gray-900 dark:text-gray-100 text-base group-hover:text-blue-600 transition-colors flex-1">
                      {pool.name}
                    </h3>
                    {(() => {
                      const badge = getPoolTypeBadge(pool.name);
                      return (
                        <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0 flex items-center gap-1", badge.color)}>
                          <Tag className="w-2.5 h-2.5" />
                          {badge.label}
                        </span>
                      );
                    })()}
                  </div>

                  {pool.description && (
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">
                      {pool.description}
                    </p>
                  )}

                  <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700 flex items-center justify-between text-xs text-gray-400">
                    <div className="flex items-center gap-1">
                      <Users className="w-3.5 h-3.5" />
                      <span>{pool.candidate_count} kandydatów</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      <span>Zaktualizowano {formatRelativeDate(pool.created_at)}</span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreatePoolModal onClose={() => setShowCreateModal(false)} />
      )}
    </div>
  );
}
