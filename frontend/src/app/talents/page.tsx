"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { talentPoolsApi, competenceCategoriesApi } from "@/lib/api";
import {
  Star,
  Users,
  Plus,
  X,
  ChevronLeft,
  MapPin,
  Briefcase,
  AlertCircle,
  Search,
  Building2,
  UserRound,
  Trash2,
  Lock,
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { DeleteButton, ConfirmButton } from "@/components/ConfirmDialog";
import { MultiSelectFilter } from "@/components/v2/filters/MultiSelectFilter";
import { useAuthStore, hasRole } from "@/store/auth";

// ── Types ─────────────────────────────────────────────────────────────────────

interface TalentPool {
  id: number;
  name: string;
  description: string | null;
  candidate_count: number;
  created_at: string;
  criteria: Record<string, unknown> | null;
  // Phase 10 A2
  competence_category_id: number | null;
  competence_category_slug: string | null;
  // Pule osobiste (migracja 0137)
  is_personal: boolean;
  owner_id: number | null;
  owner_name: string | null;
}

type PoolView = "company" | "personal";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Polish plural for "pula" — 1 pula / 2-4 pule / 5+ puli. */
function poolWord(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (n === 1) return "pula";
  if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) return "pule";
  return "puli";
}

const UNCATEGORIZED_LABEL = "Pozostałe";

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
  source_event: string | null;
  source_job_id: number | null;
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

// ── Pool Card ─────────────────────────────────────────────────────────────────

function PoolCard({
  pool,
  onClick,
  showOwner = false,
}: {
  pool: TalentPool;
  onClick: () => void;
  showOwner?: boolean;
}) {
  const color = getPoolColor(pool.name);
  return (
    <button
      onClick={onClick}
      title={pool.description ?? pool.name}
      className="group flex items-center gap-2.5 px-3 py-2.5 text-left bg-card border border-border rounded-lg hover:border-primary/40 hover:bg-muted/50 transition-colors"
    >
      <span
        className={cn(
          "w-8 h-8 rounded-lg bg-gradient-to-br flex items-center justify-center flex-shrink-0",
          color,
        )}
      >
        <Star className="w-4 h-4 text-white fill-white" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-sm text-foreground truncate group-hover:text-primary transition-colors">
          {pool.name}
        </span>
        {showOwner && pool.owner_name && (
          <span className="block text-[11px] text-muted-foreground truncate">
            {pool.owner_name}
          </span>
        )}
      </span>
      <span className="flex items-center gap-1 text-xs font-semibold text-muted-foreground tabular-nums flex-shrink-0">
        <Users className="w-3.5 h-3.5" />
        {pool.candidate_count}
      </span>
    </button>
  );
}

// ── Create Pool Modal ─────────────────────────────────────────────────────────

function CreatePoolModal({
  defaultPersonal,
  onClose,
  onCreated,
}: {
  defaultPersonal: boolean;
  onClose: () => void;
  onCreated?: (isPersonal: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isPersonal, setIsPersonal] = useState(defaultPersonal);
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (data: { name: string; description: string; is_personal: boolean }) =>
      talentPoolsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
      onCreated?.(isPersonal);
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
    createMutation.mutate({
      name: name.trim(),
      description: description.trim(),
      is_personal: isPersonal,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-card rounded-2xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-bold text-foreground dark:text-foreground">
            {isPersonal ? "Nowa pula osobista" : "Nowa pula firmowa"}
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Nazwa puli <span className="text-destructive">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder={
                isPersonal
                  ? "np. Moi React seniorzy, Do zaproszenia na meetup"
                  : "np. Senior Angular, DevOps Cloud, QA Automation"
              }
              className="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Opis</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Opisz kryteria przynależności do tej puli..."
              className="w-full px-3 py-2 border border-border rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus-visible:ring-ring"
            />
          </div>

          {/* Pula osobista vs firmowa */}
          <label className="flex items-start gap-2.5 cursor-pointer rounded-lg border border-border px-3 py-2.5 hover:bg-muted/50 transition-colors">
            <input
              type="checkbox"
              checked={isPersonal}
              onChange={(e) => setIsPersonal(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
            />
            <span className="text-sm">
              <span className="font-medium text-foreground flex items-center gap-1.5">
                <UserRound className="w-3.5 h-3.5" /> Pula osobista
              </span>
              <span className="block text-xs text-muted-foreground mt-0.5">
                Widoczna dla całego zespołu, ale dodawać kandydatów i usuwać pulę
                możesz tylko Ty (lub admin).
              </span>
            </span>
          </label>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted dark:bg-card text-muted-foreground dark:text-muted-foreground"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={!name.trim() || createMutation.isPending}
              className="flex-1 px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 font-medium"
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
  canManage,
  canDelete,
  onBack,
  onDeleted,
}: {
  pool: TalentPool;
  canManage: boolean;
  canDelete: boolean;
  onBack: () => void;
  onDeleted: () => void;
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

  const deletePoolMutation = useMutation({
    mutationFn: () => talentPoolsApi.deletePool(pool.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["talent-pools"] });
      onDeleted();
    },
  });

  const candidates: CandidateInPool[] = data?.candidates ?? [];
  const poolColor = getPoolColor(pool.name);
  // The API reports the true membership count separately from the (capped)
  // page of candidate rows — the largest pools hold ~1k members after the
  // cv_sent backfill, so we show the real total and note when truncated.
  const total: number = data?.total ?? candidates.length;

  return (
    <div className="space-y-4">
      {/* Header row: back + delete */}
      <div className="flex items-center justify-between gap-3">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground dark:text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="w-4 h-4" /> Wróć do pul
        </button>
        {canDelete && (
          <ConfirmButton
            onConfirm={() => deletePoolMutation.mutate()}
            message="Usunąć całą pulę? Tej operacji nie można cofnąć."
            confirmLabel="Usuń pulę"
            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-destructive hover:border-destructive/40 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" /> Usuń pulę
          </ConfirmButton>
        )}
      </div>

      <div
        className={cn(
          "bg-gradient-to-r rounded-2xl p-6 text-white shadow-sm",
          poolColor,
        )}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              {pool.is_personal ? (
                <UserRound className="w-5 h-5 text-white" />
              ) : (
                <Star className="w-5 h-5 fill-white text-white" />
              )}
              <span className="text-white/80 text-sm font-medium">
                {pool.is_personal ? "Pula osobista" : "Pula talentów"}
              </span>
            </div>
            <h1 className="text-2xl font-bold">{pool.name}</h1>
            {pool.description && (
              <p className="text-white/80 mt-1 text-sm">{pool.description}</p>
            )}
            {pool.is_personal && pool.owner_name && (
              <p className="text-white/70 mt-1 text-xs inline-flex items-center gap-1">
                <UserRound className="w-3 h-3" /> Właściciel: {pool.owner_name}
                {!canManage && (
                  <span className="inline-flex items-center gap-0.5 ml-1">
                    <Lock className="w-3 h-3" /> tylko podgląd
                  </span>
                )}
              </p>
            )}
          </div>
          <div className="bg-card/20 rounded-xl px-4 py-2 text-center">
            <p className="text-2xl font-bold">{total}</p>
            <p className="text-white/80 text-xs">kandydatów</p>
          </div>
        </div>
      </div>

      {/* Candidates */}
      <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border shadow-sm">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-foreground dark:text-foreground">
            Kandydaci w puli ({total})
          </h2>
          {total > candidates.length && (
            <span className="text-xs text-muted-foreground">
              pokazano {candidates.length} z {total}
            </span>
          )}
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground gap-2">
            <div className="w-4 h-4 border-2 border-primary/30 border-t-transparent rounded-full animate-spin" />
            Ładowanie...
          </div>
        ) : candidates.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <Users className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Brak kandydatów w tej puli</p>
            <p className="text-xs mt-1 text-muted-foreground">
              {canManage
                ? "Dodaj kandydatów przez profil kandydata lub listę kandydatów"
                : "Tylko właściciel może dodawać kandydatów do tej puli"}
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
                  className="flex items-center justify-between px-6 py-4 hover:bg-muted dark:bg-card transition-colors"
                >
                  <div className="flex items-center gap-4">
                    {/* Avatar */}
                    <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                      {c.name.charAt(0)}
                      {c.lastname.charAt(0)}
                    </div>
                    <div>
                      <Link
                        href={`/candidates/${c.id}`}
                        className="font-semibold text-foreground dark:text-foreground hover:text-primary transition-colors"
                      >
                        {c.name} {c.lastname}
                      </Link>
                      <div className="flex flex-wrap items-center gap-2 mt-0.5">
                        {c.competence_category && (
                          <span className="text-xs text-primary font-medium">
                            {c.competence_category}
                          </span>
                        )}
                        {c.location && (
                          <span className="text-xs text-muted-foreground flex items-center gap-0.5">
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
                              className="px-1.5 py-0.5 bg-muted text-muted-foreground dark:text-muted-foreground rounded text-xs"
                            >
                              {skill}
                            </span>
                          ))}
                          {skills.length > 4 && (
                            <span className="text-xs text-muted-foreground">
                              +{skills.length - 4}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 flex-shrink-0">
                    {c.source_event === "cv_sent" && (
                      c.source_job_id ? (
                        <Link
                          href={`/jobs/${c.source_job_id}`}
                          title="Kandydat dodany automatycznie po wysłaniu CV do klienta"
                          className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 dark:bg-indigo-900/30 dark:text-indigo-300 dark:border-indigo-700"
                        >
                          <Briefcase className="w-3 h-3" /> Z CV → Klient
                        </Link>
                      ) : (
                        <span
                          title="Kandydat dodany automatycznie po wysłaniu CV do klienta"
                          className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-indigo-50 text-indigo-700 border border-indigo-200 dark:bg-indigo-900/30 dark:text-indigo-300 dark:border-indigo-700"
                        >
                          <Briefcase className="w-3 h-3" /> Z CV → Klient
                        </span>
                      )
                    )}
                    <span
                      className={cn(
                        "text-xs px-2 py-0.5 rounded-full font-medium",
                        c.status === "active"
                          ? "bg-emerald-100 text-emerald-700"
                          : c.status === "passive"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-destructive/15 text-destructive",
                      )}
                    >
                      {c.status === "active"
                        ? "Aktywny"
                        : c.status === "passive"
                        ? "Pasywny"
                        : "Zablokowany"}
                    </span>
                    {canManage && (
                      <DeleteButton onConfirm={() => removeMutation.mutate(c.id)} />
                    )}
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

/**
 * Client-only gate — Next.js 15 + React 19 streaming SSR wiesza hydrację
 * list z React Query (patrz commit b133403 dla /contracts, /jobs, /clients).
 * Pierwszy render placeholder, dopiero po mount renderujemy content.
 */
export default function TalentsPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Ładowanie pul talentów…
      </div>
    );
  }
  return <TalentsPageContent />;
}

function TalentsPageContent() {
  const user = useAuthStore((s) => s.user);
  const userId = user?.id ?? null;
  const isAdmin = hasRole(user, "admin");

  const [view, setView] = useState<PoolView>("company");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedPool, setSelectedPool] = useState<TalentPool | null>(null);
  const [selectedCcIds, setSelectedCcIds] = useState<number[]>([]);
  const [search, setSearch] = useState("");

  const { data: pools = [], isLoading } = useQuery<TalentPool[]>({
    queryKey: ["talent-pools"],
    queryFn: () => talentPoolsApi.list().then((r) => r.data),
  });

  const { data: ccList = [] } = useQuery({
    queryKey: ["competence-categories"],
    queryFn: () => competenceCategoriesApi.list(true),
    staleTime: 1000 * 60 * 60, // 1h — CC list is stable
  });

  const companyPools = useMemo(() => pools.filter((p) => !p.is_personal), [pools]);
  const personalPools = useMemo(() => pools.filter((p) => p.is_personal), [pools]);

  // ── Company view: filter by CC + free-text search, then group by CC ──────────
  const visibleCompanyPools = useMemo(() => {
    const q = search.trim().toLowerCase();
    return companyPools.filter((p) => {
      if (
        selectedCcIds.length > 0 &&
        (p.competence_category_id === null ||
          !selectedCcIds.includes(p.competence_category_id))
      ) {
        return false;
      }
      if (q && !`${p.name} ${p.description ?? ""}`.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [companyPools, selectedCcIds, search]);

  const groupedByCategory = useMemo(() => {
    const nameById = new Map<number, string>();
    const orderById = new Map<number, number>();
    ccList.forEach((cc) => {
      nameById.set(cc.id, cc.name_pl);
      orderById.set(cc.id, cc.display_order);
    });

    const groups = new Map<string, { order: number; pools: TalentPool[] }>();
    for (const pool of visibleCompanyPools) {
      const ccId = pool.competence_category_id;
      const hasCc = ccId !== null && nameById.has(ccId);
      const label = hasCc ? nameById.get(ccId as number)! : UNCATEGORIZED_LABEL;
      const order = hasCc ? (orderById.get(ccId as number) ?? 998) : 999;
      const group = groups.get(label) ?? { order, pools: [] };
      group.pools.push(pool);
      groups.set(label, group);
    }

    for (const group of groups.values()) {
      group.pools.sort((a, b) => a.name.localeCompare(b.name, "pl"));
    }

    return Array.from(groups.entries())
      .map(([label, group]) => ({ label, ...group }))
      .sort((a, b) => a.order - b.order);
  }, [visibleCompanyPools, ccList]);

  // ── Personal view: free-text search, split mine vs team (grouped by owner) ───
  const visiblePersonalPools = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return personalPools;
    return personalPools.filter((p) =>
      `${p.name} ${p.description ?? ""} ${p.owner_name ?? ""}`
        .toLowerCase()
        .includes(q),
    );
  }, [personalPools, search]);

  const myPools = useMemo(
    () =>
      visiblePersonalPools
        .filter((p) => p.owner_id === userId)
        .sort((a, b) => a.name.localeCompare(b.name, "pl")),
    [visiblePersonalPools, userId],
  );

  const teamPersonalByOwner = useMemo(() => {
    const groups = new Map<string, TalentPool[]>();
    for (const p of visiblePersonalPools) {
      if (p.owner_id === userId) continue;
      const key = p.owner_name ?? "Nieznany właściciel";
      const arr = groups.get(key) ?? [];
      arr.push(p);
      groups.set(key, arr);
    }
    for (const arr of groups.values()) {
      arr.sort((a, b) => a.name.localeCompare(b.name, "pl"));
    }
    return Array.from(groups.entries())
      .map(([owner_name, ownerPools]) => ({ owner_name, pools: ownerPools }))
      .sort((a, b) => a.owner_name.localeCompare(b.owner_name, "pl"));
  }, [visiblePersonalPools, userId]);

  const clearFilters = () => {
    setSearch("");
    setSelectedCcIds([]);
  };

  const openPool = (pool: TalentPool) => setSelectedPool(pool);

  if (selectedPool) {
    const canManage =
      !selectedPool.is_personal ||
      selectedPool.owner_id === userId ||
      isAdmin;
    const canDelete = selectedPool.is_personal
      ? selectedPool.owner_id === userId || isAdmin
      : isAdmin;
    return (
      <PoolDetailView
        pool={selectedPool}
        canManage={canManage}
        canDelete={canDelete}
        onBack={() => setSelectedPool(null)}
        onDeleted={() => setSelectedPool(null)}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground flex items-center gap-2">
            <Star className="w-6 h-6 text-amber-500 fill-amber-500" />
            Pule talentów
          </h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-1">
            {view === "company"
              ? "Zarządzaj grupami kandydatów według technologii i specjalizacji"
              : "Twoje prywatne pule i pule zespołu — wszyscy je widzą, zarządza tylko właściciel"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {view === "company" && (
            <MultiSelectFilter<number>
              value={selectedCcIds}
              onChange={setSelectedCcIds}
              options={ccList.map((cc) => ({ value: cc.id, label: cc.name_pl }))}
              placeholder="Wszystkie kategorie"
              searchPlaceholder="Szukaj kategorii…"
              triggerLabel={(count) =>
                count === 0
                  ? "Wszystkie kategorie"
                  : count === 1
                  ? (ccList.find((cc) => cc.id === selectedCcIds[0])?.name_pl ?? "1 kategoria")
                  : `${count} kategorii`
              }
              triggerWidthClass="w-[220px]"
            />
          )}
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            Nowa pula
          </button>
        </div>
      </div>

      {/* Tabs — Firmowe / Osobiste */}
      <div className="inline-flex items-center gap-1 p-1 bg-muted rounded-lg">
        <button
          onClick={() => setView("company")}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
            view === "company"
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Building2 className="w-4 h-4" /> Firmowe
          <span className="text-xs text-muted-foreground tabular-nums">
            {companyPools.length}
          </span>
        </button>
        <button
          onClick={() => setView("personal")}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
            view === "personal"
              ? "bg-card text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <UserRound className="w-4 h-4" /> Osobiste
          <span className="text-xs text-muted-foreground tabular-nums">
            {personalPools.length}
          </span>
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground gap-2">
          <div className="w-5 h-5 border-2 border-primary/30 border-t-transparent rounded-full animate-spin" />
          Ładowanie pul talentów...
        </div>
      ) : (
        <>
          {/* Search — shared across both views */}
          <div className="relative max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={
                view === "company"
                  ? "Szukaj puli, np. Java, DevOps, Data Scientist…"
                  : "Szukaj puli lub właściciela…"
              }
              className="w-full pl-9 pr-9 py-2.5 bg-card border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                aria-label="Wyczyść wyszukiwanie"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* ── Company view ─────────────────────────────────────────────── */}
          {view === "company" &&
            (companyPools.length === 0 ? (
              <div className="text-center py-20">
                <Star className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
                <h3 className="text-lg font-semibold text-muted-foreground mb-2">
                  Brak pul firmowych
                </h3>
                <p className="text-sm text-muted-foreground mb-4">
                  Utwórz pierwszą pulę, aby grupować kandydatów
                </p>
              </div>
            ) : visibleCompanyPools.length === 0 ? (
              <div className="text-center py-16">
                <Search className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
                <p className="text-sm text-muted-foreground mb-2">
                  {search.trim()
                    ? `Brak pul pasujących do „${search.trim()}”`
                    : "Brak pul w wybranych kategoriach"}
                </p>
                <button
                  onClick={clearFilters}
                  className="text-xs text-primary hover:text-primary/80 underline"
                >
                  Wyczyść filtry
                </button>
              </div>
            ) : (
              <div className="space-y-6">
                {groupedByCategory.map((group) => (
                  <section key={group.label}>
                    <div className="flex items-baseline gap-3 mb-3 pb-2 border-b border-border dark:border-border">
                      <h2 className="text-base font-semibold text-foreground dark:text-foreground">
                        {group.label}
                      </h2>
                      <span className="text-xs text-muted-foreground">
                        {group.pools.length} {poolWord(group.pools.length)}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                      {group.pools.map((pool) => (
                        <PoolCard
                          key={pool.id}
                          pool={pool}
                          onClick={() => openPool(pool)}
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            ))}

          {/* ── Personal view ────────────────────────────────────────────── */}
          {view === "personal" && (
            <div className="space-y-6">
              {/* Moje pule */}
              <section>
                <div className="flex items-baseline gap-3 mb-3 pb-2 border-b border-border dark:border-border">
                  <h2 className="text-base font-semibold text-foreground dark:text-foreground">
                    Moje pule
                  </h2>
                  <span className="text-xs text-muted-foreground">
                    {myPools.length} {poolWord(myPools.length)}
                  </span>
                </div>

                {myPools.length === 0 ? (
                  <div className="text-center py-10 bg-card border border-dashed border-border rounded-xl">
                    <UserRound className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground mb-3">
                      {search.trim()
                        ? `Nie masz pul pasujących do „${search.trim()}”`
                        : "Nie masz jeszcze własnej puli kandydatów"}
                    </p>
                    {!search.trim() && (
                      <button
                        onClick={() => setShowCreateModal(true)}
                        className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90"
                      >
                        <Plus className="w-4 h-4" />
                        Utwórz swoją pierwszą pulę
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                    {myPools.map((pool) => (
                      <PoolCard
                        key={pool.id}
                        pool={pool}
                        onClick={() => openPool(pool)}
                      />
                    ))}
                  </div>
                )}
              </section>

              {/* Pule zespołu — grouped by owner */}
              {teamPersonalByOwner.map((group) => (
                <section key={group.owner_name}>
                  <div className="flex items-baseline gap-3 mb-3 pb-2 border-b border-border dark:border-border">
                    <h2 className="text-base font-semibold text-foreground dark:text-foreground flex items-center gap-1.5">
                      <UserRound className="w-4 h-4 text-muted-foreground" />
                      {group.owner_name}
                    </h2>
                    <span className="text-xs text-muted-foreground">
                      {group.pools.length} {poolWord(group.pools.length)}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                    {group.pools.map((pool) => (
                      <PoolCard
                        key={pool.id}
                        pool={pool}
                        onClick={() => openPool(pool)}
                      />
                    ))}
                  </div>
                </section>
              ))}

              {personalPools.length === 0 && (
                <p className="text-center text-xs text-muted-foreground">
                  Nikt nie utworzył jeszcze puli osobistej.
                </p>
              )}
            </div>
          )}
        </>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <CreatePoolModal
          defaultPersonal={view === "personal"}
          onClose={() => setShowCreateModal(false)}
          onCreated={(isPersonal) => setView(isPersonal ? "personal" : "company")}
        />
      )}
    </div>
  );
}
