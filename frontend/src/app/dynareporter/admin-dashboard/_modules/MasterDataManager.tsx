"use client";

/**
 * Master Data Manager — read-only viewer dla dr_clients + dr_consultants.
 *
 * Port `MasterDataManager.tsx` z artur-t-96/InfraReporter.
 * Pełne CRUD (add/edit klientów + konsultantów + rates) planowane na
 * kolejną sesję jak będzie potrzeba edycji.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Database, RefreshCw, Building2, Users } from "lucide-react";
import { dynareporterAdminMasterDataApi } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function formatPLN(value: number): string {
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 2 }) + " zł";
}

export function MasterDataManager() {
  const [tab, setTab] = useState<"clients" | "consultants">("clients");

  const clientsQuery = useQuery({
    queryKey: ["dr-admin-clients"],
    queryFn: () => dynareporterAdminMasterDataApi.clients(),
    staleTime: 5 * 60_000,
  });
  const consultantsQuery = useQuery({
    queryKey: ["dr-admin-consultants"],
    queryFn: () => dynareporterAdminMasterDataApi.consultants(),
    staleTime: 5 * 60_000,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Database className="w-5 h-5 text-violet-600" />
              Master Data — Klienci i Konsultanci
            </h3>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                clientsQuery.refetch();
                consultantsQuery.refetch();
              }}
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="flex gap-1 border-b border-border mb-4">
            <button
              onClick={() => setTab("clients")}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${tab === "clients" ? "text-foreground border-primary" : "text-muted-foreground border-transparent hover:text-foreground"}`}
            >
              <Building2 className="w-4 h-4" />
              Klienci ({clientsQuery.data?.length ?? "…"})
            </button>
            <button
              onClick={() => setTab("consultants")}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${tab === "consultants" ? "text-foreground border-primary" : "text-muted-foreground border-transparent hover:text-foreground"}`}
            >
              <Users className="w-4 h-4" />
              Konsultanci ({consultantsQuery.data?.length ?? "…"})
            </button>
          </div>

          {tab === "clients" && (
            <>
              {clientsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
              ) : (clientsQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  Brak klientów w bazie.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Nazwa
                        </th>
                        <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          Status
                        </th>
                        <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Placements (all-time)
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(clientsQuery.data ?? []).map((c) => (
                        <tr key={c.id} className={c.is_active ? "" : "opacity-60"}>
                          <td className="px-3 py-2 text-sm font-medium">{c.name}</td>
                          <td className="px-3 py-2 text-center">
                            <Badge
                              variant={c.is_active ? "success" : "neutral"}
                              size="sm"
                            >
                              {c.is_active ? "aktywny" : "nieaktywny"}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm font-semibold">
                            {c.placements_count}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {tab === "consultants" && (
            <>
              {consultantsQuery.isLoading ? (
                <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
              ) : (consultantsQuery.data ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  Brak konsultantów w bazie.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Nazwa
                        </th>
                        <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Default cost rate
                        </th>
                        <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Default revenue rate
                        </th>
                        <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                          Status
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(consultantsQuery.data ?? []).map((k) => (
                        <tr key={k.id} className={k.is_active ? "" : "opacity-60"}>
                          <td className="px-3 py-2 text-sm font-medium">{k.name}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm">
                            {formatPLN(k.default_cost_rate)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm">
                            {formatPLN(k.default_revenue_rate)}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Badge
                              variant={k.is_active ? "success" : "neutral"}
                              size="sm"
                            >
                              {k.is_active ? "aktywny" : "nieaktywny"}
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

          <p className="mt-4 text-xs text-muted-foreground italic">
            Read-only view. Edycja (add/update/delete klientów + konsultantów +
            rates) — planowana w kolejnej sesji portu.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
