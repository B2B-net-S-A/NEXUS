"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, { contractsApi } from "@/lib/api";
import { DataTable } from "@/components/DataTable";
import { SavedSearchPicker } from "@/components/SavedSearchPicker";
import { RequireRole } from "@/components/RequireRole";
import { Plus, AlertCircle, X, Loader2 } from "lucide-react";
import { formatDate, formatCurrency } from "@/lib/utils";

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-gray-100 text-gray-600 dark:text-gray-300",
  active: "bg-green-100 text-green-700",
  ending: "bg-orange-100 text-orange-700",
  ended: "bg-red-100 text-red-600",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-end sm:items-center justify-center sm:p-4 overflow-y-auto">
      <div className="bg-white dark:bg-gray-800 rounded-2xl sm:rounded-2xl rounded-b-none sm:rounded-b-2xl shadow-2xl w-full sm:max-w-2xl sm:my-4">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700">
          <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FieldGroup({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      {children}
    </div>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
    />
  );
}

function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { children: React.ReactNode }) {
  return (
    <select
      {...props}
      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white dark:bg-gray-700 dark:text-gray-100"
    >
      {children}
    </select>
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ message, type, onClose }: { message: string; type: "success" | "error"; onClose: () => void }) {
  return (
    <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-[200] flex items-center gap-3 px-5 py-3.5 rounded-xl shadow-xl text-white text-sm font-medium ${type === "success" ? "bg-green-600" : "bg-red-600"}`}>
      {message}
      <button onClick={onClose} className="ml-1 opacity-70 hover:opacity-100">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ── New Contract Modal ─────────────────────────────────────────────────────────

interface ContractFormData {
  candidate_id: string;
  client_id: string;
  job_id: string;
  start_date: string;
  end_date: string;
  rate_candidate: string;
  rate_client: string;
  currency: string;
  contract_type: string;
  status: string;
}

const EMPTY_CONTRACT: ContractFormData = {
  candidate_id: "",
  client_id: "",
  job_id: "",
  start_date: "",
  end_date: "",
  rate_candidate: "",
  rate_client: "",
  currency: "PLN",
  contract_type: "b2b",
  status: "draft",
};

function NewContractModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: (msg: string) => void }) {
  const [form, setForm] = useState<ContractFormData>(EMPTY_CONTRACT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { data: candidatesData } = useQuery({
    queryKey: ["candidates-list-contract"],
    queryFn: () => api.get("/api/candidates", { params: { page_size: 100 } }).then(r => r.data),
  });
  const { data: clientsData } = useQuery({
    queryKey: ["clients-list-contract"],
    queryFn: () => api.get("/api/clients", { params: { page_size: 100 } }).then(r => r.data),
  });
  const { data: jobsData } = useQuery({
    queryKey: ["jobs-list-contract"],
    queryFn: () => api.get("/api/jobs", { params: { page_size: 100 } }).then(r => r.data),
  });

  const candidates = candidatesData?.items ?? [];
  const clients = clientsData?.items ?? [];
  const jobs = jobsData?.items ?? [];

  const set = (k: keyof ContractFormData, v: string) => setForm(f => ({ ...f, [k]: v }));

  // Auto-calculate margin
  const rateCandidate = parseFloat(form.rate_candidate) || 0;
  const rateClient = parseFloat(form.rate_client) || 0;
  const margin = rateClient - rateCandidate;
  const marginPct = rateClient > 0 ? ((margin / rateClient) * 100).toFixed(1) : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.candidate_id || !form.client_id || !form.start_date) {
      setError("Kandydat, klient i data rozpoczęcia są wymagane");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await contractsApi.create({
        candidate_id: Number(form.candidate_id),
        client_id: Number(form.client_id),
        job_id: form.job_id ? Number(form.job_id) : undefined,
        start_date: form.start_date,
        end_date: form.end_date || undefined,
        rate_candidate: form.rate_candidate ? Number(form.rate_candidate) : undefined,
        rate_client: form.rate_client ? Number(form.rate_client) : undefined,
        currency: form.currency,
        contract_type: form.contract_type,
        status: form.status,
      });
      onSuccess("Kontrakt utworzony pomyślnie");
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Błąd podczas zapisywania kontraktu");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="Nowy kontrakt" onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
        {error && (
          <div className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30 rounded-lg px-4 py-2">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <FieldGroup label="Kandydat" required>
            <Select value={form.candidate_id} onChange={e => set("candidate_id", e.target.value)}>
              <option value="">— wybierz kandydata —</option>
              {candidates.map((c: any) => (
                <option key={c.id} value={c.id}>{c.name} {c.lastname}</option>
              ))}
            </Select>
          </FieldGroup>

          <FieldGroup label="Klient" required>
            <Select value={form.client_id} onChange={e => set("client_id", e.target.value)}>
              <option value="">— wybierz klienta —</option>
              {clients.map((c: any) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </FieldGroup>

          <FieldGroup label="Oferta pracy">
            <Select value={form.job_id} onChange={e => set("job_id", e.target.value)}>
              <option value="">— opcjonalnie —</option>
              {jobs.map((j: any) => (
                <option key={j.id} value={j.id}>{j.title}</option>
              ))}
            </Select>
          </FieldGroup>

          <FieldGroup label="Typ kontraktu">
            <Select value={form.contract_type} onChange={e => set("contract_type", e.target.value)}>
              <option value="b2b">B2B</option>
              <option value="uop">UoP (Umowa o pracę)</option>
              <option value="uzlecenie">Zlecenie</option>
            </Select>
          </FieldGroup>

          <FieldGroup label="Data rozpoczęcia" required>
            <Input type="date" value={form.start_date} onChange={e => set("start_date", e.target.value)} />
          </FieldGroup>

          <FieldGroup label="Data zakończenia">
            <Input type="date" value={form.end_date} onChange={e => set("end_date", e.target.value)} />
          </FieldGroup>
        </div>

        {/* Rates section */}
        <div className="border border-gray-100 dark:border-gray-700 rounded-xl p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Stawki finansowe</h3>
          <div className="grid grid-cols-3 gap-3">
            <FieldGroup label="Stawka kandydata">
              <Input
                type="number"
                min="0"
                step="100"
                value={form.rate_candidate}
                onChange={e => set("rate_candidate", e.target.value)}
                placeholder="15000"
              />
            </FieldGroup>
            <FieldGroup label="Stawka klienta">
              <Input
                type="number"
                min="0"
                step="100"
                value={form.rate_client}
                onChange={e => set("rate_client", e.target.value)}
                placeholder="20000"
              />
            </FieldGroup>
            <FieldGroup label="Waluta">
              <Select value={form.currency} onChange={e => set("currency", e.target.value)}>
                <option value="PLN">PLN</option>
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="GBP">GBP</option>
              </Select>
            </FieldGroup>
          </div>

          {/* Margin auto-display */}
          {(rateCandidate > 0 || rateClient > 0) && (
            <div className={`flex items-center gap-4 text-sm rounded-lg px-4 py-2 ${margin >= 0 ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400" : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"}`}>
              <span className="font-medium">Marża:</span>
              <span className="font-bold">
                {margin.toLocaleString("pl-PL")} {form.currency}
              </span>
              {marginPct && (
                <span className="text-xs opacity-75">({marginPct}%)</span>
              )}
            </div>
          )}
        </div>

        <FieldGroup label="Status">
          <Select value={form.status} onChange={e => set("status", e.target.value)}>
            <option value="draft">Draft</option>
            <option value="active">Aktywny</option>
            <option value="ending">Kończący się</option>
            <option value="ended">Zakończony</option>
          </Select>
        </FieldGroup>

        <div className="flex justify-end gap-3 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
          >
            Anuluj
          </button>
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-5 py-2 rounded-lg text-sm font-medium transition-all"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            Utwórz kontrakt
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ContractsPage() {
  const [statusFilter, setStatusFilter] = useState("active");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showNewModal, setShowNewModal] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["contracts", statusFilter, page, pageSize],
    queryFn: () =>
      api.get("/api/contracts", { params: { status: statusFilter || undefined, page, page_size: pageSize } }).then((r) => r.data),
  });

  const { data: expiring } = useQuery({
    queryKey: ["contracts-expiring"],
    queryFn: () => api.get("/api/contracts/expiring").then((r) => r.data),
  });

  // Fetch candidates & clients for name resolution
  const { data: candidatesData } = useQuery({
    queryKey: ["candidates-names"],
    queryFn: () => api.get("/api/candidates", { params: { page_size: 100 } }).then(r => r.data),
    staleTime: 60_000,
  });
  const { data: clientsData } = useQuery({
    queryKey: ["clients-names"],
    queryFn: () => api.get("/api/clients", { params: { page_size: 100 } }).then(r => r.data),
    staleTime: 60_000,
  });
  const candidateMap = Object.fromEntries((candidatesData?.items ?? []).map((c: any) => [c.id, `${c.name} ${c.lastname}`]));
  const clientMap = Object.fromEntries((clientsData?.items ?? []).map((c: any) => [c.id, c.name]));

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
    queryClient.invalidateQueries({ queryKey: ["contracts"] });
  };

  const columns = [
    { key: "id", label: "ID", sortable: true },
    {
      key: "candidate_id",
      label: "Kandydat",
      render: (row: any) => (
        <a href={`/candidates/${row.candidate_id}`} className="text-blue-600 dark:text-blue-400 hover:underline">
          {candidateMap[row.candidate_id] || `#${row.candidate_id}`}
        </a>
      ),
      csvValue: (row: any) => candidateMap[row.candidate_id] || row.candidate_id,
    },
    {
      key: "client_id",
      label: "Klient",
      render: (row: any) => (
        <a href={`/clients/${row.client_id}`} className="text-blue-600 dark:text-blue-400 hover:underline">
          {clientMap[row.client_id] || `#${row.client_id}`}
        </a>
      ),
      csvValue: (row: any) => clientMap[row.client_id] || row.client_id,
    },
    { key: "start_date", label: "Od", sortable: true, render: (row: any) => formatDate(row.start_date), csvValue: (row: any) => row.start_date || "" },
    { key: "end_date", label: "Do", sortable: true, render: (row: any) => formatDate(row.end_date), csvValue: (row: any) => row.end_date || "" },
    { key: "contract_type", label: "Typ", sortable: true },
    {
      key: "rate_client",
      label: "Stawka klient",
      sortable: true,
      render: (row: any) => formatCurrency(row.rate_client, row.currency),
      csvValue: (row: any) => row.rate_client ?? "",
    },
    {
      key: "rate_candidate",
      label: "Stawka kandydat",
      render: (row: any) => formatCurrency(row.rate_candidate, row.currency),
      csvValue: (row: any) => row.rate_candidate ?? "",
    },
    {
      key: "margin",
      label: "Marża",
      sortable: true,
      render: (row: any) => (
        <span className={row.margin > 0 ? "text-green-600 font-medium" : "text-red-500"}>
          {formatCurrency(row.margin, row.currency)}
        </span>
      ),
      csvValue: (row: any) => row.margin ?? "",
    },
    {
      key: "status",
      label: "Status",
      sortable: true,
      render: (row: any) => (
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[row.status] || ""}`}>
          {row.status}
        </span>
      ),
      csvValue: (row: any) => row.status,
    },
  ];

  return (
    <div className="space-y-6">
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Kontrakty</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">{data?.total ?? 0} kontraktów</p>
        </div>
        {/* TacPlus guard — create contract wymaga admin/delivery_lead/tac. */}
        <RequireRole roles={["admin", "delivery_lead", "tac"]}>
          <button
            onClick={() => setShowNewModal(true)}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="w-4 h-4" />
            Nowy kontrakt
          </button>
        </RequireRole>
      </div>

      {expiring && expiring.length > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-3 flex items-center gap-2 text-sm text-orange-700">
          <AlertCircle className="w-4 h-4" />
          <strong>{expiring.length}</strong> kontraktów wygasa w ciągu 30 dni
        </div>
      )}

      <div className="flex gap-3 items-center">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value="">Wszystkie</option>
          <option value="draft">Draft</option>
          <option value="active">Aktywne</option>
          <option value="ending">Kończące się</option>
          <option value="ended">Zakończone</option>
        </select>
        <SavedSearchPicker
          entity="contract"
          currentFilters={{ status: statusFilter }}
          onApply={(f) => {
            if (typeof f.status === "string") setStatusFilter(f.status);
            setPage(1);
          }}
        />
      </div>

      <DataTable
        columns={columns}
        data={data?.items ?? []}
        loading={isLoading}
        page={page}
        pageSize={pageSize}
        total={data?.total ?? 0}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
        showCsvExport
        csvFilename="kontrakty.csv"
      />

      {showNewModal && (
        <NewContractModal
          onClose={() => setShowNewModal(false)}
          onSuccess={(msg) => showToast(msg, "success")}
        />
      )}
    </div>
  );
}
