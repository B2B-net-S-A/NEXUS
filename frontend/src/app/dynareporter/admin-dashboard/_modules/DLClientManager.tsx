"use client";

/**
 * DL Clients Manager – Delivery Lead ↔ Klient assignments.
 *
 * Port `DLClientManager.tsx` z artur-t-96/InfraReporter (485 linii).
 *
 * Funkcje (DR parity):
 * - **Grouped view** – assignments grupowane per DL (header z liczbą klientów +
 *   liczbą Head)
 * - **Toggle is_head inline** – click przycisk żeby zmienić Head/zwykły
 * - **Add form** – DL + Client + Head checkbox
 * - **Delete confirmation** modal
 * - **Search filter** – szukaj po DL name lub client name
 * - Sortuj klientów per DL (Head pierwszy)
 */

import { useState, useMemo } from "react";
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
  Search,
  X,
} from "lucide-react";
import {
  dynareporterAdminUsersApi,
  dynareporterAdminMasterDataApi,
  type DrDLClientAssignment,
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
  const [searchQuery, setSearchQuery] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [deletingMeta, setDeletingMeta] = useState<{
    dl_name: string;
    client_name: string;
  } | null>(null);
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

  const toggleHeadMutation = useMutation({
    mutationFn: ({ id, newIsHead }: { id: number; newIsHead: boolean }) =>
      dynareporterAdminUsersApi.patchDlClient(id, newIsHead),
    onSuccess: (_, { newIsHead }) => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-dl-clients"] });
      setStatus({
        type: "success",
        msg: newIsHead ? "Oznaczono jako Head DL" : "Usunięto status Head",
      });
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
      setDeletingId(null);
      setDeletingMeta(null);
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

  // Group assignments per DL (DR parity – visual hierarchy)
  const grouped = useMemo(() => {
    const all = assignmentsQuery.data ?? [];
    const filtered = searchQuery.trim()
      ? all.filter(
          (a) =>
            a.delivery_lead_name
              .toLowerCase()
              .includes(searchQuery.toLowerCase()) ||
            a.client_name.toLowerCase().includes(searchQuery.toLowerCase()),
        )
      : all;
    const byDl: Record<
      string,
      {
        dl_name: string;
        dl_id: number;
        assignments: DrDLClientAssignment[];
      }
    > = {};
    for (const a of filtered) {
      const key = String(a.delivery_lead_user_id);
      if (!byDl[key]) {
        byDl[key] = {
          dl_name: a.delivery_lead_name,
          dl_id: a.delivery_lead_user_id,
          assignments: [],
        };
      }
      byDl[key].assignments.push(a);
    }
    // Sort: by DL name, then within DL by is_head DESC + client_name
    return Object.values(byDl)
      .map((g) => ({
        ...g,
        assignments: g.assignments
          .slice()
          .sort((a, b) => {
            if (a.is_head !== b.is_head) return a.is_head ? -1 : 1;
            return a.client_name.localeCompare(b.client_name, "pl");
          }),
      }))
      .sort((a, b) => a.dl_name.localeCompare(b.dl_name, "pl"));
  }, [assignmentsQuery.data, searchQuery]);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Building2 className="w-5 h-5 text-cyan-600" />
              DL ↔ Klienci ({assignmentsQuery.data?.length ?? "…"})
            </h3>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => assignmentsQuery.refetch()}
                aria-label="Odśwież listę"
              >
                <RefreshCw className="w-4 h-4" aria-hidden="true" />
              </Button>
              <Button size="sm" onClick={() => setShowForm((s) => !s)}>
                <Plus className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">{showForm ? "Anuluj" : "Przypisz"}</span>
              </Button>
            </div>
          </div>

          {/* Search filter */}
          <div className="mb-3 relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filtruj po DL lub kliencie…"
              className="w-full pl-9 pr-9 py-1.5 text-sm bg-background border border-input rounded-md"
              aria-label="Szukaj DL lub klienta"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label="Wyczyść wyszukiwanie"
              >
                <X className="w-4 h-4" />
              </button>
            )}
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
                    setSelectedDl(
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
                  aria-label="Wybierz klienta"
                >
                  <option value="">– wybierz klienta –</option>
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
                <label className="flex items-center gap-2 text-sm cursor-pointer">
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

          {/* Grouped view per DL */}
          {assignmentsQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Ładowanie…
            </p>
          ) : grouped.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              {searchQuery
                ? `Brak przypisań pasujących do "${searchQuery}".`
                : "Brak przypisań DL ↔ Klient. Kliknij \"Przypisz\" aby dodać."}
            </p>
          ) : (
            <div className="space-y-3">
              {grouped.map((group) => {
                const headCount = group.assignments.filter(
                  (a) => a.is_head,
                ).length;
                return (
                  <div
                    key={group.dl_id}
                    className="border border-border rounded-lg overflow-hidden"
                  >
                    <div className="bg-gradient-to-r from-cyan-50 to-blue-50 dark:from-cyan-950/30 dark:to-blue-950/30 px-4 py-2 border-b border-border flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Building2 className="w-4 h-4 text-cyan-600" />
                        <span className="font-semibold text-sm">
                          {group.dl_name}
                        </span>
                        <Badge variant="neutral" size="sm">
                          {group.assignments.length}{" "}
                          {group.assignments.length === 1 ? "klient" : "klientów"}
                        </Badge>
                        {headCount > 0 && (
                          <Badge variant="warning" size="sm">
                            <Crown className="w-3 h-3 mr-1" />
                            {headCount} Head
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="divide-y divide-border">
                      {group.assignments.map((a) => (
                        <div
                          key={a.id}
                          className="px-4 py-2 flex items-center justify-between hover:bg-muted/40"
                        >
                          <div className="flex items-center gap-3">
                            {a.is_head ? (
                              <Crown
                                className="w-4 h-4 text-yellow-600"
                                aria-label="Head DL"
                              />
                            ) : (
                              <span className="w-4 h-4 inline-block" />
                            )}
                            <span className="text-sm">{a.client_name}</span>
                            {a.is_head && (
                              <Badge variant="warning" size="sm">
                                Head
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() =>
                                toggleHeadMutation.mutate({
                                  id: a.id,
                                  newIsHead: !a.is_head,
                                })
                              }
                              disabled={toggleHeadMutation.isPending}
                              className={`px-2 py-1 text-xs rounded transition-colors ${
                                a.is_head
                                  ? "bg-muted hover:bg-muted/70 text-muted-foreground"
                                  : "bg-yellow-100 dark:bg-yellow-900/30 hover:bg-yellow-200 dark:hover:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300"
                              }`}
                              title={
                                a.is_head
                                  ? "Usuń status Head"
                                  : "Oznacz jako Head DL"
                              }
                              aria-label={
                                a.is_head
                                  ? `Usuń Head status dla ${a.client_name}`
                                  : `Oznacz ${a.client_name} jako Head DL`
                              }
                            >
                              {a.is_head ? "✕ Head" : "👑 Head"}
                            </button>
                            <button
                              onClick={() => {
                                setDeletingId(a.id);
                                setDeletingMeta({
                                  dl_name: a.delivery_lead_name,
                                  client_name: a.client_name,
                                });
                              }}
                              className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                              title="Usuń przypisanie"
                              aria-label={`Usuń przypisanie ${a.delivery_lead_name} → ${a.client_name}`}
                            >
                              <Trash2
                                className="w-4 h-4"
                                aria-hidden="true"
                              />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Delete confirmation */}
      {deletingId !== null && deletingMeta && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <div className="text-center">
              <div className="w-12 h-12 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
                <Trash2 className="w-6 h-6 text-red-600" aria-hidden="true" />
              </div>
              <h3 className="text-lg font-semibold mb-2">Usunąć przypisanie?</h3>
              <p className="text-sm text-muted-foreground mb-6">
                <strong>{deletingMeta.dl_name}</strong> ↔{" "}
                <strong>{deletingMeta.client_name}</strong>
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setDeletingId(null);
                    setDeletingMeta(null);
                  }}
                  className="flex-1 px-4 py-2 bg-muted hover:bg-muted/70 rounded-lg"
                  disabled={deleteMutation.isPending}
                >
                  Anuluj
                </button>
                <button
                  onClick={() => deleteMutation.mutate(deletingId)}
                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 animate-spin inline" />
                  ) : (
                    "Usuń"
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
