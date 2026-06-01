"use client";

/**
 * Recruitment Team Manager – admin CRUD na team assignments.
 *
 * Port `RecruitmentTeamManager.tsx` z artur-t-96/InfraReporter (695 linii).
 *
 * Funkcje (DR parity):
 * - 3 tabs: Członkowie (read) / TAC↔DL (CRUD) / Sourcer↔Kategoria (CRUD)
 * - TAC ↔ DL: add (TAC dropdown + DL dropdown) + delete + grouped per DL view
 * - Sourcer ↔ Kategoria: add (Sourcer + Category + Priority 1-5) + delete +
 *   priority upsert (ON CONFLICT update)
 */

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  GitBranch,
  Layers,
  RefreshCw,
  Plus,
  Trash2,
  CheckCircle,
  AlertCircle,
  Crown,
} from "lucide-react";
import {
  dynareporterAdminUsersApi,
  type DrTeamMember,
  type DrTacDlAssignment,
  type DrSourcerCategoryAssignment,
  type DrCompetenceCategoryRow,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const ROLE_LABEL: Record<string, string> = {
  sourcer: "Sourcer",
  tac: "TAC",
  recruiter: "Rekruter",
  delivery_lead: "Delivery Lead",
};

const ROLE_COLOR: Record<
  string,
  "neutral" | "success" | "warning" | "info"
> = {
  sourcer: "info",
  tac: "warning",
  recruiter: "success",
  delivery_lead: "neutral",
};

export function RecruitmentTeamManager() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"members" | "tac_dl" | "sourcer_cat">(
    "members",
  );
  const [status, setStatus] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  // TAC-DL form state
  const [tacFormTacId, setTacFormTacId] = useState<number | null>(null);
  const [tacFormDlId, setTacFormDlId] = useState<number | null>(null);
  const [showTacDlForm, setShowTacDlForm] = useState(false);

  // Sourcer-Category form state
  const [scFormSourcerId, setScFormSourcerId] = useState<number | null>(null);
  const [scFormCategoryId, setScFormCategoryId] = useState<number | null>(null);
  const [scFormPriority, setScFormPriority] = useState<1 | 2 | 3 | 4 | 5>(1);
  const [showScForm, setShowScForm] = useState(false);

  const showMessage = (type: "success" | "error", msg: string) => {
    setStatus({ type, msg });
    setTimeout(() => setStatus(null), 4000);
  };

  const membersQuery = useQuery({
    queryKey: ["dr-admin-team-members"],
    queryFn: () => dynareporterAdminUsersApi.teamMembers(),
    staleTime: 60_000,
  });

  const tacDlQuery = useQuery({
    queryKey: ["dr-admin-team-tac-dl"],
    queryFn: () => dynareporterAdminUsersApi.tacDl(),
    staleTime: 60_000,
    enabled: tab === "tac_dl",
  });

  const sourcerCatQuery = useQuery({
    queryKey: ["dr-admin-team-sourcer-cat"],
    queryFn: () => dynareporterAdminUsersApi.sourcerCategories(),
    staleTime: 60_000,
    enabled: tab === "sourcer_cat",
  });

  const categoriesQuery = useQuery({
    queryKey: ["dr-admin-team-categories"],
    queryFn: () => dynareporterAdminUsersApi.competenceCategories(),
    staleTime: 5 * 60_000,
    enabled: tab === "sourcer_cat",
  });

  // Filter team members for dropdowns
  const tacList = useMemo(
    () => (membersQuery.data ?? []).filter((m: DrTeamMember) => m.role === "tac"),
    [membersQuery.data],
  );
  const dlList = useMemo(
    () =>
      (membersQuery.data ?? []).filter(
        (m: DrTeamMember) => m.role === "delivery_lead",
      ),
    [membersQuery.data],
  );
  const sourcerList = useMemo(
    () =>
      (membersQuery.data ?? []).filter((m: DrTeamMember) => m.role === "sourcer"),
    [membersQuery.data],
  );

  // === TAC-DL mutations ===
  const addTacDlMutation = useMutation({
    mutationFn: () => {
      if (!tacFormTacId || !tacFormDlId) throw new Error("Wybierz TAC i DL");
      return dynareporterAdminUsersApi.addTacDl({
        tac_user_id: tacFormTacId,
        delivery_lead_user_id: tacFormDlId,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-team-tac-dl"] });
      setTacFormTacId(null);
      setTacFormDlId(null);
      setShowTacDlForm(false);
      showMessage("success", "Przypisanie TAC ↔ DL dodane");
    },
    onError: (e: unknown) => showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });

  const deleteTacDlMutation = useMutation({
    mutationFn: ({ tacId, dlId }: { tacId: number; dlId: number }) =>
      dynareporterAdminUsersApi.deleteTacDl(tacId, dlId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-team-tac-dl"] });
      showMessage("success", "Przypisanie usunięte");
    },
    onError: (e: unknown) => showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });

  // === Sourcer-Category mutations ===
  const upsertScMutation = useMutation({
    mutationFn: () => {
      if (!scFormSourcerId || !scFormCategoryId)
        throw new Error("Wybierz Sourcer i Kategorię");
      return dynareporterAdminUsersApi.upsertSourcerCategory({
        user_id: scFormSourcerId,
        category_id: scFormCategoryId,
        priority: scFormPriority,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-team-sourcer-cat"] });
      setScFormSourcerId(null);
      setScFormCategoryId(null);
      setScFormPriority(1);
      setShowScForm(false);
      showMessage("success", "Przypisanie Sourcer ↔ Kategoria zapisane");
    },
    onError: (e: unknown) => showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });

  const deleteScMutation = useMutation({
    mutationFn: ({ userId, catId }: { userId: number; catId: number }) =>
      dynareporterAdminUsersApi.deleteSourcerCategory(userId, catId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-team-sourcer-cat"] });
      showMessage("success", "Przypisanie usunięte");
    },
    onError: (e: unknown) => showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });

  // Group TAC-DL per DL (visual hierarchy)
  const tacDlGrouped = useMemo(() => {
    const all = tacDlQuery.data ?? [];
    const byDl: Record<
      string,
      { dl_name: string; dl_id: number; tacs: DrTacDlAssignment[] }
    > = {};
    for (const a of all) {
      const k = String(a.delivery_lead_user_id);
      if (!byDl[k])
        byDl[k] = {
          dl_name: a.delivery_lead_name,
          dl_id: a.delivery_lead_user_id,
          tacs: [],
        };
      byDl[k].tacs.push(a);
    }
    return Object.values(byDl)
      .map((g) => ({
        ...g,
        tacs: g.tacs.slice().sort((a, b) => a.tac_name.localeCompare(b.tac_name, "pl")),
      }))
      .sort((a, b) => a.dl_name.localeCompare(b.dl_name, "pl"));
  }, [tacDlQuery.data]);

  // Group Sourcer-Category per Sourcer
  const scGrouped = useMemo(() => {
    const all = sourcerCatQuery.data ?? [];
    const bySourcer: Record<
      string,
      {
        sourcer_name: string;
        sourcer_id: number;
        categories: DrSourcerCategoryAssignment[];
      }
    > = {};
    for (const a of all) {
      const k = String(a.user_id);
      if (!bySourcer[k])
        bySourcer[k] = {
          sourcer_name: a.sourcer_name,
          sourcer_id: a.user_id,
          categories: [],
        };
      bySourcer[k].categories.push(a);
    }
    return Object.values(bySourcer)
      .map((g) => ({
        ...g,
        categories: g.categories
          .slice()
          .sort((a, b) => a.priority - b.priority || a.category_name.localeCompare(b.category_name, "pl")),
      }))
      .sort((a, b) => a.sourcer_name.localeCompare(b.sourcer_name, "pl"));
  }, [sourcerCatQuery.data]);

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Users className="w-5 h-5 text-teal-600" />
            Zespół Rekrutacji
          </h3>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (tab === "members") membersQuery.refetch();
              if (tab === "tac_dl") tacDlQuery.refetch();
              if (tab === "sourcer_cat") {
                sourcerCatQuery.refetch();
                categoriesQuery.refetch();
              }
            }}
            aria-label="Odśwież dane"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
          </Button>
        </div>

        {status && (
          <div
            className={`mb-3 flex items-center gap-2 text-sm ${
              status.type === "success" ? "text-emerald-600" : "text-rose-600"
            }`}
          >
            {status.type === "success" ? (
              <CheckCircle className="w-4 h-4" />
            ) : (
              <AlertCircle className="w-4 h-4" />
            )}
            {status.msg}
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 border-b border-border mb-4">
          {[
            { type: "members", label: "Członkowie", icon: Users },
            { type: "tac_dl", label: "TAC ↔ DL", icon: GitBranch },
            { type: "sourcer_cat", label: "Sourcer ↔ Kategoria", icon: Layers },
          ].map((t) => {
            const Icon = t.icon;
            const isActive = tab === t.type;
            return (
              <button
                key={t.type}
                onClick={() => setTab(t.type as typeof tab)}
                className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                  isActive
                    ? "text-foreground border-primary"
                    : "text-muted-foreground border-transparent hover:text-foreground"
                }`}
                aria-pressed={isActive}
              >
                <Icon className="w-4 h-4" />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Tab: members (read-only) */}
        {tab === "members" && (
          <>
            {membersQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Ładowanie…
              </p>
            ) : (membersQuery.data ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak członków zespołu rekrutacji.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Imię i Nazwisko
                      </th>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Email
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Rola
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {(membersQuery.data ?? []).map((m) => (
                      <tr key={m.id}>
                        <td className="px-2 py-2 font-medium">{m.name}</td>
                        <td className="px-2 py-2 text-xs text-muted-foreground">
                          {m.email}
                        </td>
                        <td className="px-2 py-2 text-center">
                          <Badge
                            variant={ROLE_COLOR[m.role] ?? "neutral"}
                            size="sm"
                          >
                            {ROLE_LABEL[m.role] ?? m.role}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* Tab: TAC ↔ DL (CRUD) */}
        {tab === "tac_dl" && (
          <>
            <div className="mb-3 flex justify-end">
              <Button
                size="sm"
                onClick={() => setShowTacDlForm((s) => !s)}
                className="bg-teal-600 hover:bg-teal-700"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">
                  {showTacDlForm ? "Anuluj" : "Dodaj przypisanie"}
                </span>
              </Button>
            </div>

            {showTacDlForm && (
              <div className="mb-4 p-3 bg-muted/40 rounded grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    TAC
                  </label>
                  <select
                    value={tacFormTacId ?? ""}
                    onChange={(e) =>
                      setTacFormTacId(
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                    className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                    aria-label="Wybierz TAC"
                  >
                    <option value="">– wybierz TAC –</option>
                    {tacList.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Delivery Lead
                  </label>
                  <select
                    value={tacFormDlId ?? ""}
                    onChange={(e) =>
                      setTacFormDlId(
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                    className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                    aria-label="Wybierz Delivery Lead"
                  >
                    <option value="">– wybierz DL –</option>
                    {dlList.map((dl) => (
                      <option key={dl.id} value={dl.id}>
                        {dl.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end">
                  <Button
                    size="sm"
                    onClick={() => addTacDlMutation.mutate()}
                    disabled={addTacDlMutation.isPending}
                    className="w-full"
                  >
                    Zapisz
                  </Button>
                </div>
              </div>
            )}

            {tacDlQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Ładowanie…
              </p>
            ) : tacDlGrouped.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak przypisań TAC ↔ DL. Kliknij &quot;Dodaj przypisanie&quot;.
              </p>
            ) : (
              <div className="space-y-3">
                {tacDlGrouped.map((g) => (
                  <div
                    key={g.dl_id}
                    className="border border-border rounded-lg overflow-hidden"
                  >
                    <div className="bg-gradient-to-r from-teal-50 to-cyan-50 dark:from-teal-950/30 dark:to-cyan-950/30 px-4 py-2 border-b border-border flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Crown className="w-4 h-4 text-teal-600" />
                        <span className="font-semibold text-sm">{g.dl_name}</span>
                        <Badge variant="neutral" size="sm">
                          {g.tacs.length} {g.tacs.length === 1 ? "TAC" : "TAC-ów"}
                        </Badge>
                      </div>
                    </div>
                    <div className="divide-y divide-border">
                      {g.tacs.map((a) => (
                        <div
                          key={`${a.tac_user_id}-${a.delivery_lead_user_id}`}
                          className="px-4 py-2 flex items-center justify-between hover:bg-muted/40"
                        >
                          <span className="text-sm">{a.tac_name}</span>
                          <button
                            onClick={() => {
                              if (
                                confirm(
                                  `Usunąć przypisanie ${a.tac_name} → ${a.delivery_lead_name}?`,
                                )
                              ) {
                                deleteTacDlMutation.mutate({
                                  tacId: a.tac_user_id,
                                  dlId: a.delivery_lead_user_id,
                                });
                              }
                            }}
                            className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                            title="Usuń przypisanie"
                            aria-label={`Usuń ${a.tac_name}`}
                          >
                            <Trash2 className="w-4 h-4" aria-hidden="true" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Tab: Sourcer ↔ Kategoria (CRUD) */}
        {tab === "sourcer_cat" && (
          <>
            <div className="mb-3 flex justify-end">
              <Button
                size="sm"
                onClick={() => setShowScForm((s) => !s)}
                className="bg-teal-600 hover:bg-teal-700"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">
                  {showScForm ? "Anuluj" : "Dodaj przypisanie"}
                </span>
              </Button>
            </div>

            {showScForm && (
              <div className="mb-4 p-3 bg-muted/40 rounded grid grid-cols-1 md:grid-cols-4 gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Sourcer
                  </label>
                  <select
                    value={scFormSourcerId ?? ""}
                    onChange={(e) =>
                      setScFormSourcerId(
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                    className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                    aria-label="Wybierz Sourcer"
                  >
                    <option value="">– wybierz Sourcer –</option>
                    {sourcerList.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Kategoria
                  </label>
                  <select
                    value={scFormCategoryId ?? ""}
                    onChange={(e) =>
                      setScFormCategoryId(
                        e.target.value ? Number(e.target.value) : null,
                      )
                    }
                    className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                    aria-label="Wybierz Kategorię"
                  >
                    <option value="">– wybierz kategorię –</option>
                    {(categoriesQuery.data ?? [])
                      .filter((c: DrCompetenceCategoryRow) => c.is_active)
                      .map((c: DrCompetenceCategoryRow) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">
                    Priorytet
                  </label>
                  <select
                    value={scFormPriority}
                    onChange={(e) =>
                      setScFormPriority(Number(e.target.value) as 1 | 2 | 3 | 4 | 5)
                    }
                    className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                    aria-label="Priorytet (1-5)"
                  >
                    {[1, 2, 3, 4, 5].map((p) => (
                      <option key={p} value={p}>
                        P{p} {p === 1 ? "(główny)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end">
                  <Button
                    size="sm"
                    onClick={() => upsertScMutation.mutate()}
                    disabled={upsertScMutation.isPending}
                    className="w-full"
                  >
                    Zapisz
                  </Button>
                </div>
              </div>
            )}

            {sourcerCatQuery.isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Ładowanie…
              </p>
            ) : scGrouped.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                Brak przypisań Sourcer ↔ Kategoria.
              </p>
            ) : (
              <div className="space-y-3">
                {scGrouped.map((g) => (
                  <div
                    key={g.sourcer_id}
                    className="border border-border rounded-lg overflow-hidden"
                  >
                    <div className="bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/30 dark:to-purple-950/30 px-4 py-2 border-b border-border flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Layers className="w-4 h-4 text-indigo-600" />
                        <span className="font-semibold text-sm">
                          {g.sourcer_name}
                        </span>
                        <Badge variant="neutral" size="sm">
                          {g.categories.length}{" "}
                          {g.categories.length === 1 ? "kategoria" : "kategorii"}
                        </Badge>
                      </div>
                    </div>
                    <div className="divide-y divide-border">
                      {g.categories.map((a) => (
                        <div
                          key={`${a.user_id}-${a.category_id}`}
                          className="px-4 py-2 flex items-center justify-between hover:bg-muted/40"
                        >
                          <div className="flex items-center gap-2">
                            <Badge
                              variant={a.priority === 1 ? "success" : "neutral"}
                              size="sm"
                            >
                              P{a.priority}
                            </Badge>
                            <span className="text-sm">{a.category_name}</span>
                          </div>
                          <button
                            onClick={() => {
                              if (
                                confirm(
                                  `Usunąć przypisanie ${a.sourcer_name} → ${a.category_name} (P${a.priority})?`,
                                )
                              ) {
                                deleteScMutation.mutate({
                                  userId: a.user_id,
                                  catId: a.category_id,
                                });
                              }
                            }}
                            className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                            title="Usuń przypisanie"
                            aria-label={`Usuń ${a.category_name}`}
                          >
                            <Trash2 className="w-4 h-4" aria-hidden="true" />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
