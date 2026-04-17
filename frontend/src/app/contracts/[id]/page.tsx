"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { contractsApi } from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";
import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import { ContractOnboardingTab } from "@/components/ContractOnboardingTab";
import { ContractDocument, summariseComplianceRisk } from "@/components/ContractDocumentsTab";
import { formatDate, formatCurrency } from "@/lib/utils";
import {
  ArrowLeft,
  Pencil,
  Trash2,
  Save,
  X,
  Activity as ActivityIcon,
  History,
  FileText,
  FileEdit,
  AlertCircle,
  Loader2,
  User,
  Building2,
  Briefcase,
  Calendar,
  Banknote,
  TrendingUp,
  Printer,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ContractDetail {
  id: number;
  candidate_id: number;
  client_id: number;
  job_id: number | null;
  candidate_name: string | null;
  client_name: string | null;
  job_title: string | null;
  start_date: string;
  end_date: string | null;
  rate_candidate: number | null;
  rate_client: number | null;
  currency: string;
  rate_unit: "hourly" | "daily" | "monthly";
  billing_hours_per_month: number;
  margin: number | null;
  contract_type: "b2b" | "uop" | "uzlecenie";
  status: "draft" | "active" | "ending" | "ended";
  documents: unknown;
  client_pm_name: string | null;
  client_pm_email: string | null;
  work_mode: "remote" | "hybrid" | "onsite" | null;
  office_location: string | null;
  team_name: string | null;
  project_name: string | null;
  handover_notes: string | null;
  created_at: string;
  updated_at: string;
}

interface ActivityEntry {
  id: number;
  action: string;
  details: Record<string, unknown> | null;
  user_id: number | null;
  user_name: string | null;
  created_at: string;
}

interface RateHistoryEntry {
  id: number;
  rate: number;
  currency: string;
  contract_type: string;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700 border border-gray-200 dark:bg-gray-700 dark:text-gray-200",
  active: "bg-emerald-100 text-emerald-700 border border-emerald-200",
  ending: "bg-orange-100 text-orange-700 border border-orange-200",
  ended: "bg-red-100 text-red-700 border border-red-200",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
};

const TYPE_LABELS: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  uzlecenie: "Zlecenie",
};

const RATE_UNIT_SUFFIX: Record<string, string> = {
  monthly: "/mies.",
  daily: "/dz.",
  hourly: "/h",
};

const RATE_UNIT_LABELS: Record<string, string> = {
  monthly: "Miesięcznie",
  daily: "Dziennie",
  hourly: "Godzinowo",
};

const WORK_MODE_LABELS: Record<string, string> = {
  remote: "Zdalnie",
  hybrid: "Hybrydowo",
  onsite: "Stacjonarnie",
};

interface ContractTemplate {
  id: number;
  name: string;
  contract_type: string;
}

function GenerateDocumentButton({
  contractId,
  contractType,
}: {
  contractId: number;
  contractType: string;
}) {
  const { data: templates } = useQuery<ContractTemplate[]>({
    queryKey: ["contract-templates-by-type", contractType],
    queryFn: () =>
      api
        .get("/api/contract-templates", { params: { contract_type: contractType } })
        .then((r) => r.data),
  });

  if (!templates || templates.length === 0) return null;

  const openRendered = async (templateId: number) => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const url = `${base}/api/contract-templates/${templateId}/render?contract_id=${contractId}`;
    try {
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) {
        alert(`Błąd renderowania: ${resp.status}`);
        return;
      }
      const html = await resp.text();
      const win = window.open("", "_blank");
      if (!win) {
        alert("Popupy są blokowane — pozwól na okno i spróbuj ponownie.");
        return;
      }
      win.document.write(html);
      win.document.close();
    } catch (err) {
      alert(`Błąd: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <div className="relative">
      <select
        onChange={(e) => {
          const id = Number(e.target.value);
          if (id) openRendered(id);
          e.target.value = "";
        }}
        className="flex items-center gap-2 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 px-3 py-2 rounded-lg text-sm font-medium"
      >
        <option value="">Generuj z szablonu…</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </div>
  );
}

function monthlyMultiplier(rate_unit: string, billing_hours_per_month: number): number {
  if (rate_unit === "daily") return 22;
  if (rate_unit === "hourly") return billing_hours_per_month || 160;
  return 1;
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

type TabKey = "details" | "documents" | "amendments" | "onboarding" | "rateHistory" | "timeline";

interface Tab {
  key: TabKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: Tab[] = [
  { key: "details", label: "Szczegóły", icon: FileEdit },
  { key: "documents", label: "Dokumenty", icon: FileText },
  { key: "amendments", label: "Aneksy", icon: FileEdit },
  { key: "onboarding", label: "Onboarding", icon: FileText },
  { key: "rateHistory", label: "Historia stawek", icon: History },
  { key: "timeline", label: "Timeline", icon: ActivityIcon },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[status] ?? ""}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function InfoRow({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-2">
      <Icon className="w-4 h-4 text-gray-400 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
        <div className="text-sm text-gray-900 dark:text-gray-100">{children}</div>
      </div>
    </div>
  );
}

// ── Edit form ─────────────────────────────────────────────────────────────────

interface EditForm {
  start_date: string;
  end_date: string;
  rate_candidate: string;
  rate_client: string;
  currency: string;
  rate_unit: string;
  billing_hours_per_month: string;
  contract_type: string;
  status: string;
  client_pm_name: string;
  client_pm_email: string;
  work_mode: string;
  office_location: string;
  team_name: string;
  project_name: string;
  handover_notes: string;
}

function contractToForm(c: ContractDetail): EditForm {
  return {
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? "",
    rate_candidate: c.rate_candidate?.toString() ?? "",
    rate_client: c.rate_client?.toString() ?? "",
    currency: c.currency,
    rate_unit: c.rate_unit ?? "monthly",
    billing_hours_per_month: (c.billing_hours_per_month ?? 160).toString(),
    contract_type: c.contract_type,
    status: c.status,
    client_pm_name: c.client_pm_name ?? "",
    client_pm_email: c.client_pm_email ?? "",
    work_mode: c.work_mode ?? "",
    office_location: c.office_location ?? "",
    team_name: c.team_name ?? "",
    project_name: c.project_name ?? "",
    handover_notes: c.handover_notes ?? "",
  };
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ContractDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const id = Number(params.id);

  const [activeTab, setActiveTab] = useState<TabKey>("details");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<EditForm | null>(null);
  const [error, setError] = useState("");

  // Fetch contract
  const { data: contract, isLoading, isError } = useQuery<ContractDetail>({
    queryKey: ["contract", id],
    queryFn: () => contractsApi.get(id).then((r) => r.data),
    enabled: !Number.isNaN(id),
  });

  // Fetch activity timeline (lazy)
  const { data: activities } = useQuery<ActivityEntry[]>({
    queryKey: ["contract-activities", id],
    queryFn: () => contractsApi.activities(id).then((r) => r.data),
    enabled: !Number.isNaN(id) && activeTab === "timeline",
  });

  // Fetch rate history (lazy)
  const { data: rateHistory } = useQuery<RateHistoryEntry[]>({
    queryKey: ["contract-rate-history", id],
    queryFn: () => contractsApi.rateHistory(id).then((r) => r.data),
    enabled: !Number.isNaN(id) && activeTab === "rateHistory",
  });

  // Compliance risk — eagerly fetch documents so the badge works on all tabs.
  const { data: contractDocs } = useQuery<ContractDocument[]>({
    queryKey: ["contract-documents", id],
    queryFn: () => contractsApi.documents(id).then((r) => r.data),
    enabled: !Number.isNaN(id),
  });
  const complianceRisk = summariseComplianceRisk(contractDocs);

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => contractsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract", id] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", id] });
      setEditing(false);
      setError("");
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error ? err.message : "Błąd podczas zapisu kontraktu";
      setError(message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => contractsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      router.push("/contracts");
    },
  });

  const handleStartEdit = () => {
    if (!contract) return;
    setForm(contractToForm(contract));
    setEditing(true);
    setError("");
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setForm(null);
    setError("");
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const payload: Record<string, unknown> = {
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      rate_candidate: form.rate_candidate ? Number(form.rate_candidate) : null,
      rate_client: form.rate_client ? Number(form.rate_client) : null,
      currency: form.currency,
      rate_unit: form.rate_unit,
      billing_hours_per_month: Number(form.billing_hours_per_month) || 160,
      contract_type: form.contract_type,
      status: form.status,
      client_pm_name: form.client_pm_name || null,
      client_pm_email: form.client_pm_email || null,
      work_mode: form.work_mode || null,
      office_location: form.office_location || null,
      team_name: form.team_name || null,
      project_name: form.project_name || null,
      handover_notes: form.handover_notes || null,
    };
    updateMutation.mutate(payload);
  };

  const handleDelete = () => {
    if (window.confirm("Czy na pewno usunąć ten kontrakt? Operacja jest nieodwracalna.")) {
      deleteMutation.mutate();
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  if (Number.isNaN(id)) {
    return (
      <div className="p-6">
        <p className="text-red-600">Nieprawidłowe ID kontraktu.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center text-gray-500">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> Ładowanie kontraktu…
      </div>
    );
  }

  if (isError || !contract) {
    return (
      <div className="p-6">
        <Link
          href="/contracts"
          className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-300"
        >
          <ArrowLeft className="w-4 h-4" /> Wróć do listy
        </Link>
        <p className="mt-4 text-red-600">Nie udało się wczytać kontraktu.</p>
      </div>
    );
  }

  const marginPct =
    contract.rate_client && contract.rate_client > 0 && contract.margin !== null
      ? ((contract.margin / contract.rate_client) * 100).toFixed(1)
      : null;

  const unitSuffix = RATE_UNIT_SUFFIX[contract.rate_unit] ?? "";
  const monthlyMult = monthlyMultiplier(contract.rate_unit, contract.billing_hours_per_month);
  const monthlyMargin = contract.margin !== null ? contract.margin * monthlyMult : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <Link
            href="/contracts"
            className="inline-flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Kontrakty
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-3 flex-wrap">
            Kontrakt #{contract.id}
            <StatusBadge status={contract.status} />
            {complianceRisk.risk === "overdue" && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 border border-red-200">
                Compliance: dokument wygasł
              </span>
            )}
            {complianceRisk.risk === "soon" && (
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-700 border border-orange-200">
                Compliance: {complianceRisk.docType} wygasa {formatDate(complianceRisk.soonestDate)}
              </span>
            )}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {contract.candidate_name ? (
              <Link
                className="text-blue-600 hover:underline dark:text-blue-400"
                href={`/candidates/${contract.candidate_id}`}
              >
                {contract.candidate_name}
              </Link>
            ) : (
              `#${contract.candidate_id}`
            )}
            {" · "}
            {contract.client_name ? (
              <Link
                className="text-blue-600 hover:underline dark:text-blue-400"
                href={`/clients/${contract.client_id}`}
              >
                {contract.client_name}
              </Link>
            ) : (
              `Klient #${contract.client_id}`
            )}
            {contract.job_title ? ` · ${contract.job_title}` : ""}
          </p>
        </div>

        <RequireRole roles={["admin", "delivery_lead", "tac"]}>
          <div className="flex gap-2 flex-wrap">
            <GenerateDocumentButton contractId={id} contractType={contract.contract_type} />
            {!editing && (
              <button
                onClick={handleStartEdit}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium"
              >
                <Pencil className="w-4 h-4" /> Edytuj
              </button>
            )}
            <RequireRole roles={["admin", "delivery_lead"]}>
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-2 bg-red-600 hover:bg-red-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}{" "}
                Usuń
              </button>
            </RequireRole>
          </div>
        </RequireRole>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700 flex gap-1 overflow-x-auto">
        {TABS.map((t) => {
          const active = t.key === activeTab;
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition-colors ${
                active
                  ? "border-blue-600 text-blue-600 font-medium"
                  : "border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-100"
              }`}
            >
              <Icon className="w-4 h-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab: Szczegóły */}
      {activeTab === "details" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            {/* View mode */}
            {!editing && (
              <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 space-y-1">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
                  Informacje o kontrakcie
                </h2>
                <InfoRow icon={User} label="Kandydat">
                  {contract.candidate_name ? (
                    <Link
                      href={`/candidates/${contract.candidate_id}`}
                      className="text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {contract.candidate_name}
                    </Link>
                  ) : (
                    `#${contract.candidate_id}`
                  )}
                </InfoRow>
                <InfoRow icon={Building2} label="Klient">
                  {contract.client_name ? (
                    <Link
                      href={`/clients/${contract.client_id}`}
                      className="text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {contract.client_name}
                    </Link>
                  ) : (
                    `#${contract.client_id}`
                  )}
                </InfoRow>
                <InfoRow icon={Briefcase} label="Oferta pracy">
                  {contract.job_title ? (
                    <Link
                      href={`/jobs/${contract.job_id}`}
                      className="text-blue-600 hover:underline dark:text-blue-400"
                    >
                      {contract.job_title}
                    </Link>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </InfoRow>
                <InfoRow icon={Calendar} label="Okres">
                  {formatDate(contract.start_date)} –{" "}
                  {contract.end_date ? formatDate(contract.end_date) : (
                    <span className="italic text-gray-500">bezterminowo</span>
                  )}
                </InfoRow>
                <InfoRow icon={FileEdit} label="Typ kontraktu">
                  {TYPE_LABELS[contract.contract_type] ?? contract.contract_type}
                </InfoRow>
              </div>
            )}

            {/* Assignment context */}
            {!editing && (contract.client_pm_name || contract.work_mode || contract.project_name || contract.team_name || contract.office_location) && (
              <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 space-y-1">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
                  Osadzenie u klienta
                </h2>
                {contract.client_pm_name && (
                  <InfoRow icon={User} label="PM po stronie klienta">
                    {contract.client_pm_name}
                    {contract.client_pm_email && (
                      <span className="block text-xs text-gray-500 dark:text-gray-400">
                        {contract.client_pm_email}
                      </span>
                    )}
                  </InfoRow>
                )}
                {contract.work_mode && (
                  <InfoRow icon={Building2} label="Tryb pracy">
                    {WORK_MODE_LABELS[contract.work_mode] ?? contract.work_mode}
                    {contract.office_location && ` · ${contract.office_location}`}
                  </InfoRow>
                )}
                {contract.project_name && (
                  <InfoRow icon={Briefcase} label="Projekt">
                    {contract.project_name}
                  </InfoRow>
                )}
                {contract.team_name && (
                  <InfoRow icon={Briefcase} label="Zespół">
                    {contract.team_name}
                  </InfoRow>
                )}
              </div>
            )}

            {/* Handover notes (C6) — wewnętrzne */}
            {!editing && contract.handover_notes && (
              <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-900 rounded-2xl p-5">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200 mb-2">
                  Notatki wewnętrzne (handover)
                </h2>
                <p className="text-sm text-amber-900 dark:text-amber-100 whitespace-pre-line">
                  {contract.handover_notes}
                </p>
              </div>
            )}

            {/* Edit mode */}
            {editing && form && (
              <form
                onSubmit={handleSave}
                className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 space-y-4"
              >
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Edycja kontraktu
                </h2>

                {error && (
                  <div className="text-sm text-red-700 bg-red-50 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-4 py-2 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" /> {error}
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Data rozpoczęcia
                    </label>
                    <input
                      type="date"
                      value={form.start_date}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, start_date: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Data zakończenia
                    </label>
                    <input
                      type="date"
                      value={form.end_date}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, end_date: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Typ kontraktu
                    </label>
                    <select
                      value={form.contract_type}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, contract_type: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    >
                      <option value="b2b">B2B</option>
                      <option value="uop">UoP</option>
                      <option value="uzlecenie">Zlecenie</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Status
                    </label>
                    <select
                      value={form.status}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, status: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    >
                      <option value="draft">Draft</option>
                      <option value="active">Aktywny</option>
                      <option value="ending">Kończący się</option>
                      <option value="ended">Zakończony</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Stawka kandydata
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="100"
                      value={form.rate_candidate}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, rate_candidate: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Stawka klienta
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="100"
                      value={form.rate_client}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, rate_client: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Waluta
                    </label>
                    <select
                      value={form.currency}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, currency: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    >
                      <option value="PLN">PLN</option>
                      <option value="EUR">EUR</option>
                      <option value="USD">USD</option>
                      <option value="GBP">GBP</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Jednostka stawki
                    </label>
                    <select
                      value={form.rate_unit}
                      onChange={(e) =>
                        setForm((f) => (f ? { ...f, rate_unit: e.target.value } : f))
                      }
                      className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    >
                      <option value="monthly">Miesięcznie</option>
                      <option value="daily">Dziennie</option>
                      <option value="hourly">Godzinowo</option>
                    </select>
                  </div>
                  {form.rate_unit === "hourly" && (
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                        Godziny / miesiąc
                      </label>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={form.billing_hours_per_month}
                        onChange={(e) =>
                          setForm((f) => (f ? { ...f, billing_hours_per_month: e.target.value } : f))
                        }
                        className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                      />
                    </div>
                  )}
                </div>

                <div className="border-t border-gray-100 dark:border-gray-700 pt-3">
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Notatki wewnętrzne (widoczne tylko dla TAC/delivery)
                  </label>
                  <textarea
                    rows={3}
                    value={form.handover_notes}
                    onChange={(e) =>
                      setForm((f) => (f ? { ...f, handover_notes: e.target.value } : f))
                    }
                    placeholder="Preferencje kontraktora, quirks, historia relacji z klientem…"
                    className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                  />
                </div>

                <details className="border-t border-gray-100 dark:border-gray-700 pt-3">
                  <summary className="cursor-pointer text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
                    Osadzenie u klienta
                  </summary>
                  <div className="space-y-3 mt-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                          PM po stronie klienta
                        </label>
                        <input
                          type="text"
                          value={form.client_pm_name}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, client_pm_name: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                          placeholder="Jan Kowalski"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                          Email PM
                        </label>
                        <input
                          type="email"
                          value={form.client_pm_email}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, client_pm_email: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                          placeholder="jan.kowalski@klient.pl"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                          Tryb pracy
                        </label>
                        <select
                          value={form.work_mode}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, work_mode: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                        >
                          <option value="">— nie określono —</option>
                          <option value="remote">Zdalnie</option>
                          <option value="hybrid">Hybrydowo</option>
                          <option value="onsite">Stacjonarnie</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                          Lokalizacja biura
                        </label>
                        <input
                          type="text"
                          value={form.office_location}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, office_location: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                          placeholder="Warszawa — Domaniewska 50"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                          Projekt
                        </label>
                        <input
                          type="text"
                          value={form.project_name}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, project_name: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                          Zespół
                        </label>
                        <input
                          type="text"
                          value={form.team_name}
                          onChange={(e) =>
                            setForm((f) => (f ? { ...f, team_name: e.target.value } : f))
                          }
                          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                        />
                      </div>
                    </div>
                  </div>
                </details>

                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={handleCancelEdit}
                    className="flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700 rounded-lg"
                  >
                    <X className="w-4 h-4" /> Anuluj
                  </button>
                  <button
                    type="submit"
                    disabled={updateMutation.isPending}
                    className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
                  >
                    {updateMutation.isPending ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4" />
                    )}
                    Zapisz
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* Right sidebar: rates & margin */}
          <div className="space-y-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 space-y-3">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
                <Banknote className="w-4 h-4" /> Stawki finansowe
              </h2>
              <div className="text-xs text-gray-500 dark:text-gray-400 flex items-center justify-between">
                <span>Jednostka: {RATE_UNIT_LABELS[contract.rate_unit] ?? contract.rate_unit}</span>
                {contract.rate_unit === "hourly" && (
                  <span>{contract.billing_hours_per_month} h/mies.</span>
                )}
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Klient</span>
                  <span className="font-medium">
                    {formatCurrency(contract.rate_client, contract.currency)}
                    <span className="text-xs opacity-70">{unitSuffix}</span>
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">Kandydat</span>
                  <span className="font-medium">
                    {formatCurrency(contract.rate_candidate, contract.currency)}
                    <span className="text-xs opacity-70">{unitSuffix}</span>
                  </span>
                </div>
                <div className="flex justify-between pt-2 border-t border-gray-100 dark:border-gray-700">
                  <span className="text-gray-500 dark:text-gray-400 flex items-center gap-1">
                    <TrendingUp className="w-3.5 h-3.5" /> Marża
                  </span>
                  <span
                    className={`font-bold text-right ${
                      (contract.margin ?? 0) > 0 ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {formatCurrency(contract.margin, contract.currency)}
                    <span className="text-xs opacity-70">{unitSuffix}</span>
                    {marginPct && (
                      <span className="ml-1 text-xs opacity-70">({marginPct}%)</span>
                    )}
                  </span>
                </div>
                {contract.rate_unit !== "monthly" && monthlyMargin !== null && (
                  <div className="flex justify-between pt-1 text-xs text-gray-500 dark:text-gray-400">
                    <span>Marża miesięcznie (≈)</span>
                    <span>{formatCurrency(monthlyMargin, contract.currency)}</span>
                  </div>
                )}
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6 text-xs text-gray-500 dark:text-gray-400 space-y-1">
              <div>Utworzono: {formatDate(contract.created_at)}</div>
              <div>Aktualizacja: {formatDate(contract.updated_at)}</div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Dokumenty */}
      {activeTab === "documents" && <ContractDocumentsTab contractId={id} />}

      {/* Tab: Aneksy */}
      {activeTab === "amendments" && <ContractAmendmentsTab contractId={id} />}

      {/* Tab: Onboarding */}
      {activeTab === "onboarding" && <ContractOnboardingTab contractId={id} />}

      {/* Tab: Rate history */}
      {activeTab === "rateHistory" && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden">
          {!rateHistory || rateHistory.length === 0 ? (
            <div className="p-8 text-center text-sm text-gray-500 dark:text-gray-400">
              Brak historii stawek dla tego kandydata i klienta.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-700/40 text-xs uppercase text-gray-500 dark:text-gray-400">
                <tr>
                  <th className="text-left px-4 py-2">Od</th>
                  <th className="text-left px-4 py-2">Do</th>
                  <th className="text-left px-4 py-2">Typ</th>
                  <th className="text-right px-4 py-2">Stawka</th>
                  <th className="text-left px-4 py-2">Notatka</th>
                </tr>
              </thead>
              <tbody>
                {rateHistory.map((row) => (
                  <tr
                    key={row.id}
                    className="border-t border-gray-100 dark:border-gray-700"
                  >
                    <td className="px-4 py-2">{formatDate(row.start_date)}</td>
                    <td className="px-4 py-2">
                      {row.end_date ? formatDate(row.end_date) : "—"}
                    </td>
                    <td className="px-4 py-2 uppercase">{row.contract_type}</td>
                    <td className="px-4 py-2 text-right font-medium">
                      {formatCurrency(row.rate, row.currency)}
                    </td>
                    <td className="px-4 py-2 text-gray-500 dark:text-gray-400">
                      {row.notes ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab: Timeline (activity log) */}
      {activeTab === "timeline" && (
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-6">
          {!activities || activities.length === 0 ? (
            <div className="text-center text-sm text-gray-500 dark:text-gray-400 py-6">
              Brak wpisów w historii.
            </div>
          ) : (
            <ol className="space-y-4">
              {activities.map((a) => (
                <li key={a.id} className="flex gap-3">
                  <div className="w-2 h-2 rounded-full bg-blue-500 mt-2 shrink-0" />
                  <div className="flex-1">
                    <div className="text-sm text-gray-900 dark:text-gray-100">
                      <span className="font-medium capitalize">{a.action}</span>
                      {a.user_name && (
                        <span className="text-gray-500 dark:text-gray-400">
                          {" "}
                          · {a.user_name}
                        </span>
                      )}
                    </div>
                    {a.details && Object.keys(a.details).length > 0 && (
                      <pre className="mt-1 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900/50 rounded px-2 py-1 overflow-x-auto">
                        {JSON.stringify(a.details, null, 2)}
                      </pre>
                    )}
                    <div className="text-xs text-gray-400 mt-0.5">
                      {formatDate(a.created_at)}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
