"use client";

import { useQuery } from "@tanstack/react-query";
import { Crown, TrendingUp, Users } from "lucide-react";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { DlKpiRow } from "@/lib/api/dlPortal";
import { fmtNumber, LoadingSpinner } from "./_shared";

export function DLRevenueLeaderboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["insights-dl-leaderboard"],
    queryFn: async () => (await dlPortalApi.adminByDl()).data,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error)
    return (
      <div className="text-sm text-destructive py-4">Błąd ładowania leaderboardu DL.</div>
    );

  const rows: DlKpiRow[] = data ?? [];

  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Users className="w-5 h-5 text-primary" />
        Leaderboard Delivery Leadów
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          Revenue + Marża + Active orders/consultants (lifetime)
        </span>
      </h2>
      <div className="border border-border rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 border-b border-border">
            <tr>
              <th className="text-left px-3 py-2 font-medium">#</th>
              <th className="text-left px-3 py-2 font-medium">Delivery Lead</th>
              <th className="text-right px-3 py-2 font-medium">Klienci</th>
              <th className="text-right px-3 py-2 font-medium">Head clients</th>
              <th className="text-right px-3 py-2 font-medium">Revenue lifetime (PLN)</th>
              <th className="text-right px-3 py-2 font-medium">Active (PLN)</th>
              <th className="text-right px-3 py-2 font-medium">Marża/mc (PLN)</th>
              <th className="text-right px-3 py-2 font-medium">Active orders</th>
              <th className="text-right px-3 py-2 font-medium">Konsultanci / kontrakty</th>
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
                      <Crown className="w-3 h-3 text-primary" />
                      {r.head_clients_count}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    {fmtNumber(r.total_revenue)}
                  </td>
                  <td className="px-3 py-2 text-right text-green-700">
                    <span className="flex items-center justify-end gap-1">
                      <TrendingUp className="w-3 h-3" />
                      {fmtNumber(r.active_revenue)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-primary">
                    {r.monthly_margin_total !== null ? r.monthly_margin_total : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">{r.active_orders_count}</td>
                  <td className="px-3 py-2 text-right">
                    {r.active_consultants} / {r.active_contracts}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
