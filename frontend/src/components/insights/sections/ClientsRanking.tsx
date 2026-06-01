"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Building2, Crown } from "lucide-react";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type { OverviewRow } from "@/lib/api/dlPortal";
import { fmtNumber, LoadingSpinner } from "./_shared";

export function ClientsRanking() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["insights-clients-overview"],
    queryFn: async () => (await dlPortalApi.adminOverview()).data,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error)
    return <div className="text-sm text-destructive py-4">Błąd ładowania rankingu klientów.</div>;

  const rows: OverviewRow[] = data ?? [];

  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Building2 className="w-5 h-5 text-primary" />
        Ranking klientów
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          {rows.length} aktywnych klientów · lifetime revenue
        </span>
      </h2>
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
                      className="font-medium hover:text-primary flex items-center gap-1"
                    >
                      <Building2 className="w-3.5 h-3.5 text-muted-foreground" />
                      {r.name}
                    </Link>
                    {r.industry && (
                      <div className="text-xs text-muted-foreground mt-0.5">{r.industry}</div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {r.head_dl_name ? (
                      <span className="flex items-center gap-1">
                        <Crown className="w-3 h-3 text-primary" />
                        {r.head_dl_name}
                      </span>
                    ) : (
                      <span className="text-muted-foreground italic">brak</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-medium">
                    {fmtNumber(r.total_revenue_all_time)}
                  </td>
                  <td className="px-3 py-2 text-right text-green-700">
                    {fmtNumber(r.active_revenue)}
                  </td>
                  <td className="px-3 py-2 text-right text-primary">
                    {r.monthly_margin_total !== null ? r.monthly_margin_total : "–"}
                  </td>
                  <td className="px-3 py-2 text-right">{r.active_orders_count}</td>
                  <td className="px-3 py-2 text-right">{r.active_consultants}</td>
                  <td className="px-3 py-2 text-xs">
                    {r.framework_status ? (
                      <>
                        {r.framework_status}
                        {r.framework_expiry_date && (
                          <div className="text-muted-foreground">do {r.framework_expiry_date}</div>
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
    </section>
  );
}
