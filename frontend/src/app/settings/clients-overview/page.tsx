"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { BarChart3, Building2, Crown, TrendingUp, Users } from "lucide-react";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { DlKpiRow, OverviewRow } from "@/lib/api/dlPortal";

type View = "clients" | "by-dl";

export default function AdminClientsOverviewPage() {
  const [view, setView] = useState<View>("clients");

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <header>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <BarChart3 className="w-6 h-6 text-violet-600" />
          Przegląd klientów (admin)
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Wszystkie aktywne klienty + KPI per Delivery Lead. Tylko admin /
          head_of_recruitment widzi te dane.
        </p>
      </header>

      <div className="flex gap-2 border-b border-border">
        <button
          onClick={() => setView("clients")}
          className={`px-4 py-2 text-sm font-medium border-b-2 ${
            view === "clients"
              ? "border-violet-600 text-violet-600"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Ranking klientów
        </button>
        <button
          onClick={() => setView("by-dl")}
          className={`px-4 py-2 text-sm font-medium border-b-2 ${
            view === "by-dl"
              ? "border-violet-600 text-violet-600"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          Leaderboard DL
        </button>
      </div>

      {view === "clients" ? <ClientsTable /> : <DlLeaderboard />}
    </div>
  );
}

function ClientsTable() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-clients-overview"],
    queryFn: async () => {
      const res = await dlPortalApi.adminOverview();
      return res.data;
    },
  });

  if (isLoading) return <div className="text-muted-foreground">Ładowanie…</div>;
  if (error) return <div className="text-destructive">Błąd ładowania.</div>;

  const rows: OverviewRow[] = data ?? [];

  return (
    <div className="border border-border rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 border-b border-border">
          <tr>
            <th className="text-left px-3 py-2 font-medium">#</th>
            <th className="text-left px-3 py-2 font-medium">Klient</th>
            <th className="text-left px-3 py-2 font-medium">Head DL</th>
            <th className="text-right px-3 py-2 font-medium">Revenue lifetime</th>
            <th className="text-right px-3 py-2 font-medium">Active</th>
            <th className="text-right px-3 py-2 font-medium">Marża/mc</th>
            <th className="text-right px-3 py-2 font-medium">Active orders</th>
            <th className="text-right px-3 py-2 font-medium">Konsultanci</th>
            <th className="text-left px-3 py-2 font-medium">MSA</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                Brak klientów.
              </td>
            </tr>
          ) : (
            rows.map((r, idx) => (
              <tr key={r.client_id} className="border-b border-border hover:bg-accent/30">
                <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                <td className="px-3 py-2">
                  <Link
                    href={`/clients/${r.client_id}?tab=analityka`}
                    className="font-medium hover:text-violet-600 flex items-center gap-1"
                  >
                    <Building2 className="w-3.5 h-3.5 text-muted-foreground" />
                    {r.name}
                  </Link>
                  {r.industry && (
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {r.industry}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.head_dl_name ? (
                    <span className="flex items-center gap-1">
                      <Crown className="w-3 h-3 text-violet-600" />
                      {r.head_dl_name}
                    </span>
                  ) : (
                    <span className="text-muted-foreground italic">brak</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-medium">
                  {fmt(r.total_revenue_all_time)}
                </td>
                <td className="px-3 py-2 text-right text-green-700">
                  {fmt(r.active_revenue)}
                </td>
                <td className="px-3 py-2 text-right text-violet-700">
                  {r.monthly_margin_total !== null ? r.monthly_margin_total : "–"}
                </td>
                <td className="px-3 py-2 text-right">{r.active_orders_count}</td>
                <td className="px-3 py-2 text-right">{r.active_consultants}</td>
                <td className="px-3 py-2 text-xs">
                  {r.framework_status ? (
                    <>
                      {r.framework_status}
                      {r.framework_expiry_date && (
                        <div className="text-muted-foreground">
                          do {r.framework_expiry_date}
                        </div>
                      )}
                    </>
                  ) : (
                    <span className="text-muted-foreground italic">brak</span>
                  )}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function DlLeaderboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-by-dl"],
    queryFn: async () => {
      const res = await dlPortalApi.adminByDl();
      return res.data;
    },
  });

  if (isLoading) return <div className="text-muted-foreground">Ładowanie…</div>;
  if (error) return <div className="text-destructive">Błąd ładowania.</div>;

  const rows: DlKpiRow[] = data ?? [];

  return (
    <div className="border border-border rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 border-b border-border">
          <tr>
            <th className="text-left px-3 py-2 font-medium">#</th>
            <th className="text-left px-3 py-2 font-medium">Delivery Lead</th>
            <th className="text-right px-3 py-2 font-medium">Klienci</th>
            <th className="text-right px-3 py-2 font-medium">Head clients</th>
            <th className="text-right px-3 py-2 font-medium">Revenue lifetime</th>
            <th className="text-right px-3 py-2 font-medium">Active</th>
            <th className="text-right px-3 py-2 font-medium">Marża/mc</th>
            <th className="text-right px-3 py-2 font-medium">Active orders</th>
            <th className="text-right px-3 py-2 font-medium">Konsultanci</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                Brak Delivery Leadów z przypisanymi klientami.
              </td>
            </tr>
          ) : (
            rows.map((r, idx) => (
              <tr key={r.dl_user_id} className="border-b border-border hover:bg-accent/30">
                <td className="px-3 py-2 text-muted-foreground">{idx + 1}</td>
                <td className="px-3 py-2">
                  <div className="font-medium flex items-center gap-1">
                    <Users className="w-3.5 h-3.5 text-muted-foreground" />
                    {r.dl_name}
                  </div>
                  <div className="text-xs text-muted-foreground">{r.dl_email}</div>
                </td>
                <td className="px-3 py-2 text-right">{r.managed_clients_count}</td>
                <td className="px-3 py-2 text-right">
                  <span className="flex items-center justify-end gap-1">
                    <Crown className="w-3 h-3 text-violet-600" />
                    {r.head_clients_count}
                  </span>
                </td>
                <td className="px-3 py-2 text-right font-medium">
                  {fmt(r.total_revenue)}
                </td>
                <td className="px-3 py-2 text-right text-green-700">
                  <span className="flex items-center justify-end gap-1">
                    <TrendingUp className="w-3 h-3" />
                    {fmt(r.active_revenue)}
                  </span>
                </td>
                <td className="px-3 py-2 text-right text-violet-700">
                  {r.monthly_margin_total !== null ? r.monthly_margin_total : "–"}
                </td>
                <td className="px-3 py-2 text-right">{r.active_orders_count}</td>
                <td className="px-3 py-2 text-right">{r.active_consultants}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function fmt(v: string | number | null): string {
  if (v === null || v === undefined) return "–";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "–";
  return num.toLocaleString("pl-PL");
}
