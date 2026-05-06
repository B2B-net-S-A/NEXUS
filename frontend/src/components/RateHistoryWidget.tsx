"use client";

import { useEffect, useState } from "react";
import { DollarSign, Loader2, Plus, Trash2 } from "lucide-react";
import { phase5Api, RateHistoryRow } from "@/lib/api";

interface Props {
  candidateId: number;
}

const CONTRACT_LABEL: Record<string, string> = {
  b2b: "B2B",
  uop: "UoP",
  zlecenie: "Zlecenie",
};

export function RateHistoryWidget({ candidateId }: Props) {
  const [rows, setRows] = useState<RateHistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [clients, setClients] = useState<{ id: number; name: string }[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    rate: "",
    contract_type: "b2b" as "b2b" | "uop" | "zlecenie",
    start_date: "",
    client_id: "",
    notes: "",
  });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [rRes, cRes] = await Promise.all([
        phase5Api.rateHistory.list(candidateId),
        phase5Api.clientsLookup(),
      ]);
      setRows(rRes.data);
      setClients(cRes.data);
    } catch (e) {
      console.error("rate history load failed:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateId]);

  const handleCreate = async () => {
    if (!form.rate || !form.start_date) {
      alert("Stawka i data startu są wymagane.");
      return;
    }
    setSaving(true);
    try {
      await phase5Api.rateHistory.create(candidateId, {
        rate: Number(form.rate),
        contract_type: form.contract_type,
        start_date: form.start_date,
        client_id: form.client_id ? Number(form.client_id) : null,
        notes: form.notes || null,
      });
      setForm({ rate: "", contract_type: "b2b", start_date: "", client_id: "", notes: "" });
      setShowForm(false);
      await load();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      alert(`Nie zapisano: ${msg}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Usunąć rekord stawki?")) return;
    try {
      await phase5Api.rateHistory.delete(id);
      await load();
    } catch (e) {
      console.error(e);
    }
  };

  const clientName = (id: number | null) =>
    clients.find((c) => c.id === id)?.name ?? (id ? `#${id}` : "—");

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium flex items-center gap-2 text-foreground dark:text-foreground">
          <DollarSign className="w-4 h-4 text-emerald-500" />
          Historia stawek ({rows.length})
        </h3>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="text-xs text-primary hover:underline flex items-center gap-1"
          data-testid="rate-history-add-toggle"
        >
          <Plus className="w-3 h-3" />
          {showForm ? "Anuluj" : "Dodaj stawkę"}
        </button>
      </div>

      {showForm && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mb-3 p-3 rounded bg-muted dark:bg-card/40">
          <input
            type="number"
            placeholder="Stawka PLN"
            value={form.rate}
            onChange={(e) => setForm((f) => ({ ...f, rate: e.target.value }))}
            className="col-span-2 rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          />
          <select
            value={form.contract_type}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                contract_type: e.target.value as "b2b" | "uop" | "zlecenie",
              }))
            }
            className="rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          >
            <option value="b2b">B2B</option>
            <option value="uop">UoP</option>
            <option value="zlecenie">Zlecenie</option>
          </select>
          <input
            type="date"
            value={form.start_date}
            onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
            className="rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          />
          <select
            value={form.client_id}
            onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}
            className="col-span-2 md:col-span-1 rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          >
            <option value="">-- klient --</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            onClick={handleCreate}
            disabled={saving}
            className="rounded bg-primary text-white text-sm px-3 py-1 hover:bg-primary/90 disabled:opacity-50"
            data-testid="rate-history-save"
          >
            {saving ? "…" : "Zapisz"}
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Brak zapisanych stawek.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-muted-foreground">
            <tr>
              <th className="text-left py-1">Data startu</th>
              <th className="text-left">Klient</th>
              <th className="text-right">Stawka</th>
              <th className="text-left pl-4">Kontrakt</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                className="border-t border-border dark:border-border"
              >
                <td className="py-1.5">{r.start_date}</td>
                <td>{clientName(r.client_id)}</td>
                <td className="text-right">
                  {r.rate.toLocaleString()} {r.currency}
                </td>
                <td className="pl-4">{CONTRACT_LABEL[r.contract_type] ?? r.contract_type}</td>
                <td className="text-right">
                  <button
                    onClick={() => handleDelete(r.id)}
                    className="text-red-400 hover:text-destructive"
                    aria-label="Usuń"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
