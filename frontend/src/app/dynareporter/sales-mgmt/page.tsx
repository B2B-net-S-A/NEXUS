"use client";

/**
 * DynaReporter B.2.9 — Sales Management (projects/leads/offers/people).
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";

interface SalesProject {
  id: number;
  name: string;
  bdm_id?: number;
  is_active: boolean;
}
interface SalesPerson {
  id: number;
  name: string;
  role: string;
  is_hod: boolean;
  is_active: boolean;
}
interface SalesLead {
  id: number;
  user_id: number;
  week_start: string;
  company_name: string;
}
interface WeeklyActivity {
  week_start: string;
  week_number: number;
  year: number;
  leads_count: number;
  offers_sent: number;
}

export default function SalesMgmtPage() {
  const { user, hydrated } = useAuthStore();

  const projectsQ = useQuery({
    queryKey: ["dr", "sales-mgmt", "projects"],
    queryFn: () => api.get<SalesProject[]>("/api/dynareporter/sales-mgmt/projects").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "sales-mgmt"),
  });
  const peopleQ = useQuery({
    queryKey: ["dr", "sales-mgmt", "people"],
    queryFn: () => api.get<SalesPerson[]>("/api/dynareporter/sales-mgmt/people").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "sales-mgmt"),
  });
  const leadsQ = useQuery({
    queryKey: ["dr", "sales-mgmt", "leads"],
    queryFn: () => api.get<SalesLead[]>("/api/dynareporter/sales-mgmt/leads").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "sales-mgmt"),
  });
  const offersQ = useQuery({
    queryKey: ["dr", "sales-mgmt", "offers"],
    queryFn: () => api.get<SalesLead[]>("/api/dynareporter/sales-mgmt/offers").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "sales-mgmt"),
  });
  const weeklyQ = useQuery({
    queryKey: ["dr", "sales-mgmt", "weekly"],
    queryFn: () =>
      api.get<WeeklyActivity[]>("/api/dynareporter/sales-mgmt/weekly-activity").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "sales-mgmt"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "sales-mgmt")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">Brak sekcji <code>sales-mgmt</code>.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Sales — Zarządzanie</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Projekty, leady, oferty, ludzie, weekly activity.
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card label="Aktywne projekty" value={projectsQ.data?.length ?? "…"} />
        <Card label="Ludzie sales" value={peopleQ.data?.length ?? "…"} />
        <Card label="Leady (last 100)" value={leadsQ.data?.length ?? "…"} />
        <Card label="Oferty (last 100)" value={offersQ.data?.length ?? "…"} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">Sales people</h2>
          {peopleQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : (peopleQ.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">Brak danych.</p>
          ) : (
            <ul className="space-y-1.5">
              {(peopleQ.data ?? []).map((p) => (
                <li key={p.id} className="flex items-center justify-between text-xs">
                  <span className="font-medium">{p.name}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] uppercase">
                    {p.role}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">Projekty sales</h2>
          {projectsQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : (projectsQ.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">Brak danych.</p>
          ) : (
            <ul className="space-y-1.5 max-h-72 overflow-y-auto">
              {(projectsQ.data ?? []).map((p) => (
                <li key={p.id} className="text-xs truncate">
                  {p.name}
                  {p.bdm_id ? (
                    <span className="text-muted-foreground ml-1.5">(BDM #{p.bdm_id})</span>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Weekly activity (12 tyg)</h2>
        {weeklyQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (weeklyQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak danych.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Tydzień</th>
                  <th className="pb-2 font-medium text-right">Leady</th>
                  <th className="pb-2 font-medium text-right">Oferty</th>
                </tr>
              </thead>
              <tbody>
                {(weeklyQ.data ?? []).map((w) => (
                  <tr key={`${w.year}-W${w.week_number}`} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">
                      {w.week_start} <span className="text-muted-foreground">(W{w.week_number}/{w.year})</span>
                    </td>
                    <td className="py-2 text-right tabular-nums">{w.leads_count}</td>
                    <td className="py-2 text-right tabular-nums font-semibold">{w.offers_sent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
    </div>
  );
}
