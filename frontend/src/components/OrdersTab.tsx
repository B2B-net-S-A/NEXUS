"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Plus,
  Trash2,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import type {
  ClientOrderRead,
  ClientOrderStatus,
  FrameworkContractRead,
  OrderContractLinkRead,
} from "@/lib/api/dlPortal";

interface OrdersTabProps {
  clientId: number;
}

const ORDER_STATUS_LABELS: Record<ClientOrderStatus, string> = {
  draft: "Szkic",
  active: "Aktywne",
  paused: "Wstrzymane",
  completed: "Zakończone",
  cancelled: "Anulowane",
};

const ORDER_STATUS_COLORS: Record<ClientOrderStatus, string> = {
  draft: "bg-muted text-muted-foreground",
  active: "bg-green-100 text-green-800",
  paused: "bg-yellow-100 text-yellow-800",
  completed: "bg-zinc-200 text-zinc-700",
  cancelled: "bg-red-100 text-red-700",
};

export function OrdersTab({ clientId }: OrdersTabProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["orders", clientId],
    queryFn: async () => {
      const res = await dlPortalApi.listOrders(clientId);
      return res.data;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (orderId: number) => dlPortalApi.deleteOrder(clientId, orderId),
    onSuccess: () => {
      showToast("Zamówienie anulowane / usunięte", "success");
      queryClient.invalidateQueries({ queryKey: ["orders", clientId] });
    },
  });

  if (isLoading) return <div className="text-muted-foreground">Ładowanie zamówień…</div>;

  const orders = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Zamówienia (Statement of Work)</h3>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
        >
          <Plus className="w-4 h-4" />
          Nowe zamówienie
        </button>
      </div>

      {orders.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-8 text-center text-muted-foreground">
          Brak zamówień. Stwórz pierwsze zlecenie pod istniejącą umową ramową.
        </div>
      ) : (
        <ul className="space-y-2">
          {orders.map((o) => (
            <OrderRow
              key={o.id}
              order={o}
              onOpen={() => setSelectedOrderId(o.id)}
              onDelete={() => {
                if (confirm(`Anulować zamówienie "${o.title}"?`)) {
                  deleteMutation.mutate(o.id);
                }
              }}
            />
          ))}
        </ul>
      )}

      {showCreate && (
        <CreateOrderDialog
          clientId={clientId}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            queryClient.invalidateQueries({ queryKey: ["orders", clientId] });
          }}
        />
      )}

      {selectedOrderId !== null && (
        <OrderDetailDrawer
          clientId={clientId}
          orderId={selectedOrderId}
          onClose={() => setSelectedOrderId(null)}
        />
      )}
    </div>
  );
}

interface OrderRowProps {
  order: ClientOrderRead;
  onOpen: () => void;
  onDelete: () => void;
}

function OrderRow({ order, onOpen, onDelete }: OrderRowProps) {
  const expiringWarn =
    order.days_to_end !== null && order.days_to_end >= 0 && order.days_to_end <= 30;

  return (
    <li className="border border-border rounded-lg bg-card hover:bg-accent/30 cursor-pointer p-4" onClick={onOpen}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{order.title}</span>
            <span className={`text-xs px-2 py-0.5 rounded ${ORDER_STATUS_COLORS[order.status]}`}>
              {ORDER_STATUS_LABELS[order.status]}
            </span>
            {expiringWarn && (
              <span className="text-xs text-orange-700 bg-orange-100 px-2 py-0.5 rounded flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                kończy się za {order.days_to_end} dni
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 mt-1 text-xs text-muted-foreground flex-wrap">
            {order.start_date && (
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                {order.start_date}{order.end_date ? ` – ${order.end_date}` : ""}
              </span>
            )}
            {order.total_value !== null && (
              <span>
                {order.total_value} {order.currency}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Users className="w-3 h-3" />
              {order.filled_positions}/{order.positions_count ?? "?"} pozycji
            </span>
            {order.monthly_margin_total !== null && (
              <span className="flex items-center gap-1 text-green-700">
                <TrendingUp className="w-3 h-3" />
                marża {order.monthly_margin_total}/mc
                {order.monthly_margin_pct !== null && ` (${order.monthly_margin_pct}%)`}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="text-muted-foreground hover:text-destructive p-1"
          title="Anuluj"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </li>
  );
}

interface CreateOrderDialogProps {
  clientId: number;
  onClose: () => void;
  onCreated: () => void;
}

function CreateOrderDialog({ clientId, onClose, onCreated }: CreateOrderDialogProps) {
  const { showToast } = useToast();
  const [frameworkContractId, setFrameworkContractId] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [orderStatus, setOrderStatus] = useState<ClientOrderStatus>("draft");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [totalValue, setTotalValue] = useState("");
  const [currency, setCurrency] = useState("PLN");
  const [positionsCount, setPositionsCount] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { data: contractsData } = useQuery({
    queryKey: ["framework-contracts-active", clientId],
    queryFn: async () => {
      const res = await dlPortalApi.listFrameworkContracts(clientId);
      return res.data.items.filter((fc: FrameworkContractRead) =>
        ["active", "pending_signature", "draft"].includes(fc.status),
      );
    },
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !frameworkContractId) return;
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("framework_contract_id", String(frameworkContractId));
      fd.append("title", title);
      if (description) fd.append("description", description);
      fd.append("order_status", orderStatus);
      if (startDate) fd.append("start_date", startDate);
      if (endDate) fd.append("end_date", endDate);
      if (totalValue) fd.append("total_value", totalValue);
      if (currency) fd.append("currency", currency);
      if (positionsCount) fd.append("positions_count", positionsCount);
      if (file) fd.append("file", file);
      await dlPortalApi.createOrder(clientId, fd);
      showToast("Zamówienie dodane", "success");
      onCreated();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Błąd zapisu", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <form
        onSubmit={handleSubmit}
        className="bg-card rounded-lg shadow-xl max-w-lg w-full p-6 space-y-3 max-h-[90vh] overflow-auto"
      >
        <h3 className="text-lg font-semibold">Nowe zamówienie</h3>
        <label>
          <span className="text-sm">Umowa ramowa</span>
          <select
            value={frameworkContractId}
            onChange={(e) =>
              setFrameworkContractId(e.target.value ? Number(e.target.value) : "")
            }
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
          >
            <option value="">— wybierz —</option>
            {(contractsData ?? []).map((fc) => (
              <option key={fc.id} value={fc.id}>
                {fc.name} ({fc.status})
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="text-sm">Tytuł</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            placeholder="np. Java devs Q3 2026"
          />
        </label>
        <label>
          <span className="text-sm">Opis</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="mt-1 w-full px-3 py-2 border border-border rounded bg-background text-sm"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Status</span>
            <select
              value={orderStatus}
              onChange={(e) => setOrderStatus(e.target.value as ClientOrderStatus)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            >
              <option value="draft">Szkic</option>
              <option value="active">Aktywne</option>
              <option value="paused">Wstrzymane</option>
            </select>
          </label>
          <label>
            <span className="text-sm">Liczba pozycji</span>
            <input
              type="number"
              min="0"
              value={positionsCount}
              onChange={(e) => setPositionsCount(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Start</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Koniec</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <span className="text-sm">Wartość total</span>
            <input
              type="number"
              step="0.01"
              min="0"
              value={totalValue}
              onChange={(e) => setTotalValue(e.target.value)}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
          <label>
            <span className="text-sm">Waluta</span>
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              maxLength={3}
              className="mt-1 w-full px-3 py-2 border border-border rounded bg-background"
            />
          </label>
        </div>
        <label>
          <span className="text-sm">PO PDF (opcjonalny)</span>
          <input
            type="file"
            accept=".pdf,.docx,.doc"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 w-full text-sm"
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="px-3 py-2 text-sm border border-border rounded">
            Anuluj
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : "Zapisz"}
          </button>
        </div>
      </form>
    </div>
  );
}

interface OrderDetailDrawerProps {
  clientId: number;
  orderId: number;
  onClose: () => void;
}

function OrderDetailDrawer({ clientId, orderId, onClose }: OrderDetailDrawerProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [linkInput, setLinkInput] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["order", clientId, orderId],
    queryFn: async () => {
      const res = await dlPortalApi.getOrder(clientId, orderId);
      return res.data;
    },
  });

  const linkMutation = useMutation({
    mutationFn: (contractId: number) =>
      dlPortalApi.linkContract(clientId, orderId, contractId),
    onSuccess: () => {
      showToast("Kandydat dodany do zamówienia", "success");
      setLinkInput("");
      queryClient.invalidateQueries({ queryKey: ["order", clientId, orderId] });
      queryClient.invalidateQueries({ queryKey: ["orders", clientId] });
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : "Błąd linkowania";
      showToast(msg, "error");
    },
  });

  const unlinkMutation = useMutation({
    mutationFn: (contractId: number) =>
      dlPortalApi.unlinkContract(clientId, orderId, contractId),
    onSuccess: () => {
      showToast("Kandydat odłączony", "success");
      queryClient.invalidateQueries({ queryKey: ["order", clientId, orderId] });
      queryClient.invalidateQueries({ queryKey: ["orders", clientId] });
    },
  });

  return (
    <div className="fixed inset-0 bg-black/50 flex justify-end z-50">
      <div className="bg-card w-full max-w-xl h-full overflow-y-auto p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">Szczegóły zamówienia</h3>
          <button onClick={onClose} className="p-1">
            <X className="w-5 h-5" />
          </button>
        </div>
        {isLoading || !data ? (
          <p className="text-muted-foreground">Ładowanie…</p>
        ) : (
          <>
            <div>
              <h4 className="font-medium">{data.title}</h4>
              {data.description && (
                <p className="text-sm text-muted-foreground mt-1">{data.description}</p>
              )}
              <div className="text-xs text-muted-foreground mt-2 space-y-0.5">
                <div>Status: {ORDER_STATUS_LABELS[data.status]}</div>
                {data.start_date && (
                  <div>
                    Daty: {data.start_date}
                    {data.end_date ? ` – ${data.end_date}` : " – open-ended"}
                  </div>
                )}
                {data.total_value !== null && (
                  <div>
                    Wartość: {data.total_value} {data.currency}
                  </div>
                )}
                {data.monthly_margin_total !== null && (
                  <div>
                    Marża miesięczna (auto): {data.monthly_margin_total}
                    {data.monthly_margin_pct !== null && ` (${data.monthly_margin_pct}%)`}
                  </div>
                )}
              </div>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-2">
                Linkowane kontrakty kandydatów ({data.contracts.length})
              </h4>
              <ul className="space-y-1.5">
                {data.contracts.map((link: OrderContractLinkRead) => (
                  <li
                    key={link.id}
                    className="flex items-center justify-between text-sm border border-border rounded p-2"
                  >
                    <div>
                      <div className="font-medium">
                        {link.candidate_name ?? `Contract #${link.contract_id}`}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {link.contract_status} · marża/mc {link.monthly_margin ?? "—"}
                      </div>
                    </div>
                    <button
                      onClick={() => unlinkMutation.mutate(link.contract_id)}
                      className="text-muted-foreground hover:text-destructive p-1"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex gap-2">
                <input
                  type="number"
                  placeholder="Contract ID"
                  value={linkInput}
                  onChange={(e) => setLinkInput(e.target.value)}
                  className="flex-1 px-3 py-1.5 border border-border rounded bg-background text-sm"
                />
                <button
                  onClick={() => {
                    const cid = Number(linkInput);
                    if (cid > 0) linkMutation.mutate(cid);
                  }}
                  disabled={!linkInput || linkMutation.isPending}
                  className="px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
                >
                  Połącz
                </button>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Wpisz ID kontraktu kandydackiego (z zakładki Kontrakty kandydata).
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
