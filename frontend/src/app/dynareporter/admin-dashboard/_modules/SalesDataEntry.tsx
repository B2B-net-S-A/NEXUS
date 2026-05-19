"use client";

/**
 * Sales Data Entry — admin tools dla działu Sales.
 *
 * Port `SalesDataEntry.tsx` z artur-t-96/InfraReporter:
 * - Dodawanie sales projects (z BDM assignment)
 * - Dodawanie sales people (HoD/BDM/SDR)
 * - Weekly activity entry (leads + offers per week)
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Briefcase,
  Plus,
  Save,
  CheckCircle,
  AlertCircle,
  Activity,
} from "lucide-react";
import {
  dynareporterAdminWritesApi,
  dynareporterSalesMgmtApi,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function isoWeekNumber(d: Date): number {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function SalesDataEntry() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"projects" | "people" | "activity">("projects");
  const [status, setStatus] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  // Projects state
  const [projectName, setProjectName] = useState("");
  const [projectBdm, setProjectBdm] = useState<number | null>(null);

  // People state
  const [personName, setPersonName] = useState("");
  const [personRole, setPersonRole] = useState<"hod" | "bdm" | "sdr">("bdm");
  const [personIsHod, setPersonIsHod] = useState(false);

  // Activity state
  const [activityWeek, setActivityWeek] = useState(todayIso());
  const [activityLeads, setActivityLeads] = useState(0);
  const [activityOffers, setActivityOffers] = useState(0);

  const projectsQuery = useQuery({
    queryKey: ["dr-sales-projects-admin"],
    queryFn: () => dynareporterSalesMgmtApi.projects(false),
    staleTime: 60_000,
  });

  const peopleQuery = useQuery({
    queryKey: ["dr-sales-people-admin"],
    queryFn: () => dynareporterSalesMgmtApi.people(false),
    staleTime: 60_000,
  });

  const activityQuery = useQuery({
    queryKey: ["dr-sales-activity-admin"],
    queryFn: () => dynareporterSalesMgmtApi.weeklyActivity(12),
    staleTime: 60_000,
    enabled: tab === "activity",
  });

  const addProjectMutation = useMutation({
    mutationFn: () => {
      if (!projectName.trim()) throw new Error("Nazwa wymagana");
      return dynareporterAdminWritesApi.addSalesProject({
        name: projectName,
        bdm_id: projectBdm,
        is_active: true,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-sales-projects-admin"] });
      setProjectName("");
      setProjectBdm(null);
      setStatus({ type: "success", msg: "Projekt dodany" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus({ type: "error", msg: `Błąd: ${String(e)}` }),
  });

  const addPersonMutation = useMutation({
    mutationFn: () => {
      if (!personName.trim()) throw new Error("Imię i nazwisko wymagane");
      return dynareporterAdminWritesApi.addSalesPerson({
        name: personName,
        role: personRole,
        is_hod: personIsHod,
        is_active: true,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-sales-people-admin"] });
      setPersonName("");
      setPersonRole("bdm");
      setPersonIsHod(false);
      setStatus({ type: "success", msg: "Osoba dodana" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus({ type: "error", msg: `Błąd: ${String(e)}` }),
  });

  const upsertActivityMutation = useMutation({
    mutationFn: () => {
      const d = new Date(activityWeek);
      return dynareporterAdminWritesApi.upsertWeeklyActivity({
        week_start: activityWeek,
        week_number: isoWeekNumber(d),
        year: d.getFullYear(),
        leads_count: activityLeads,
        offers_sent: activityOffers,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-sales-activity-admin"] });
      setActivityLeads(0);
      setActivityOffers(0);
      setStatus({ type: "success", msg: "Aktywność zapisana" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus({ type: "error", msg: `Błąd: ${String(e)}` }),
  });

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Briefcase className="w-5 h-5 text-green-600" />
            Sales — Wprowadzanie Danych
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

        {/* Tabs */}
        <div className="flex gap-1 border-b border-border mb-4">
          {[
            { type: "projects", label: "Projekty", icon: Briefcase },
            { type: "people", label: "Osoby", icon: Plus },
            { type: "activity", label: "Weekly Activity", icon: Activity },
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
                <label className="block text-xs text-muted-foreground mb-1">Nazwa projektu</label>
                <input
                  type="text"
                  placeholder="np. Klient X — Cloud Migration"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">BDM (opcjonalny)</label>
                <select
                  value={projectBdm ?? ""}
                  onChange={(e) =>
                    setProjectBdm(e.target.value ? Number(e.target.value) : null)
                  }
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  <option value="">— brak —</option>
                  {(peopleQuery.data ?? [])
                    .filter((p) => p.role === "bdm" && p.is_active)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
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
                          BDM ID
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
                            {p.bdm_id ?? "—"}
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

        {/* People tab */}
        {tab === "people" && (
          <div className="space-y-4">
            <div className="p-3 bg-muted/40 rounded grid grid-cols-1 md:grid-cols-4 gap-3">
              <div className="md:col-span-2">
                <label className="block text-xs text-muted-foreground mb-1">Imię i Nazwisko</label>
                <input
                  type="text"
                  placeholder="np. Jan Kowalski"
                  value={personName}
                  onChange={(e) => setPersonName(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Rola</label>
                <select
                  value={personRole}
                  onChange={(e) => setPersonRole(e.target.value as "hod" | "bdm" | "sdr")}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                >
                  <option value="hod">HoD</option>
                  <option value="bdm">BDM</option>
                  <option value="sdr">SDR</option>
                </select>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={personIsHod}
                    onChange={(e) => setPersonIsHod(e.target.checked)}
                    className="rounded border-input"
                  />
                  Head of Department
                </label>
              </div>
              <div className="md:col-span-4 flex justify-end">
                <Button
                  size="sm"
                  onClick={() => addPersonMutation.mutate()}
                  disabled={addPersonMutation.isPending}
                >
                  <Save className="w-4 h-4" aria-hidden="true" />
                  <span className="ml-1">Dodaj osobę</span>
                </Button>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2">
                Istniejące osoby ({peopleQuery.data?.length ?? "…"})
              </h4>
              {peopleQuery.isLoading ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Ładowanie…</p>
              ) : (peopleQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Brak osób.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Nazwa
                        </th>
                        <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          Rola
                        </th>
                        <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          HoD?
                        </th>
                        <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(peopleQuery.data ?? []).map((p) => (
                        <tr key={p.id} className={p.is_active ? "" : "opacity-60"}>
                          <td className="px-2 py-2 font-medium">{p.name}</td>
                          <td className="px-2 py-2 text-center">
                            <Badge variant="neutral" size="sm">
                              {p.role}
                            </Badge>
                          </td>
                          <td className="px-2 py-2 text-center">
                            {p.is_hod ? "✓" : "—"}
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

        {/* Activity tab */}
        {tab === "activity" && (
          <div className="space-y-4">
            <div className="p-3 bg-muted/40 rounded grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  Week start (poniedziałek)
                </label>
                <input
                  type="date"
                  value={activityWeek}
                  onChange={(e) => setActivityWeek(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Leads</label>
                <input
                  type="number"
                  min={0}
                  value={activityLeads}
                  onChange={(e) => setActivityLeads(Number(e.target.value))}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Offers sent</label>
                <input
                  type="number"
                  min={0}
                  value={activityOffers}
                  onChange={(e) => setActivityOffers(Number(e.target.value))}
                  className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                />
              </div>
              <div className="flex items-end">
                <Button
                  size="sm"
                  onClick={() => upsertActivityMutation.mutate()}
                  disabled={upsertActivityMutation.isPending}
                  className="w-full"
                >
                  <Save className="w-4 h-4" aria-hidden="true" />
                  <span className="ml-1">Zapisz</span>
                </Button>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold mb-2">Ostatnie 12 tygodni</h4>
              {activityQuery.isLoading ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Ładowanie…</p>
              ) : (activityQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">Brak danych.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Week
                        </th>
                        <th className="px-2 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Leads
                        </th>
                        <th className="px-2 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Offers
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(activityQuery.data ?? []).map((w) => (
                        <tr key={w.week_start}>
                          <td className="px-2 py-2 font-mono text-xs">
                            {w.week_start} (W{w.week_number}/{w.year})
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">
                            {w.leads_count}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">
                            {w.offers_sent}
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
      </CardContent>
    </Card>
  );
}
