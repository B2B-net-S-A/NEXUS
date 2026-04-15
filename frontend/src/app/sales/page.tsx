"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  TrendingUp,
  Plus,
  X,
  ChevronRight,
  DollarSign,
  Target,
  Trophy,
  Percent,
  User,
  Building2,
  Calendar,
  ArrowRight,
  Briefcase,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SalesOpportunity {
  id: number;
  client_id: number;
  title: string;
  contact_person: string | null;
  description: string | null;
  stage: SalesStage;
  value: number | null;
  currency: string;
  probability: number;
  expected_close_date: string | null;
  assigned_to: number | null;
  lost_reason: string | null;
  converted_job_id: number | null;
  created_at: string;
  updated_at: string;
}

interface SalesStats {
  by_stage: Record<string, { count: number; total_value: number }>;
  total_pipeline_value: number;
  won_this_month_count: number;
  won_this_month_value: number;
  conversion_rate: number;
  total_opportunities: number;
}

type SalesStage = "lead" | "qualification" | "proposal" | "negotiation" | "won" | "lost";

// ── Constants ─────────────────────────────────────────────────────────────────

const STAGES: { key: SalesStage; label: string; color: string; bg: string }[] = [
  { key: "lead", label: "Lead", color: "text-gray-600", bg: "bg-gray-100" },
  { key: "qualification", label: "Kwalifikacja", color: "text-blue-600", bg: "bg-blue-50" },
  { key: "proposal", label: "Oferta", color: "text-violet-600", bg: "bg-violet-50" },
  { key: "negotiation", label: "Negocjacje", color: "text-amber-600", bg: "bg-amber-50" },
  { key: "won", label: "Wygrana", color: "text-emerald-600", bg: "bg-emerald-50" },
  { key: "lost", label: "Przegrana", color: "text-red-600", bg: "bg-red-50" },
];

const STAGE_BORDER: Record<SalesStage, string> = {
  lead: "border-gray-300",
  qualification: "border-blue-300",
  proposal: "border-violet-300",
  negotiation: "border-amber-300",
  won: "border-emerald-300",
  lost: "border-red-300",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatValue(value: number | null, currency: string) {
  if (!value) return "—";
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: currency || "PLN",
    maximumFractionDigits: 0,
  }).format(value);
}

// ── Opportunity Card ──────────────────────────────────────────────────────────

function OpportunityCard({
  opp,
  onClick,
}: {
  opp: SalesOpportunity;
  onClick: () => void;
}) {
  const stage = STAGES.find((s) => s.key === opp.stage);

  return (
    <div
      onClick={onClick}
      className={cn(
        "bg-white dark:bg-gray-800 rounded-xl border-l-4 shadow-sm p-3 cursor-pointer hover:shadow-md transition-all",
        STAGE_BORDER[opp.stage]
      )}
    >
      <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-tight line-clamp-2">{opp.title}</h4>

      {opp.contact_person && (
        <div className="flex items-center gap-1 mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          <User className="w-3 h-3" />
          {opp.contact_person}
        </div>
      )}

      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-100 dark:border-gray-700">
        <span className="text-sm font-bold text-gray-800 dark:text-gray-200">{formatValue(opp.value, opp.currency)}</span>
        <span className="text-xs text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded-full">
          {opp.probability}%
        </span>
      </div>

      {opp.expected_close_date && (
        <div className="flex items-center gap-1 mt-1.5 text-xs text-gray-400">
          <Calendar className="w-3 h-3" />
          {new Date(opp.expected_close_date).toLocaleDateString("pl-PL")}
        </div>
      )}
    </div>
  );
}

// ── Detail Modal ──────────────────────────────────────────────────────────────

function OpportunityModal({
  opp,
  onClose,
  onStageChange,
  onConvert,
}: {
  opp: SalesOpportunity;
  onClose: () => void;
  onStageChange: (id: number, stage: SalesStage) => void;
  onConvert: (id: number) => void;
}) {
  const stage = STAGES.find((s) => s.key === opp.stage);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className={cn("px-6 py-4 border-b border-gray-100 dark:border-gray-700 flex items-start justify-between")}>
          <div className="flex-1 min-w-0">
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold mb-2",
                stage?.bg,
                stage?.color
              )}
            >
              {stage?.label}
            </span>
            <h2 className="text-lg font-bold text-gray-900 leading-tight">{opp.title}</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors ml-3 flex-shrink-0">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          {/* Key metrics */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 rounded-xl p-3">
              <p className="text-xs text-gray-500 mb-0.5">Wartość</p>
              <p className="text-lg font-bold text-gray-900">{formatValue(opp.value, opp.currency)}</p>
            </div>
            <div className="bg-gray-50 rounded-xl p-3">
              <p className="text-xs text-gray-500 mb-0.5">Prawdopodobieństwo</p>
              <p className="text-lg font-bold text-gray-900">{opp.probability}%</p>
            </div>
          </div>

          {/* Details */}
          {opp.contact_person && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Kontakt</p>
              <p className="text-sm text-gray-700">{opp.contact_person}</p>
            </div>
          )}

          {opp.description && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Opis</p>
              <p className="text-sm text-gray-700 whitespace-pre-line">{opp.description}</p>
            </div>
          )}

          {opp.expected_close_date && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Oczekiwane zamknięcie</p>
              <p className="text-sm text-gray-700">
                {new Date(opp.expected_close_date).toLocaleDateString("pl-PL", {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}
              </p>
            </div>
          )}

          {opp.lost_reason && (
            <div className="bg-red-50 border border-red-100 rounded-xl p-3">
              <p className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-1">Powód przegranej</p>
              <p className="text-sm text-red-700">{opp.lost_reason}</p>
            </div>
          )}

          {/* Stage change */}
          {opp.stage !== "won" && opp.stage !== "lost" && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Zmień etap</p>
              <div className="flex flex-wrap gap-2">
                {STAGES.filter((s) => s.key !== opp.stage && s.key !== "lost").map((s) => (
                  <button
                    key={s.key}
                    onClick={() => onStageChange(opp.id, s.key)}
                    className={cn(
                      "px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors",
                      s.bg,
                      s.color,
                      "border-current/20 hover:opacity-80"
                    )}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Convert to job */}
          {opp.stage === "won" && !opp.converted_job_id && (
            <button
              onClick={() => onConvert(opp.id)}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl font-semibold text-sm transition-colors"
            >
              <Briefcase className="w-4 h-4" />
              Konwertuj na projekt (Job)
            </button>
          )}

          {opp.converted_job_id && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 flex items-center gap-2">
              <Trophy className="w-4 h-4 text-emerald-600 flex-shrink-0" />
              <p className="text-sm text-emerald-700">
                Skonwertowano na Job #{opp.converted_job_id}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Create Opportunity Modal ───────────────────────────────────────────────────

function CreateOpportunityModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    title: "",
    client_id: "",
    contact_person: "",
    description: "",
    stage: "lead" as SalesStage,
    value: "",
    currency: "PLN",
    probability: "50",
    expected_close_date: "",
  });

  const { data: clients } = useQuery({
    queryKey: ["clients-all"],
    queryFn: () => api.get("/api/clients?page_size=100").then((r) => r.data.items),
  });

  const createMutation = useMutation({
    mutationFn: (data: object) => api.post("/api/sales", data),
    onSuccess: () => {
      onCreated();
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate({
      ...form,
      client_id: parseInt(form.client_id),
      value: form.value ? parseFloat(form.value) : null,
      probability: parseInt(form.probability),
      expected_close_date: form.expected_close_date || null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-lg font-bold text-gray-900">Nowa szansa sprzedażowa</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Tytuł *</label>
            <input
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="np. Angular Team — Nordea Q3"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Klient *</label>
            <select
              required
              value={form.client_id}
              onChange={(e) => setForm({ ...form, client_id: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Wybierz klienta...</option>
              {clients?.map((c: { id: number; name: string }) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Osoba kontaktowa</label>
            <input
              value={form.contact_person}
              onChange={(e) => setForm({ ...form, contact_person: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Imię i nazwisko"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Wartość (PLN)</label>
              <input
                type="number"
                value={form.value}
                onChange={(e) => setForm({ ...form, value: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="0"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Prawdopodob. %</label>
              <input
                type="number"
                min="0"
                max="100"
                value={form.probability}
                onChange={(e) => setForm({ ...form, probability: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Etap</label>
            <select
              value={form.stage}
              onChange={(e) => setForm({ ...form, stage: e.target.value as SalesStage })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {STAGES.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Oczekiwane zamknięcie</label>
            <input
              type="date"
              value={form.expected_close_date}
              onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Opis</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder="Szczegóły szansy sprzedażowej..."
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 transition-colors"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-50"
            >
              {createMutation.isPending ? "Tworzenie..." : "Utwórz"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SalesPage() {
  const [selectedOpp, setSelectedOpp] = useState<SalesOpportunity | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const queryClient = useQueryClient();

  const { data: opportunities = [], isLoading } = useQuery<SalesOpportunity[]>({
    queryKey: ["sales"],
    queryFn: () => api.get("/api/sales").then((r) => r.data),
  });

  const { data: stats } = useQuery<SalesStats>({
    queryKey: ["sales-stats"],
    queryFn: () => api.get("/api/sales/stats").then((r) => r.data),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: object }) => api.put(`/api/sales/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales"] });
      queryClient.invalidateQueries({ queryKey: ["sales-stats"] });
      setSelectedOpp(null);
    },
  });

  const convertMutation = useMutation({
    mutationFn: (id: number) => api.post(`/api/sales/${id}/convert`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales"] });
      setSelectedOpp(null);
    },
  });

  const handleStageChange = (id: number, stage: SalesStage) => {
    updateMutation.mutate({ id, data: { stage } });
  };

  const handleConvert = (id: number) => {
    convertMutation.mutate(id);
  };

  const oppsByStage = (stage: SalesStage) =>
    opportunities.filter((o) => o.stage === stage);

  return (
    <div className="space-y-4 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-blue-600" />
            <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Pipeline sprzedażowy</h1>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">CRM — szanse sprzedażowe B2B.net S.A.</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-xl transition-colors"
        >
          <Plus className="w-4 h-4" />
          Nowa szansa
        </button>
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 flex-shrink-0">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-3 flex items-center gap-3">
            <div className="w-9 h-9 bg-blue-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <DollarSign className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400">Pipeline łącznie</p>
              <p className="text-sm font-bold text-gray-900 dark:text-gray-100">
                {formatValue(stats.total_pipeline_value, "PLN")}
              </p>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-3 flex items-center gap-3">
            <div className="w-9 h-9 bg-emerald-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <Trophy className="w-4 h-4 text-emerald-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400">Wygrane (miesiąc)</p>
              <p className="text-sm font-bold text-gray-900 dark:text-gray-100">
                {formatValue(stats.won_this_month_value, "PLN")}
              </p>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-3 flex items-center gap-3">
            <div className="w-9 h-9 bg-violet-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <Target className="w-4 h-4 text-violet-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">Szans ogółem</p>
              <p className="text-sm font-bold text-gray-900 dark:text-gray-100">{stats.total_opportunities}</p>
            </div>
          </div>

          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-3 flex items-center gap-3">
            <div className="w-9 h-9 bg-amber-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <Percent className="w-4 h-4 text-amber-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">Konwersja</p>
              <p className="text-sm font-bold text-gray-900 dark:text-gray-100">{stats.conversion_rate}%</p>
            </div>
          </div>
        </div>
      )}

      {/* Kanban board */}
      <div className="flex gap-3 overflow-x-auto flex-1 pb-4 min-h-0 -mx-4 px-4 sm:mx-0 sm:px-0">
        {STAGES.map((stage) => {
          const opps = oppsByStage(stage.key);
          const stageValue = opps.reduce((sum, o) => sum + (o.value || 0), 0);

          return (
            <div
              key={stage.key}
              className="flex-shrink-0 w-64 flex flex-col"
            >
              {/* Column header */}
              <div className={cn("rounded-t-xl px-3 py-2.5", stage.bg)}>
                <div className="flex items-center justify-between">
                  <span className={cn("text-xs font-bold uppercase tracking-wider", stage.color)}>
                    {stage.label}
                  </span>
                  <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded-full bg-white/60", stage.color)}>
                    {opps.length}
                  </span>
                </div>
                {stageValue > 0 && (
                  <p className="text-xs text-gray-500 mt-0.5">{formatValue(stageValue, "PLN")}</p>
                )}
              </div>

              {/* Cards */}
              <div className="flex-1 bg-gray-50/50 dark:bg-gray-800/50 rounded-b-xl border border-t-0 border-gray-200 dark:border-gray-700 p-2 space-y-2 overflow-y-auto min-h-[200px]">
                {isLoading ? (
                  <div className="flex items-center justify-center h-20">
                    <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : opps.length === 0 ? (
                  <p className="text-xs text-gray-400 dark:text-gray-500 text-center py-6">Brak szans</p>
                ) : (
                  opps.map((opp) => (
                    <OpportunityCard
                      key={opp.id}
                      opp={opp}
                      onClick={() => setSelectedOpp(opp)}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Modals */}
      {selectedOpp && (
        <OpportunityModal
          opp={selectedOpp}
          onClose={() => setSelectedOpp(null)}
          onStageChange={handleStageChange}
          onConvert={handleConvert}
        />
      )}

      {showCreate && (
        <CreateOpportunityModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ["sales"] });
            queryClient.invalidateQueries({ queryKey: ["sales-stats"] });
          }}
        />
      )}
    </div>
  );
}
