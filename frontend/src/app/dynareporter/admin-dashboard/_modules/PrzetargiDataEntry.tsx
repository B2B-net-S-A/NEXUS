"use client";

/**
 * Przetargi Data Entry — admin tools dla działu Zamówień Publicznych.
 *
 * Port `PrzetargiDataEntry.tsx` z artur-t-96/InfraReporter:
 * - Dodawanie projektów przetargowych
 * - Alokacje konsultantów per project per month
 * - Koszty per project per month
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FileText,
  Plus,
  Save,
  CheckCircle,
  AlertCircle,
  Users,
  DollarSign,
} from "lucide-react";
import {
  dynareporterAdminWritesApi,
  dynareporterPrzetargiAdminApi,
  dynareporterAdminMasterDataApi,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthStart(d: string): string {
  return d.slice(0, 7) + "-01";
}

function formatPLN(value: number): string {
  return (value || 0).toLocaleString("pl-PL", { maximumFractionDigits: 2 }) + " zł";
}

const COST_CATEGORIES = [
  { value: "other", label: "Inne" },
  { value: "license", label: "Licencja" },
  { value: "subcontractor", label: "Podwykonawca" },
  { value: "infrastructure", label: "Infrastruktura" },
  { value: "travel", label: "Podróż" },
];

export function PrzetargiDataEntry() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"projects" | "allocations" | "costs">("projects");
  const [status, setStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  // Projects
  const [projectName, setProjectName] = useState("");
  const [projectClient, setProjectClient] = useState<number | null>(null);

  // Allocations
  const [allocProject, setAllocProject] = useState<number | null>(null);
  const [allocConsultant, setAllocConsultant] = useState<number | null>(null);
  const [allocMonth, setAllocMonth] = useState(monthStart(todayIso()));
  const [allocHours, setAllocHours] = useState(0);
  const [allocCostRate, setAllocCostRate] = useState(0);
  const [allocRevRate, setAllocRevRate] = useState(0);

  // Costs
  const [costProject, setCostProject] = useState<number | null>(null);
  const [costMonth, setCostMonth] = useState(monthStart(todayIso()));
  const [costDesc, setCostDesc] = useState("");
  const [costValue, setCostValue] = useState(0);
  const [costCategory, setCostCategory] = useState("other");

  const projectsQuery = useQuery({
    queryKey: ["dr-przetargi-projects-admin"],
    queryFn: () => dynareporterPrzetargiAdminApi.projects(),
    staleTime: 60_000,
  });

  const consultantsQuery = useQuery({
    queryKey: ["dr-przetargi-consultants-admin"],
    queryFn: () => dynareporterPrzetargiAdminApi.consultants(),
    staleTime: 60_000,
  });

  const allocationsQuery = useQuery({
    queryKey: ["dr-przetargi-allocations-admin"],
    queryFn: () => dynareporterPrzetargiAdminApi.allocations(),
    staleTime: 60_000,
    enabled: tab === "allocations",
  });

  const clientsQuery = useQuery({
    queryKey: ["dr-admin-clients"],
    queryFn: () => dynareporterAdminMasterDataApi.clients(),
    staleTime: 5 * 60_000,
  });

  const addProjectMutation = useMutation({
    mutationFn: () => {
      if (!projectName.trim()) throw new Error("Nazwa wymagana");
      return dynareporterAdminWritesApi.addPrzetargiProject({
        name: projectName,
        client_id: projectClient,
        is_active: true,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-przetargi-projects-admin"] });
      setProjectName("");
      setProjectClient(null);
      setStatus({ type: "success", msg: "Projekt dodany" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus({ type: "error", msg: `Błąd: ${String(e)}` }),
  });

  const upsertAllocMutation = useMutation({
    mutationFn: () => {
      if (allocProject === null || allocConsultant === null)
        throw new Error("Wybierz projekt i konsultanta");
      return dynareporterAdminWritesApi.upsertPrzetargiAllocation({
        project_id: allocProject,
        consultant_id: allocConsultant,
        month: allocMonth,
        hours: allocHours,
        cost_rate: allocCostRate,
        revenue_rate: allocRevRate,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-przetargi-allocations-admin"] });
      setStatus({ type: "success", msg: "Alokacja zapisana" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus({ type: "error", msg: `Błąd: ${String(e)}` }),
  });

  const addCostMutation = useMutation({
    mutationFn: () => {
      if (costProject === null) throw new Error("Wybierz projekt");
      if (!costDesc.trim()) throw new Error("Opis wymagany");
      return dynareporterAdminWritesApi.addPrzetargiCost({
        project_id: costProject,
        month: costMonth,
        description: costDesc,
        value: costValue,
        category: costCategory,
      });
    },
    onSuccess: () => {
      setCostDesc("");
      setCostValue(0);
      setCostCategory("other");
      setStatus({ type: "success", msg: "Koszt dodany" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus({ type: "error", msg: `Błąd: ${String(e)}` }),
  });

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <FileText className="w-5 h-5 text-indigo-600" />
            Przetargi — Wprowadzanie Danych
          </h3>
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

        <div className="flex gap-1 border-b border-border mb-4">
          {[
            { type: "projects", label: "Projekty", icon: FileText },
            { type: "allocations", label: "Alokacje", icon: Users },
            { type: "costs", label: "Koszty", icon: DollarSign },
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
              >
                <Icon className="w-4 h-4" />
                {t.label}
              </button>
            );
          })}
        </div>

        {/* Projects tab */}
        {tab === "projects" && (
          <div className="space-y-4">
            <div className="p-3 bg-muted/40 rounded grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-2">
                <label className="block text-xs text-muted-foreground mb-1">
                  Nazwa projektu
                </label>
                <input
                  type="text"
                  placeholder="np. ZP-2026-XX Centralna Komisja Egzaminacyjna"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Klient (opcjonalny)
                </label>
                <select
                  value={projectClient ?? ""}
                  onChange={(e) =>
                    setProjectClient(e.target.value ? Number(e.target.value) : null)
                  }
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  <option value="">— brak —</option>
                  {(clientsQuery.data ?? [])
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </div>
              <div className="md:col-span-3 flex justify-end">
                <Button
                  size="sm"
                  onClick={() => addProjectMutation.mutate()}
                  disabled={addProjectMutation.isPending}
                >
                  <Save className="w-4 h-4" aria-hidden="true" />
                  <span className="ml-1">Dodaj projekt</span>
                </Button>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2">
                Istniejące projekty ({projectsQuery.data?.length ?? "…"})
              </h4>
              {projectsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Ładowanie…</p>
              ) : (projectsQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Brak projektów.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Nazwa
                        </th>
                        <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          Client ID
                        </th>
                        <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(projectsQuery.data ?? []).map((p) => (
                        <tr key={p.id} className={p.is_active ? "" : "opacity-60"}>
                          <td className="px-2 py-2 font-medium">{p.name}</td>
                          <td className="px-2 py-2 text-center text-muted-foreground">
                            {p.client_id ?? "—"}
                          </td>
                          <td className="px-2 py-2 text-center">
                            <Badge variant={p.is_active ? "success" : "neutral"} size="sm">
                              {p.is_active ? "aktywny" : "nieaktywny"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Allocations tab */}
        {tab === "allocations" && (
          <div className="space-y-4">
            <div className="p-3 bg-muted/40 rounded grid grid-cols-2 md:grid-cols-6 gap-3">
              <div className="md:col-span-2">
                <label className="block text-xs text-muted-foreground mb-1">Projekt</label>
                <select
                  value={allocProject ?? ""}
                  onChange={(e) =>
                    setAllocProject(e.target.value ? Number(e.target.value) : null)
                  }
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  <option value="">— wybierz —</option>
                  {(projectsQuery.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="block text-xs text-muted-foreground mb-1">Konsultant</label>
                <select
                  value={allocConsultant ?? ""}
                  onChange={(e) =>
                    setAllocConsultant(e.target.value ? Number(e.target.value) : null)
                  }
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  <option value="">— wybierz —</option>
                  {(consultantsQuery.data ?? [])
                    .filter((c) => c.is_active)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Miesiąc</label>
                <input
                  type="month"
                  value={allocMonth.slice(0, 7)}
                  onChange={(e) => setAllocMonth(`${e.target.value}-01`)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Godziny</label>
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={allocHours}
                  onChange={(e) => setAllocHours(Number(e.target.value))}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Stawka kosztu (PLN/h)
                </label>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={allocCostRate}
                  onChange={(e) => setAllocCostRate(Number(e.target.value))}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Stawka przychodu (PLN/h)
                </label>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={allocRevRate}
                  onChange={(e) => setAllocRevRate(Number(e.target.value))}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div className="md:col-span-6 flex justify-end items-center gap-3">
                <span className="text-xs text-muted-foreground">
                  Przychód: {formatPLN(allocHours * allocRevRate)} · Koszt:{" "}
                  {formatPLN(allocHours * allocCostRate)} · Marża:{" "}
                  <strong>{formatPLN(allocHours * (allocRevRate - allocCostRate))}</strong>
                </span>
                <Button
                  size="sm"
                  onClick={() => upsertAllocMutation.mutate()}
                  disabled={upsertAllocMutation.isPending}
                >
                  <Save className="w-4 h-4" aria-hidden="true" />
                  <span className="ml-1">Zapisz alokację</span>
                </Button>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2">
                Istniejące alokacje ({allocationsQuery.data?.length ?? "…"})
              </h4>
              {allocationsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Ładowanie…</p>
              ) : (allocationsQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">
                  Brak alokacji.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Projekt
                        </th>
                        <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Konsultant
                        </th>
                        <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Miesiąc
                        </th>
                        <th className="px-2 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          h
                        </th>
                        <th className="px-2 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Marża
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(allocationsQuery.data ?? []).slice(0, 50).map((a) => (
                        <tr key={a.id}>
                          <td className="px-2 py-2 font-medium">
                            {a.project_name ?? `#${a.project_id}`}
                          </td>
                          <td className="px-2 py-2 text-muted-foreground">
                            {a.consultant_name ?? `#${a.consultant_id}`}
                          </td>
                          <td className="px-2 py-2 font-mono text-xs">
                            {a.month?.slice(0, 7)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">{a.hours}</td>
                          <td className="px-2 py-2 text-right tabular-nums">
                            {formatPLN(a.margin)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Costs tab */}
        {tab === "costs" && (
          <div className="space-y-4">
            <div className="p-3 bg-muted/40 rounded grid grid-cols-2 md:grid-cols-5 gap-3">
              <div className="md:col-span-2">
                <label className="block text-xs text-muted-foreground mb-1">Projekt</label>
                <select
                  value={costProject ?? ""}
                  onChange={(e) =>
                    setCostProject(e.target.value ? Number(e.target.value) : null)
                  }
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  <option value="">— wybierz —</option>
                  {(projectsQuery.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Miesiąc</label>
                <input
                  type="month"
                  value={costMonth.slice(0, 7)}
                  onChange={(e) => setCostMonth(`${e.target.value}-01`)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Kategoria</label>
                <select
                  value={costCategory}
                  onChange={(e) => setCostCategory(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  {COST_CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Wartość (PLN)</label>
                <input
                  type="number"
                  step={0.01}
                  value={costValue}
                  onChange={(e) => setCostValue(Number(e.target.value))}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div className="md:col-span-5">
                <label className="block text-xs text-muted-foreground mb-1">Opis</label>
                <input
                  type="text"
                  placeholder="np. Licencja Confluence, kwiecień 2026"
                  value={costDesc}
                  onChange={(e) => setCostDesc(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div className="md:col-span-5 flex justify-end">
                <Button
                  size="sm"
                  onClick={() => addCostMutation.mutate()}
                  disabled={addCostMutation.isPending}
                >
                  <Plus className="w-4 h-4" aria-hidden="true" />
                  <span className="ml-1">Dodaj koszt</span>
                </Button>
              </div>
            </div>

            <p className="text-xs text-muted-foreground italic">
              Koszty są agregowane w widoku DL/Board dla margin calc per projekt.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
