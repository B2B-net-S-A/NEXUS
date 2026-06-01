"use client";

/**
 * Employees Manager – admin CRUD na users + dr_user_seniority.
 *
 * Port skrócony `EmployeeManagement.tsx` z artur-t-96/InfraReporter
 * (oryginał: dodawanie userów, edycja role/sections – w Nexusie userzy są
 * zarządzani przez AAD + admin panel main Nexus). Tutaj fokus na:
 * - listę userów z search + filter active/role
 * - toggle is_active (admin)
 * - set seniority_level (junior/senior/expert) + acceleration dates
 *   dla acceleration path roles (sourcer/tac/recruiter)
 */

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users,
  Search,
  Power,
  Shield,
  Save,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  Key,
  X,
} from "lucide-react";
import {
  dynareporterAdminUsersApi,
  type DrEmployeeRow,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const ACCEL_ROLES = new Set(["sourcer", "tac", "recruiter"]);
const SENIORITY_LEVELS = [
  { value: "junior", label: "Junior" },
  { value: "senior", label: "Senior" },
  { value: "expert", label: "Expert" },
] as const;

type SeniorityLevel = (typeof SENIORITY_LEVELS)[number]["value"];

// Sekcje DR – canonical values matching `DynaReporterSection` type w
// `store/auth.ts` (DASHES nie underscores). Te same wartości używane są
// w middleware do route gating + w sidebar/nav. Były underscores w mojej
// wcześniejszej wersji ale DB i type używają DASHES (legacy DR migration).
const DR_SECTIONS = [
  { value: "body-leasing", label: "Rekrutacja (Body Leasing)" },
  { value: "delivery-lead", label: "Delivery Lead" },
  { value: "board", label: "Rada Nadzorcza" },
  { value: "competitions", label: "Liga Mistrzów" },
  { value: "clients-mrr", label: "Klienci + MRR" },
  { value: "placements", label: "Placements" },
  { value: "mindy", label: "MINDY AI" },
  { value: "sales-mgmt", label: "Sales Mgmt" },
  { value: "sales", label: "Sales" },
  { value: "przetargi", label: "Przetargi" },
  { value: "admin", label: "Admin (DR)" },
] as const;

function fullName(e: DrEmployeeRow): string {
  // Backend zwraca `name` (Nexus users.name). first_name/last_name jest fallback
  // dla compat z DR (gdzie były 2 kolumny).
  if (e.name && e.name.trim()) return e.name.trim();
  const trimmed = `${e.first_name ?? ""} ${e.last_name ?? ""}`.trim();
  return trimmed || e.email;
}

export function EmployeesManager() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "active" | "inactive"
  >("active");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editLevel, setEditLevel] = useState<SeniorityLevel>("junior");
  const [editStart, setEditStart] = useState("");
  const [editSenior, setEditSenior] = useState("");
  const [editExpert, setEditExpert] = useState("");
  // Allowed sections modal state
  const [editingSectionsUser, setEditingSectionsUser] =
    useState<DrEmployeeRow | null>(null);
  const [editSections, setEditSections] = useState<string[]>([]);
  const [status, setStatus] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  const employeesQuery = useQuery({
    queryKey: ["dr-admin-employees"],
    queryFn: () => dynareporterAdminUsersApi.employees(),
    staleTime: 30_000,
  });

  const seniorityMutation = useMutation({
    mutationFn: (params: { userId: number }) =>
      dynareporterAdminUsersApi.setSeniority(params.userId, {
        seniority_level: editLevel,
        acceleration_start_date: editStart || null,
        senior_since: editSenior || null,
        expert_since: editExpert || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-employees"] });
      setEditingId(null);
      setStatus({ type: "success", msg: "Seniority zaktualizowany" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const activeMutation = useMutation({
    mutationFn: (params: { userId: number; isActive: boolean }) =>
      dynareporterAdminUsersApi.toggleActive(params.userId, params.isActive),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-employees"] });
      setStatus({ type: "success", msg: "Status zmieniony" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const sectionsMutation = useMutation({
    mutationFn: () => {
      if (!editingSectionsUser) throw new Error("Brak usera");
      return dynareporterAdminUsersApi.updateAllowedSections(
        editingSectionsUser.id,
        editSections,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-employees"] });
      setEditingSectionsUser(null);
      setStatus({ type: "success", msg: "Sekcje DR zaktualizowane" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const openSectionsModal = (e: DrEmployeeRow) => {
    setEditingSectionsUser(e);
    setEditSections([...(e.allowed_sections ?? [])]);
  };

  const toggleSection = (s: string) => {
    setEditSections((prev) =>
      prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s],
    );
  };

  const rolesAvailable = useMemo(() => {
    const set = new Set<string>();
    (employeesQuery.data ?? []).forEach((e) => set.add(e.role));
    return Array.from(set).sort();
  }, [employeesQuery.data]);

  const filtered = useMemo(() => {
    const list = employeesQuery.data ?? [];
    return list.filter((e) => {
      if (statusFilter === "active" && !e.is_active) return false;
      if (statusFilter === "inactive" && e.is_active) return false;
      if (roleFilter !== "all" && e.role !== roleFilter) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const haystack =
          `${e.email} ${e.first_name ?? ""} ${e.last_name ?? ""}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [employeesQuery.data, statusFilter, roleFilter, searchQuery]);

  function startEdit(e: DrEmployeeRow) {
    setEditingId(e.id);
    setEditLevel((e.seniority_level ?? "junior") as SeniorityLevel);
    setEditStart(e.acceleration_start_date ?? "");
    setEditSenior(e.senior_since ?? "");
    setEditExpert(e.expert_since ?? "");
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Users className="w-5 h-5 text-amber-600" />
            Pracownicy i konta ({filtered.length})
          </h3>
          <Button
            size="sm"
            variant="outline"
            onClick={() => employeesQuery.refetch()}
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

        {/* Filters */}
        <div className="flex flex-wrap gap-3 mb-4 items-center">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Szukaj email / imię / nazwisko…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-sm w-full bg-background border border-input rounded-md"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as "all" | "active" | "inactive")
            }
            className="px-3 py-1.5 text-sm bg-background border border-input rounded-md"
            aria-label="Filter status"
          >
            <option value="active">Aktywni</option>
            <option value="inactive">Nieaktywni</option>
            <option value="all">Wszyscy</option>
          </select>
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="px-3 py-1.5 text-sm bg-background border border-input rounded-md"
            aria-label="Filter role"
          >
            <option value="all">Wszystkie role</option>
            {rolesAvailable.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        {/* Table */}
        {employeesQuery.isLoading ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Ładowanie…
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Brak wyników dla obecnych filtrów.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    User
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Email
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Rola
                  </th>
                  <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                    Status
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Seniority
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Sekcje DR
                  </th>
                  <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                    Akcje
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtered.map((e) => {
                  const isEditing = editingId === e.id;
                  const canSeniority = ACCEL_ROLES.has(e.role);
                  return (
                    <tr key={e.id} className={e.is_active ? "" : "opacity-50"}>
                      <td className="px-2 py-2 font-medium">{fullName(e)}</td>
                      <td className="px-2 py-2 text-xs text-muted-foreground">
                        {e.email}
                      </td>
                      <td className="px-2 py-2">
                        <Badge variant="neutral" size="sm">
                          {e.role}
                        </Badge>
                      </td>
                      <td className="px-2 py-2 text-center">
                        <Badge
                          variant={e.is_active ? "success" : "danger"}
                          size="sm"
                        >
                          {e.is_active ? "aktywny" : "wyłączony"}
                        </Badge>
                      </td>
                      <td className="px-2 py-2">
                        {!canSeniority ? (
                          <span className="text-xs text-muted-foreground italic">
                            –
                          </span>
                        ) : isEditing ? (
                          <div className="space-y-1">
                            <select
                              value={editLevel}
                              onChange={(ev) =>
                                setEditLevel(ev.target.value as SeniorityLevel)
                              }
                              className="w-full px-2 py-1 text-xs bg-background border border-input rounded-md"
                              aria-label="Seniority level"
                            >
                              {SENIORITY_LEVELS.map((lvl) => (
                                <option key={lvl.value} value={lvl.value}>
                                  {lvl.label}
                                </option>
                              ))}
                            </select>
                            <div className="grid grid-cols-3 gap-1">
                              <input
                                type="date"
                                value={editStart}
                                onChange={(ev) => setEditStart(ev.target.value)}
                                className="px-1 py-0.5 text-[10px] bg-background border border-input rounded"
                                aria-label="Acceleration start"
                                title="Acceleration start"
                              />
                              <input
                                type="date"
                                value={editSenior}
                                onChange={(ev) =>
                                  setEditSenior(ev.target.value)
                                }
                                className="px-1 py-0.5 text-[10px] bg-background border border-input rounded"
                                aria-label="Senior since"
                                title="Senior since"
                              />
                              <input
                                type="date"
                                value={editExpert}
                                onChange={(ev) =>
                                  setEditExpert(ev.target.value)
                                }
                                className="px-1 py-0.5 text-[10px] bg-background border border-input rounded"
                                aria-label="Expert since"
                                title="Expert since"
                              />
                            </div>
                          </div>
                        ) : (
                          <Badge
                            variant={
                              e.seniority_level === "expert"
                                ? "warning"
                                : e.seniority_level === "senior"
                                  ? "success"
                                  : "neutral"
                            }
                            size="sm"
                          >
                            <Shield className="w-3 h-3 mr-1" />
                            {e.seniority_level ?? "junior"}
                          </Badge>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        {(e.allowed_sections ?? []).length === 0 ? (
                          <span className="text-xs text-muted-foreground italic">
                            –
                          </span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {(e.allowed_sections ?? []).slice(0, 4).map((s) => (
                              <Badge key={s} variant="info" size="sm">
                                {DR_SECTIONS.find((d) => d.value === s)?.label ??
                                  s}
                              </Badge>
                            ))}
                            {(e.allowed_sections ?? []).length > 4 && (
                              <Badge variant="neutral" size="sm">
                                +{(e.allowed_sections ?? []).length - 4}
                              </Badge>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2 text-center">
                        {isEditing ? (
                          <div className="flex justify-center gap-1">
                            <Button
                              size="sm"
                              variant="primary"
                              onClick={() =>
                                seniorityMutation.mutate({ userId: e.id })
                              }
                              disabled={seniorityMutation.isPending}
                            >
                              <Save className="w-3 h-3" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setEditingId(null)}
                            >
                              ✕
                            </Button>
                          </div>
                        ) : (
                          <div className="flex justify-center gap-1">
                            {canSeniority && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => startEdit(e)}
                                title="Edytuj seniority"
                                aria-label="Edytuj seniority"
                              >
                                <Shield className="w-3 h-3" />
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => openSectionsModal(e)}
                              title="Edytuj sekcje DR"
                              aria-label={`Edytuj sekcje DR dla ${fullName(e)}`}
                            >
                              <Key className="w-3 h-3 text-blue-600" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                if (
                                  confirm(
                                    `${e.is_active ? "Wyłączyć" : "Włączyć"} konto ${fullName(e)}?`,
                                  )
                                ) {
                                  activeMutation.mutate({
                                    userId: e.id,
                                    isActive: !e.is_active,
                                  });
                                }
                              }}
                              aria-label={e.is_active ? "Wyłącz" : "Włącz"}
                            >
                              <Power
                                className={`w-3 h-3 ${
                                  e.is_active
                                    ? "text-rose-600"
                                    : "text-emerald-600"
                                }`}
                              />
                            </Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <p className="mt-4 text-xs text-muted-foreground italic">
          User creation + role + password → centralny admin panel Nexusa ({" "}
          <a href="/settings/users" className="text-primary hover:underline">
            /settings/users
          </a>
          , AAD/SSO managed). Tu zarządzasz seniority + active toggle +
          DR sekcje (allowed_sections).
        </p>

        {/* Allowed sections edit modal */}
        {editingSectionsUser && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-card rounded-xl shadow-xl w-full max-w-md mx-4">
              <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                <h3 className="text-lg font-semibold flex items-center gap-2">
                  <Key className="w-5 h-5 text-blue-600" />
                  Sekcje DR – {fullName(editingSectionsUser)}
                </h3>
                <button
                  onClick={() => setEditingSectionsUser(null)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label="Zamknij modal"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-6">
                <p className="text-sm text-muted-foreground mb-4">
                  Wybierz które sekcje DynaReportera są widoczne dla tego
                  usera (allowed_sections JSONB).
                </p>
                <div className="space-y-2">
                  {DR_SECTIONS.map((s) => (
                    <label
                      key={s.value}
                      className="flex items-center gap-2 cursor-pointer hover:bg-muted/40 p-2 rounded"
                    >
                      <input
                        type="checkbox"
                        checked={editSections.includes(s.value)}
                        onChange={() => toggleSection(s.value)}
                        className="rounded border-input"
                      />
                      <span className="text-sm">{s.label}</span>
                      <code className="ml-auto text-[10px] text-muted-foreground">
                        {s.value}
                      </code>
                    </label>
                  ))}
                </div>
              </div>
              <div className="px-6 py-4 bg-muted/40 flex justify-end gap-3 rounded-b-xl">
                <button
                  onClick={() => setEditingSectionsUser(null)}
                  className="px-4 py-2 hover:bg-muted rounded-lg"
                >
                  Anuluj
                </button>
                <button
                  onClick={() => sectionsMutation.mutate()}
                  disabled={sectionsMutation.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
                >
                  {sectionsMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4" />
                  )}
                  Zapisz zmiany
                </button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
