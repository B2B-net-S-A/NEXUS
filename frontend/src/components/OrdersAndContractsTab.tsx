"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Calendar,
  Download,
  FilePlus2,
  Plus,
  TrendingUp,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import type {
  ClientOrderRead,
  ClientOrderStatus,
  ContractWithOrdersRead,
} from "@/lib/api/dlPortal";
import { ExtendOrderDialog } from "@/components/ExtendOrderDialog";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";

interface OrdersAndContractsTabProps {
  clientId: number;
}

type Filter = "all" | "active" | "expiring_30d" | "ended" | "drafts";

const STATUS_LABELS: Record<ClientOrderStatus, string> = {
  draft: "Draft",
  active: "Aktywne",
  paused: "Wstrzymane",
  completed: "Zakończone",
  cancelled: "Anulowane",
};

const STATUS_COLORS: Record<ClientOrderStatus, string> = {
  draft: "bg-yellow-100 text-yellow-800",
  active: "bg-green-100 text-green-800",
  paused: "bg-orange-100 text-orange-800",
  completed: "bg-zinc-200 text-zinc-700",
  cancelled: "bg-red-100 text-red-700",
};

export function OrdersAndContractsTab({ clientId }: OrdersAndContractsTabProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [extendingContract, setExtendingContract] = useState<ContractWithOrdersRead | null>(
    null,
  );
  const [newContractor, setNewContractor] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["dl-orders-grouped", clientId],
    queryFn: async () => {
      const res = await dlPortalApi.listContractorsWithOrders(clientId);
      return res.data;
    },
  });

  const filtered = useMemo<ContractWithOrdersRead[]>(() => {
    const contractors = data?.contractors ?? [];
    if (filter === "all") return contractors;
    if (filter === "active") {
      return contractors.filter(
        (c) => c.contract_status === "active" || c.contract_status === "ending",
      );
    }
    if (filter === "expiring_30d") {
      return contractors.filter(
        (c) =>
          c.days_to_latest_end !== null &&
          c.days_to_latest_end >= 0 &&
          c.days_to_latest_end <= 30,
      );
    }
    if (filter === "ended") {
      return contractors.filter(
        (c) => c.contract_status === "ended" || c.contract_status === "completed",
      );
    }
    if (filter === "drafts") {
      return contractors.filter(
        (c) =>
          c.contract_status === "draft" ||
          c.orders.some((o) => o.status === "draft"),
      );
    }
    return contractors;
  }, [data, filter]);

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["dl-orders-grouped", clientId] });
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground py-8 text-center">
        Ładowanie zamówień & kontraktów…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex flex-wrap gap-2 items-center">
          <FilterPill active={filter === "all"} onClick={() => setFilter("all")}>
            Wszyscy ({data?.total_contractors ?? 0})
          </FilterPill>
          <FilterPill active={filter === "active"} onClick={() => setFilter("active")}>
            Aktywni
          </FilterPill>
          <FilterPill
            active={filter === "expiring_30d"}
            onClick={() => setFilter("expiring_30d")}
            warn
          >
            ⚠️ Kończące się 30d
          </FilterPill>
          <FilterPill active={filter === "drafts"} onClick={() => setFilter("drafts")}>
            📝 Draft (do uzupełnienia)
          </FilterPill>
          <FilterPill active={filter === "ended"} onClick={() => setFilter("ended")}>
            Zakończeni
          </FilterPill>
        </div>
        <button
          onClick={() => setNewContractor(true)}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
        >
          <UserPlus className="w-4 h-4" />
          Nowy kontraktor / zamówienie
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="border border-dashed border-border rounded-lg p-12 text-center text-muted-foreground">
          <Users className="w-12 h-12 mx-auto mb-2 opacity-40" />
          {filter === "all"
            ? "Brak kontraktorów u tego klienta. Dodaj pierwszego kontraktora i zamówienie."
            : "Brak wyników dla wybranego filtra."}
        </div>
      ) : (
        <ul className="space-y-3">
          {filtered.map((contractor) => (
            <ContractorCard
              key={contractor.contract_id}
              contractor={contractor}
              clientId={clientId}
              onExtend={() => setExtendingContract(contractor)}
              onChange={refresh}
              onError={(msg) => showToast(msg, "error")}
              onSuccess={(msg) => showToast(msg, "success")}
            />
          ))}
        </ul>
      )}

      {extendingContract && (
        <ExtendOrderDialog
          clientId={clientId}
          contract={extendingContract}
          onClose={() => setExtendingContract(null)}
          onCreated={() => {
            setExtendingContract(null);
            refresh();
          }}
        />
      )}

      {newContractor && (
        <NewContractorOrderDialog
          clientId={clientId}
          onClose={() => setNewContractor(false)}
          onCreated={() => {
            setNewContractor(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

interface FilterPillProps {
  active: boolean;
  warn?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function FilterPill({ active, warn, onClick, children }: FilterPillProps) {
  return (
    <button
      onClick={onClick}
      className={
        "px-3 py-1.5 text-sm rounded-full border transition-colors " +
        (active
          ? warn
            ? "bg-orange-100 border-orange-300 text-orange-800"
            : "bg-violet-100 border-violet-300 text-violet-800"
          : "bg-card border-border text-muted-foreground hover:text-foreground")
      }
    >
      {children}
    </button>
  );
}

interface ContractorCardProps {
  contractor: ContractWithOrdersRead;
  clientId: number;
  onExtend: () => void;
  onChange: () => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
}

function ContractorCard({
  contractor,
  clientId,
  onExtend,
  onChange,
  onError,
  onSuccess,
}: ContractorCardProps) {
  const expiringWarn =
    contractor.days_to_latest_end !== null &&
    contractor.days_to_latest_end >= 0 &&
    contractor.days_to_latest_end <= 30;

  return (
    <li className="border border-border rounded-lg bg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-base">
              👤 {contractor.candidate_name}
            </h3>
            <span
              className={
                "text-xs px-2 py-0.5 rounded " +
                (contractor.contract_status === "active"
                  ? "bg-green-100 text-green-800"
                  : contractor.contract_status === "draft"
                  ? "bg-yellow-100 text-yellow-800"
                  : "bg-zinc-200 text-zinc-700")
              }
            >
              Contract #{contractor.contract_id} · {contractor.contract_status}
            </span>
            {expiringWarn && (
              <span className="text-xs text-orange-700 bg-orange-100 px-2 py-0.5 rounded flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                kończy się za {contractor.days_to_latest_end} dni
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
            {contractor.rate_candidate !== null && (
              <span>my płacimy {fmtMoney(contractor.rate_candidate)}/mc</span>
            )}
            {contractor.contract_start_date && (
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                od {fmtDate(contractor.contract_start_date)}
              </span>
            )}
            {contractor.initial_job_title && (
              <span>z rekrutacji: {contractor.initial_job_title}</span>
            )}
          </div>
        </div>
        <button
          onClick={onExtend}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 text-white rounded hover:bg-violet-700"
        >
          <Plus className="w-4 h-4" />
          Dodaj przedłużenie
        </button>
      </div>

      {contractor.orders.length === 0 ? (
        <div className="text-xs text-muted-foreground italic pl-2">
          Brak zamówień — Contract bez aktualnego PDF od klienta.
        </div>
      ) : (
        <div className="pl-2 border-l-2 border-violet-200 space-y-2">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Historia zamówień ({contractor.orders.length})
          </div>
          {contractor.orders.map((order) => (
            <OrderRow
              key={order.id}
              order={order}
              clientId={clientId}
              onError={onError}
              onSuccess={onSuccess}
              onDeleted={onChange}
            />
          ))}
        </div>
      )}
    </li>
  );
}

interface OrderRowProps {
  order: ClientOrderRead;
  clientId: number;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
  onDeleted: () => void;
}

function OrderRow({
  order,
  clientId,
  onError,
  onSuccess,
  onDeleted,
}: OrderRowProps) {
  const deleteMutation = useMutation({
    mutationFn: () => dlPortalApi.deleteOrder(clientId, order.id),
    onSuccess: () => {
      onSuccess("Zamówienie usunięte / anulowane");
      onDeleted();
    },
    onError: (err: unknown) => {
      onError(err instanceof Error ? err.message : "Błąd usuwania");
    },
  });

  const expiringWarn =
    order.days_to_end !== null && order.days_to_end >= 0 && order.days_to_end <= 30;

  // The file endpoint is Bearer-guarded — a raw <a href> sends no Authorization
  // header. Fetch the bytes with the token and download the same-origin blob.
  const handleDownloadPo = async () => {
    try {
      await downloadAuthenticatedFile(
        `/api/clients/${clientId}/orders/${order.id}/file`,
        order.filename ?? `zamowienie-${order.id}.pdf`,
      );
    } catch {
      onError("Nie udało się pobrać pliku zamówienia.");
    }
  };

  return (
    <div className="flex items-start justify-between gap-3 text-sm border border-border rounded p-2 bg-background">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLORS[order.status]}`}>
            {STATUS_LABELS[order.status]}
          </span>
          <span className="font-medium">{order.title}</span>
          {expiringWarn && (
            <span className="text-xs text-orange-700 bg-orange-100 px-2 py-0.5 rounded">
              ⚠️ kończy się za {order.days_to_end} dni
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground flex-wrap">
          {(order.start_date || order.end_date) && (
            <span className="flex items-center gap-1">
              <Calendar className="w-3 h-3" />
              {fmtDate(order.start_date)} → {fmtDate(order.end_date) || "open"}
            </span>
          )}
          {order.rate_client !== null && (
            <span>klient {fmtMoney(order.rate_client)}/mc</span>
          )}
          {order.monthly_margin !== null && (
            <span className="flex items-center gap-1 text-green-700">
              <TrendingUp className="w-3 h-3" />
              marża {fmtMoney(order.monthly_margin)}/mc
            </span>
          )}
          {order.job_title && (
            <span className="text-violet-600">Job: {order.job_title}</span>
          )}
          {order.has_file && (
            <button
              type="button"
              onClick={handleDownloadPo}
              className="flex items-center gap-1 hover:text-violet-600"
            >
              <Download className="w-3 h-3" />
              PDF
            </button>
          )}
        </div>
      </div>
      <button
        onClick={() => {
          if (confirm(`Anulować zamówienie "${order.title}"?`)) deleteMutation.mutate();
        }}
        className="text-muted-foreground hover:text-destructive p-1"
        title="Usuń / anuluj"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function fmtDate(d: string | null): string | null {
  if (!d) return null;
  return d.slice(0, 10);
}

function fmtMoney(v: number | string | null): string {
  if (v === null || v === undefined) return "—";
  const num = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(num)) return "—";
  return num.toLocaleString("pl-PL");
}

export { FilePlus2 };
