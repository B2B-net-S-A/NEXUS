"use client";

/**
 * Master Data Manager – admin CRUD na dr_clients + dr_consultants.
 *
 * Pełen port `MasterDataManager.tsx` z artur-t-96/InfraReporter (564 linii).
 *
 * Funkcje (DR parity):
 * - 2 tabs: Klienci (clients) + Konsultanci (consultants)
 * - Add modal (per type)
 * - Edit inline w modalu (z pre-populated form)
 * - Toggle active/inactive (soft-delete)
 * - Delete confirmation
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Database,
  RefreshCw,
  Building2,
  Users,
  Plus,
  Edit2,
  Trash2,
  X,
  CheckCircle,
  AlertCircle,
  Save,
} from "lucide-react";
import {
  dynareporterAdminMasterDataApi,
  type DrAdminClientRow,
  type DrAdminConsultantRow,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function formatPLN(value: number): string {
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 2 }) + " zł";
}

type Tab = "clients" | "consultants";

type ClientFormState = { name: string; is_active: boolean };
type ConsultantFormState = {
  name: string;
  is_active: boolean;
  default_cost_rate: number;
  default_revenue_rate: number;
};

export function MasterDataManager() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("clients");
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // Modal state
  const [showClientModal, setShowClientModal] = useState(false);
  const [editingClient, setEditingClient] = useState<DrAdminClientRow | null>(
    null,
  );
  const [clientForm, setClientForm] = useState<ClientFormState>({
    name: "",
    is_active: true,
  });

  const [showConsultantModal, setShowConsultantModal] = useState(false);
  const [editingConsultant, setEditingConsultant] =
    useState<DrAdminConsultantRow | null>(null);
  const [consultantForm, setConsultantForm] = useState<ConsultantFormState>({
    name: "",
    is_active: true,
    default_cost_rate: 0,
    default_revenue_rate: 0,
  });

  const [deletingClientId, setDeletingClientId] = useState<number | null>(null);
  const [deletingConsultantId, setDeletingConsultantId] = useState<
    number | null
  >(null);

  // Queries
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

  const showMessage = (type: "success" | "error", text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 4000);
  };

  // === CLIENTS ===
  const createClientMutation = useMutation({
    mutationFn: () =>
      dynareporterAdminMasterDataApi.createClient({
        name: clientForm.name.trim(),
        is_active: clientForm.is_active,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-clients"] });
      showMessage("success", "Klient dodany");
      closeClientModal();
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });
  const updateClientMutation = useMutation({
    mutationFn: () =>
      dynareporterAdminMasterDataApi.updateClient(editingClient!.id, {
        name: clientForm.name.trim(),
        is_active: clientForm.is_active,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-clients"] });
      showMessage("success", "Klient zaktualizowany");
      closeClientModal();
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });
  const toggleClientActiveMutation = useMutation({
    mutationFn: (c: DrAdminClientRow) =>
      dynareporterAdminMasterDataApi.updateClient(c.id, {
        is_active: !c.is_active,
      }),
    onSuccess: (_, c) => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-clients"] });
      showMessage("success", c.is_active ? "Klient dezaktywowany" : "Klient aktywowany");
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });
  const deleteClientMutation = useMutation({
    mutationFn: (clientId: number) =>
      dynareporterAdminMasterDataApi.deleteClient(clientId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-clients"] });
      showMessage("success", "Klient dezaktywowany");
      setDeletingClientId(null);
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });

  const openNewClient = () => {
    setEditingClient(null);
    setClientForm({ name: "", is_active: true });
    setShowClientModal(true);
  };
  const openEditClient = (c: DrAdminClientRow) => {
    setEditingClient(c);
    setClientForm({ name: c.name, is_active: c.is_active });
    setShowClientModal(true);
  };
  const closeClientModal = () => {
    setShowClientModal(false);
    setEditingClient(null);
  };
  const saveClient = () => {
    if (!clientForm.name.trim()) {
      showMessage("error", "Nazwa klienta jest wymagana");
      return;
    }
    if (editingClient) updateClientMutation.mutate();
    else createClientMutation.mutate();
  };

  // === CONSULTANTS ===
  const createConsultantMutation = useMutation({
    mutationFn: () =>
      dynareporterAdminMasterDataApi.createConsultant({
        name: consultantForm.name.trim(),
        is_active: consultantForm.is_active,
        default_cost_rate: consultantForm.default_cost_rate,
        default_revenue_rate: consultantForm.default_revenue_rate,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-consultants"] });
      showMessage("success", "Konsultant dodany");
      closeConsultantModal();
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });
  const updateConsultantMutation = useMutation({
    mutationFn: () =>
      dynareporterAdminMasterDataApi.updateConsultant(editingConsultant!.id, {
        name: consultantForm.name.trim(),
        is_active: consultantForm.is_active,
        default_cost_rate: consultantForm.default_cost_rate,
        default_revenue_rate: consultantForm.default_revenue_rate,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-consultants"] });
      showMessage("success", "Konsultant zaktualizowany");
      closeConsultantModal();
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });
  const toggleConsultantActiveMutation = useMutation({
    mutationFn: (k: DrAdminConsultantRow) =>
      dynareporterAdminMasterDataApi.updateConsultant(k.id, {
        is_active: !k.is_active,
      }),
    onSuccess: (_, k) => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-consultants"] });
      showMessage(
        "success",
        k.is_active ? "Konsultant dezaktywowany" : "Konsultant aktywowany",
      );
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });
  const deleteConsultantMutation = useMutation({
    mutationFn: (consultantId: number) =>
      dynareporterAdminMasterDataApi.deleteConsultant(consultantId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-consultants"] });
      showMessage("success", "Konsultant dezaktywowany");
      setDeletingConsultantId(null);
    },
    onError: (e: unknown) =>
      showMessage("error", `Błąd: ${extractErrorMsg(e)}`),
  });

  const openNewConsultant = () => {
    setEditingConsultant(null);
    setConsultantForm({
      name: "",
      is_active: true,
      default_cost_rate: 0,
      default_revenue_rate: 0,
    });
    setShowConsultantModal(true);
  };
  const openEditConsultant = (k: DrAdminConsultantRow) => {
    setEditingConsultant(k);
    setConsultantForm({
      name: k.name,
      is_active: k.is_active,
      default_cost_rate: k.default_cost_rate,
      default_revenue_rate: k.default_revenue_rate,
    });
    setShowConsultantModal(true);
  };
  const closeConsultantModal = () => {
    setShowConsultantModal(false);
    setEditingConsultant(null);
  };
  const saveConsultant = () => {
    if (!consultantForm.name.trim()) {
      showMessage("error", "Nazwa konsultanta jest wymagana");
      return;
    }
    if (editingConsultant) updateConsultantMutation.mutate();
    else createConsultantMutation.mutate();
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Database className="w-5 h-5 text-violet-600" />
              Master Data – Klienci i Konsultanci
            </h3>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  clientsQuery.refetch();
                  consultantsQuery.refetch();
                }}
                aria-label="Odśwież dane"
              >
                <RefreshCw className="w-4 h-4" aria-hidden="true" />
              </Button>
              <Button
                size="sm"
                onClick={tab === "clients" ? openNewClient : openNewConsultant}
                className="bg-violet-600 hover:bg-violet-700"
              >
                <Plus className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">
                  {tab === "clients" ? "Dodaj klienta" : "Dodaj konsultanta"}
                </span>
              </Button>
            </div>
          </div>

          {message && (
            <div
              className={`mb-4 p-3 rounded-lg flex items-center gap-2 text-sm ${
                message.type === "success"
                  ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                  : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400"
              }`}
            >
              {message.type === "success" ? (
                <CheckCircle className="w-4 h-4" />
              ) : (
                <AlertCircle className="w-4 h-4" />
              )}
              {message.text}
            </div>
          )}

          <div className="flex gap-1 border-b border-border mb-4">
            <button
              onClick={() => setTab("clients")}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${tab === "clients" ? "text-foreground border-primary" : "text-muted-foreground border-transparent hover:text-foreground"}`}
              aria-pressed={tab === "clients"}
            >
              <Building2 className="w-4 h-4" />
              Klienci ({clientsQuery.data?.length ?? "…"})
            </button>
            <button
              onClick={() => setTab("consultants")}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors border-b-2 ${tab === "consultants" ? "text-foreground border-primary" : "text-muted-foreground border-transparent hover:text-foreground"}`}
              aria-pressed={tab === "consultants"}
            >
              <Users className="w-4 h-4" />
              Konsultanci ({consultantsQuery.data?.length ?? "…"})
            </button>
          </div>

          {tab === "clients" && (
            <ClientsTable
              clients={clientsQuery.data ?? []}
              isLoading={clientsQuery.isLoading}
              onEdit={openEditClient}
              onToggleActive={(c) => toggleClientActiveMutation.mutate(c)}
              onDelete={(id) => setDeletingClientId(id)}
            />
          )}

          {tab === "consultants" && (
            <ConsultantsTable
              consultants={consultantsQuery.data ?? []}
              isLoading={consultantsQuery.isLoading}
              onEdit={openEditConsultant}
              onToggleActive={(k) => toggleConsultantActiveMutation.mutate(k)}
              onDelete={(id) => setDeletingConsultantId(id)}
            />
          )}
        </CardContent>
      </Card>

      {/* Client Modal */}
      {showClientModal && (
        <Modal
          title={editingClient ? "Edytuj klienta" : "Dodaj klienta"}
          icon={<Building2 className="w-5 h-5 text-violet-600" />}
          onClose={closeClientModal}
          onSubmit={saveClient}
          isSubmitting={
            createClientMutation.isPending || updateClientMutation.isPending
          }
          submitLabel={editingClient ? "Zapisz zmiany" : "Dodaj"}
        >
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                Nazwa klienta
              </label>
              <input
                type="text"
                value={clientForm.name}
                onChange={(e) =>
                  setClientForm((p) => ({ ...p, name: e.target.value }))
                }
                placeholder="np. Nordea Bank"
                className="w-full px-3 py-2 border border-input rounded-lg bg-background"
                autoFocus
                aria-label="Nazwa klienta"
              />
            </div>
            <div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={clientForm.is_active}
                  onChange={(e) =>
                    setClientForm((p) => ({
                      ...p,
                      is_active: e.target.checked,
                    }))
                  }
                  className="rounded border-input"
                />
                Aktywny
              </label>
            </div>
          </div>
        </Modal>
      )}

      {/* Consultant Modal */}
      {showConsultantModal && (
        <Modal
          title={editingConsultant ? "Edytuj konsultanta" : "Dodaj konsultanta"}
          icon={<Users className="w-5 h-5 text-violet-600" />}
          onClose={closeConsultantModal}
          onSubmit={saveConsultant}
          isSubmitting={
            createConsultantMutation.isPending ||
            updateConsultantMutation.isPending
          }
          submitLabel={editingConsultant ? "Zapisz zmiany" : "Dodaj"}
        >
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                Nazwa konsultanta
              </label>
              <input
                type="text"
                value={consultantForm.name}
                onChange={(e) =>
                  setConsultantForm((p) => ({ ...p, name: e.target.value }))
                }
                placeholder="np. Jan Kowalski"
                className="w-full px-3 py-2 border border-input rounded-lg bg-background"
                autoFocus
                aria-label="Nazwa konsultanta"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium mb-1">
                  Cost rate (PLN/h)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={consultantForm.default_cost_rate || ""}
                  onChange={(e) =>
                    setConsultantForm((p) => ({
                      ...p,
                      default_cost_rate: Number(e.target.value) || 0,
                    }))
                  }
                  placeholder="0.00"
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background tabular-nums"
                  aria-label="Default cost rate w PLN na godzinę"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">
                  Revenue rate (PLN/h)
                </label>
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={consultantForm.default_revenue_rate || ""}
                  onChange={(e) =>
                    setConsultantForm((p) => ({
                      ...p,
                      default_revenue_rate: Number(e.target.value) || 0,
                    }))
                  }
                  placeholder="0.00"
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background tabular-nums"
                  aria-label="Default revenue rate w PLN na godzinę"
                />
              </div>
            </div>
            <div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={consultantForm.is_active}
                  onChange={(e) =>
                    setConsultantForm((p) => ({
                      ...p,
                      is_active: e.target.checked,
                    }))
                  }
                  className="rounded border-input"
                />
                Aktywny
              </label>
            </div>
          </div>
        </Modal>
      )}

      {/* Delete confirmations */}
      {deletingClientId !== null && (
        <DeleteConfirmModal
          title="Dezaktywować klienta?"
          message="Klient zostanie oznaczony jako nieaktywny (soft-delete). Placementy historyczne pozostają nienaruszone."
          onCancel={() => setDeletingClientId(null)}
          onConfirm={() => deleteClientMutation.mutate(deletingClientId)}
          isLoading={deleteClientMutation.isPending}
        />
      )}
      {deletingConsultantId !== null && (
        <DeleteConfirmModal
          title="Dezaktywować konsultanta?"
          message="Konsultant zostanie oznaczony jako nieaktywny (soft-delete). Dane historyczne pozostają."
          onCancel={() => setDeletingConsultantId(null)}
          onConfirm={() =>
            deleteConsultantMutation.mutate(deletingConsultantId)
          }
          isLoading={deleteConsultantMutation.isPending}
        />
      )}
    </div>
  );
}

function ClientsTable({
  clients,
  isLoading,
  onEdit,
  onToggleActive,
  onDelete,
}: {
  clients: DrAdminClientRow[];
  isLoading: boolean;
  onEdit: (c: DrAdminClientRow) => void;
  onToggleActive: (c: DrAdminClientRow) => void;
  onDelete: (id: number) => void;
}) {
  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        Ładowanie…
      </p>
    );
  }
  if (clients.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        Brak klientów w bazie. Kliknij &quot;Dodaj klienta&quot;.
      </p>
    );
  }
  return (
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
            <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
              Akcje
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {clients.map((c) => (
            <tr key={c.id} className={c.is_active ? "" : "opacity-60"}>
              <td className="px-3 py-2 text-sm font-medium">{c.name}</td>
              <td className="px-3 py-2 text-center">
                <button
                  onClick={() => onToggleActive(c)}
                  className="cursor-pointer"
                  title={c.is_active ? "Kliknij by dezaktywować" : "Kliknij by aktywować"}
                  aria-label={`Status klienta ${c.name}`}
                >
                  <Badge variant={c.is_active ? "success" : "neutral"} size="sm">
                    {c.is_active ? "aktywny" : "nieaktywny"}
                  </Badge>
                </button>
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-sm font-semibold">
                {c.placements_count}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  onClick={() => onEdit(c)}
                  className="p-1.5 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded mr-1"
                  title="Edytuj"
                  aria-label={`Edytuj klienta ${c.name}`}
                >
                  <Edit2 className="w-4 h-4" aria-hidden="true" />
                </button>
                {c.is_active && (
                  <button
                    onClick={() => onDelete(c.id)}
                    className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                    title="Dezaktywuj"
                    aria-label={`Dezaktywuj klienta ${c.name}`}
                  >
                    <Trash2 className="w-4 h-4" aria-hidden="true" />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConsultantsTable({
  consultants,
  isLoading,
  onEdit,
  onToggleActive,
  onDelete,
}: {
  consultants: DrAdminConsultantRow[];
  isLoading: boolean;
  onEdit: (k: DrAdminConsultantRow) => void;
  onToggleActive: (k: DrAdminConsultantRow) => void;
  onDelete: (id: number) => void;
}) {
  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        Ładowanie…
      </p>
    );
  }
  if (consultants.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        Brak konsultantów w bazie. Kliknij &quot;Dodaj konsultanta&quot;.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-muted/40">
          <tr>
            <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
              Nazwa
            </th>
            <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
              Cost rate
            </th>
            <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
              Revenue rate
            </th>
            <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
              Status
            </th>
            <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
              Akcje
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {consultants.map((k) => (
            <tr key={k.id} className={k.is_active ? "" : "opacity-60"}>
              <td className="px-3 py-2 text-sm font-medium">{k.name}</td>
              <td className="px-3 py-2 text-right tabular-nums text-sm">
                {formatPLN(k.default_cost_rate)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-sm">
                {formatPLN(k.default_revenue_rate)}
              </td>
              <td className="px-3 py-2 text-center">
                <button
                  onClick={() => onToggleActive(k)}
                  className="cursor-pointer"
                  title={k.is_active ? "Kliknij by dezaktywować" : "Kliknij by aktywować"}
                  aria-label={`Status konsultanta ${k.name}`}
                >
                  <Badge variant={k.is_active ? "success" : "neutral"} size="sm">
                    {k.is_active ? "aktywny" : "nieaktywny"}
                  </Badge>
                </button>
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  onClick={() => onEdit(k)}
                  className="p-1.5 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded mr-1"
                  title="Edytuj"
                  aria-label={`Edytuj konsultanta ${k.name}`}
                >
                  <Edit2 className="w-4 h-4" aria-hidden="true" />
                </button>
                {k.is_active && (
                  <button
                    onClick={() => onDelete(k.id)}
                    className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                    title="Dezaktywuj"
                    aria-label={`Dezaktywuj konsultanta ${k.name}`}
                  >
                    <Trash2 className="w-4 h-4" aria-hidden="true" />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Modal({
  title,
  icon,
  children,
  onClose,
  onSubmit,
  isSubmitting,
  submitLabel,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  onClose: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  submitLabel: string;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            {icon}
            {title}
          </h3>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Zamknij modal"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6">{children}</div>
        <div className="px-6 py-4 bg-muted/40 flex justify-end gap-3 rounded-b-xl">
          <button
            onClick={onClose}
            className="px-4 py-2 hover:bg-muted rounded-lg"
          >
            Anuluj
          </button>
          <button
            onClick={onSubmit}
            disabled={isSubmitting}
            className="px-4 py-2 bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2"
          >
            {isSubmitting ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function DeleteConfirmModal({
  title,
  message,
  onCancel,
  onConfirm,
  isLoading,
}: {
  title: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
  isLoading: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
        <div className="text-center">
          <div className="w-12 h-12 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
            <Trash2 className="w-6 h-6 text-red-600" aria-hidden="true" />
          </div>
          <h3 className="text-lg font-semibold mb-2">{title}</h3>
          <p className="text-sm text-muted-foreground mb-6">{message}</p>
          <div className="flex gap-3">
            <button
              onClick={onCancel}
              className="flex-1 px-4 py-2 bg-muted hover:bg-muted/70 rounded-lg"
              disabled={isLoading}
            >
              Anuluj
            </button>
            <button
              onClick={onConfirm}
              className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              disabled={isLoading}
            >
              {isLoading ? (
                <RefreshCw className="w-4 h-4 animate-spin inline" />
              ) : (
                "Dezaktywuj"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
