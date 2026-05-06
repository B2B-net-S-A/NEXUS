"use client";

import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  rateBenchmarksApi,
  type RateBenchmarkRow,
  type SeniorityLevel,
} from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { Plus, Trash2, Upload, X, Save } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";

const SENIORITY_LABELS: Record<SeniorityLevel, string> = {
  junior: "Junior",
  mid: "Mid",
  senior: "Senior",
  expert: "Expert",
  principal: "Principal",
};

const RATE_UNIT_LABELS: Record<string, string> = {
  hourly: "godz.",
  daily: "dzień",
  monthly: "mies.",
};

export default function RateBenchmarksPage() {
  return (
    <RequireRole roles={["admin"]}>
      <RateBenchmarksAdmin />
    </RequireRole>
  );
}

function RateBenchmarksAdmin() {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [roleFilter, setRoleFilter] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const [importResult, setImportResult] = useState<{
    created: number;
    skipped: number;
    errors: string[];
  } | null>(null);

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["rate-benchmarks", roleFilter],
    queryFn: async () => {
      const res = await rateBenchmarksApi.list(
        roleFilter ? { role: roleFilter } : undefined,
      );
      return res.data as RateBenchmarkRow[];
    },
  });

  const createMut = useMutation({
    mutationFn: (payload: Partial<RateBenchmarkRow>) =>
      rateBenchmarksApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rate-benchmarks"] });
      setAdding(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => rateBenchmarksApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rate-benchmarks"] }),
  });

  const importMut = useMutation({
    mutationFn: (file: File) => rateBenchmarksApi.importCsv(file),
    onSuccess: (res) => {
      setImportResult(res.data);
      qc.invalidateQueries({ queryKey: ["rate-benchmarks"] });
    },
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Benchmarki stawek</h1>
          <p className="text-sm text-muted-foreground">
            Stawki rynkowe z raportów branżowych (Hays, No Fluff Jobs, Just Join
            IT). Używane przez kartę Benchmark na stronie każdego kontraktu.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="inline-flex items-center gap-1.5 border border-border dark:border-border rounded-md px-3 py-1.5 text-sm hover:bg-muted dark:hover:bg-muted"
          >
            <Upload className="w-3.5 h-3.5" />
            Import CSV
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importMut.mutate(file);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary hover:bg-primary/90 text-white text-sm px-3 py-1.5"
          >
            <Plus className="w-3.5 h-3.5" />
            Dodaj
          </button>
        </div>
      </header>

      {importResult && (
        <div className="rounded-lg border border-border dark:border-border p-4 text-sm bg-muted dark:bg-muted">
          <div className="font-medium mb-1">
            Import: {importResult.created} dodanych, {importResult.skipped}{" "}
            pominiętych
          </div>
          {importResult.errors.length > 0 && (
            <ul className="text-xs text-amber-700 list-disc pl-4">
              {importResult.errors.slice(0, 10).map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={() => setImportResult(null)}
            className="text-xs underline mt-2"
          >
            Zamknij
          </button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <input
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          placeholder="Filtruj po roli…"
          className="border border-border dark:border-border rounded-md px-3 py-1.5 text-sm bg-card dark:bg-card"
        />
      </div>

      {adding && (
        <BenchmarkForm
          onSubmit={(payload) => createMut.mutate(payload)}
          onCancel={() => setAdding(false)}
          submitting={createMut.isPending}
        />
      )}

      <div className="overflow-x-auto rounded-lg border border-border dark:border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted dark:bg-muted text-xs uppercase text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2">Rola</th>
              <th className="text-left px-3 py-2">Seniority</th>
              <th className="text-left px-3 py-2">Jednostka</th>
              <th className="text-right px-3 py-2">Min</th>
              <th className="text-right px-3 py-2">Mediana</th>
              <th className="text-right px-3 py-2">Max</th>
              <th className="text-left px-3 py-2">Lokalizacja</th>
              <th className="text-left px-3 py-2">Źródło</th>
              <th className="text-right px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {isLoading ? (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
                  Ładowanie…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
                  Brak wpisów.
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id}>
                  <td className="px-3 py-2 font-medium">{row.role}</td>
                  <td className="px-3 py-2">
                    {row.seniority ? SENIORITY_LABELS[row.seniority] : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {RATE_UNIT_LABELS[row.rate_unit] || row.rate_unit}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.market_min != null
                      ? formatCurrency(row.market_min, row.currency)
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold">
                    {formatCurrency(row.market_median, row.currency)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.market_max != null
                      ? formatCurrency(row.market_max, row.currency)
                      : "—"}
                  </td>
                  <td className="px-3 py-2">{row.location || "—"}</td>
                  <td className="px-3 py-2">
                    <div className="text-xs">{row.source}</div>
                    <div className="text-xs text-muted-foreground">
                      {formatDate(row.source_date)}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm("Usunąć wpis?")) deleteMut.mutate(row.id);
                      }}
                      className="text-destructive hover:underline"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-muted-foreground">
        CSV header:{" "}
        <code className="bg-muted dark:bg-muted px-1 py-0.5 rounded">
          role,seniority,currency,rate_unit,market_min,market_median,market_max,source,source_date,location,notes
        </code>
      </div>
    </div>
  );
}

interface BenchmarkFormProps {
  onSubmit: (data: Partial<RateBenchmarkRow>) => void;
  onCancel: () => void;
  submitting: boolean;
}

function BenchmarkForm({ onSubmit, onCancel, submitting }: BenchmarkFormProps) {
  const [form, setForm] = useState({
    role: "",
    seniority: "mid" as SeniorityLevel,
    currency: "PLN",
    rate_unit: "hourly" as "hourly" | "daily" | "monthly",
    market_min: "",
    market_median: "",
    market_max: "",
    source: "",
    source_date: new Date().toISOString().slice(0, 10),
    location: "",
    notes: "",
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      role: form.role,
      seniority: form.seniority,
      currency: form.currency,
      rate_unit: form.rate_unit,
      market_min: form.market_min ? Number(form.market_min) : null,
      market_median: Number(form.market_median),
      market_max: form.market_max ? Number(form.market_max) : null,
      source: form.source,
      source_date: form.source_date,
      location: form.location || null,
      notes: form.notes || null,
    });
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-border dark:border-border p-4 space-y-3 bg-muted dark:bg-muted"
    >
      <div className="grid grid-cols-3 gap-3">
        <label className="block col-span-2">
          <span className="text-xs text-muted-foreground">Rola</span>
          <input
            value={form.role}
            onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
            placeholder="Java Developer"
            required
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Seniority</span>
          <select
            value={form.seniority}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                seniority: e.target.value as SeniorityLevel,
              }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
          >
            {Object.entries(SENIORITY_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Jednostka</span>
          <select
            value={form.rate_unit}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                rate_unit: e.target.value as "hourly" | "daily" | "monthly",
              }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
          >
            <option value="hourly">godz.</option>
            <option value="daily">dzień</option>
            <option value="monthly">mies.</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Waluta</span>
          <input
            value={form.currency}
            onChange={(e) =>
              setForm((f) => ({ ...f, currency: e.target.value.toUpperCase() }))
            }
            maxLength={3}
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950 uppercase"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Lokalizacja</span>
          <input
            value={form.location}
            onChange={(e) =>
              setForm((f) => ({ ...f, location: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
            placeholder="Warszawa / Remote"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Min</span>
          <input
            type="number"
            value={form.market_min}
            onChange={(e) =>
              setForm((f) => ({ ...f, market_min: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Mediana *</span>
          <input
            type="number"
            value={form.market_median}
            onChange={(e) =>
              setForm((f) => ({ ...f, market_median: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
            required
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Max</span>
          <input
            type="number"
            value={form.market_max}
            onChange={(e) =>
              setForm((f) => ({ ...f, market_max: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
          />
        </label>
        <label className="block col-span-2">
          <span className="text-xs text-muted-foreground">Źródło</span>
          <input
            value={form.source}
            onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
            placeholder="Hays Guide 2026"
            required
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Data raportu</span>
          <input
            type="date"
            value={form.source_date}
            onChange={(e) =>
              setForm((f) => ({ ...f, source_date: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-gray-950"
            required
          />
        </label>
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-muted-foreground hover:underline inline-flex items-center gap-1"
        >
          <X className="w-3.5 h-3.5" />
          Anuluj
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary hover:bg-primary/90 disabled:opacity-50 text-white text-sm px-3 py-1.5"
        >
          <Save className="w-3.5 h-3.5" />
          {submitting ? "Zapisywanie…" : "Zapisz"}
        </button>
      </div>
    </form>
  );
}
