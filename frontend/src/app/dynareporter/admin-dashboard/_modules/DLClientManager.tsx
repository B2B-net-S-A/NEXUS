"use client";

/**
 * DL Clients Manager — Delivery Lead ↔ Klient assignments.
 *
 * Port `DLClientManager.tsx` z artur-t-96/InfraReporter.
 * Lista przypisań + add/remove form.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Plus,
  Trash2,
  Save,
  CheckCircle,
  AlertCircle,
  Crown,
  RefreshCw,
} from "lucide-react";
import {
  dynareporterAdminUsersApi,
  dynareporterAdminMasterDataApi,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function DLClientManager() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [selectedDl, setSelectedDl] = useState<number | null>(null);
  const [selectedClient, setSelectedClient] = useState<number | null>(null);
  const [isHead, setIsHead] = useState(false);
  const [status, setStatus] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  const assignmentsQuery = useQuery({
    queryKey: ["dr-admin-dl-clients"],
    queryFn: () => dynareporterAdminUsersApi.dlClients(),
    staleTime: 60_000,
  });

  const teamQuery = useQuery({
    queryKey: ["dr-admin-team-members"],
    queryFn: () => dynareporterAdminUsersApi.teamMembers(),
    staleTime: 5 * 60_000,
  });

  const clientsQuery = useQuery({
    queryKey: ["dr-admin-clients"],
    queryFn: () => dynareporterAdminMasterDataApi.clients(),
    staleTime: 5 * 60_000,
  });

  const addMutation = useMutation({
    mutationFn: () => {
      if (selectedDl === null || selectedClient === null)
        throw new Error("Wybierz DL i klienta");
      return dynareporterAdminUsersApi.addDlClient({
        delivery_lead_user_id: selectedDl,
        client_id: selectedClient,
        is_head: isHead,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-dl-clients"] });
      setShowForm(false);
      setSelectedDl(null);
      setSelectedClient(null);
      setIsHead(false);
      setStatus({ type: "success", msg: "Przypisanie dodane" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => dynareporterAdminUsersApi.deleteDlClient(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-dl-clients"] });
      setStatus({ type: "success", msg: "Przypisanie usunięte" });
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setStatus({ type: "error", msg: `Błąd usuwania: ${extractErrorMsg(e)}` });
    },
  });

  const dlList = (teamQuery.data ?? []).filter(
    (m) => m.role === "delivery_lead",
  );

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Building2 className="w-5 h-5 text-cyan-600" />
            DL ↔ Klienci ({assignmentsQuery.data?.length ?? "…"})
          </h3>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => assignmentsQuery.refetch()}
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </Button>
            <Button size="sm" onClick={() => setShowForm((s) => !s)}>
              <Plus className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">{showForm ? "Anuluj" : "Przypisz"}</span>
            </Button>
          </div>
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

        {/* Add form */}
        {showForm && (
          <div className="mb-4 p-3 bg-muted/40 rounded grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Delivery Lead
              </label>
              <select
                value={selectedDl ?? ""}
                onChange={(e) =>
                  setSelectedDl(e.target.value ? Number(e.target.value) : null)
                }
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              >
                <option value="">— wybierz DL —</option>
                {dlList.map((dl) => (
                  <option key={dl.id} value={dl.id}>
                    {dl.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Klient
              </label>
              <select
                value={selectedClient ?? ""}
                onChange={(e) =>
                  setSelectedClient(
                    e.target.value ? Number(e.target.value) : null,
                  )
                }
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              >
                <option value="">— wybierz klienta —</option>
                {(clientsQuery.data ?? [])
                  .filter((c) => c.is_active)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={isHead}
                  onChange={(e) => setIsHead(e.target.checked)}
                  className="rounded border-input"
                />
                <Crown className="w-4 h-4 text-yellow-600" />
                Head DL
              </label>
            </div>
            <div className="flex items-end">
              <Button
                size="sm"
                onClick={() => addMutation.mutate()}
                disabled={addMutation.isPending}
                className="w-full"
              >
                <Save className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">Zapisz</span>
              </Button>
            </div>
          </div>
        )}

        {/* Assignments table */}
        {assignmentsQuery.isLoading ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Ładowanie…
          </p>
        ) : !assignmentsQuery.data || assignmentsQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Brak przypisań DL ↔ Klient.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Delivery Lead
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Klient
                  </th>
                  <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                    Head?
                  </th>
                  <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                    Akcje
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {assignmentsQuery.data.map((a) => (
                  <tr key={a.id}>
                    <td className="px-2 py-2 font-medium">
                      {a.delivery_lead_name}
                    </td>
                    <td className="px-2 py-2 text-muted-foreground">
                      {a.client_name}
                    </td>
                    <td className="px-2 py-2 text-center">
                      {a.is_head ? (
                        <Badge variant="warning" size="sm">
                          <Crown className="w-3 h-3 mr-1" />
                          Head
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (
                            confirm(
                              `Usunąć przypisanie ${a.delivery_lead_name} → ${a.client_name}?`,
                            )
                          ) {
                            deleteMutation.mutate(a.id);
                          }
                        }}
                        aria-label={`Usuń ${a.delivery_lead_name}`}
                      >
                        <Trash2
                          className="w-4 h-4 text-rose-600"
                          aria-hidden="true"
                        />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
