"use client";

import { useEffect, useState } from "react";
import { AlertOctagon, Loader2, Plus, X } from "lucide-react";
import { phase5Api, ConflictRow } from "@/lib/api";

interface Props {
  candidateId: number;
}

const TYPE_LABEL: Record<string, string> = {
  blacklist: "Blacklist",
  current_employment: "Obecne zatrudnienie",
  nda: "NDA / cooling-off",
  competitor: "Konkurencja",
};

const TYPE_COLOR: Record<string, string> = {
  blacklist: "bg-destructive/15 text-destructive border-red-300",
  current_employment: "bg-amber-100 text-amber-700 border-amber-300",
  nda: "bg-purple-100 text-purple-700 border-purple-300",
  competitor: "bg-slate-100 text-slate-700 border-slate-300",
};

export function ConflictsWidget({ candidateId }: Props) {
  const [rows, setRows] = useState<ConflictRow[]>([]);
  const [clients, setClients] = useState<{ id: number; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    client_id: "",
    type: "blacklist" as ConflictRow["type"],
    reason: "",
  });
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [cRes, clRes] = await Promise.all([
        phase5Api.conflicts.list(candidateId, true),
        phase5Api.clientsLookup(),
      ]);
      setRows(cRes.data);
      setClients(clRes.data);
    } catch (e) {
      console.error("conflicts load failed:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateId]);

  const handleCreate = async () => {
    if (!form.client_id) {
      alert("Wybierz klienta.");
      return;
    }
    setSaving(true);
    try {
      await phase5Api.conflicts.create(candidateId, {
        client_id: Number(form.client_id),
        type: form.type,
        reason: form.reason || undefined,
      });
      setForm({ client_id: "", type: "blacklist", reason: "" });
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

  const handleDeactivate = async (id: number) => {
    if (!confirm("Zdezaktywować konflikt?")) return;
    try {
      await phase5Api.conflicts.deactivate(id);
      await load();
    } catch (e) {
      console.error(e);
    }
  };

  const clientName = (id: number) =>
    clients.find((c) => c.id === id)?.name ?? `#${id}`;

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium flex items-center gap-2 text-foreground dark:text-foreground">
          <AlertOctagon className="w-4 h-4 text-destructive" />
          Konflikty klient↔kandydat ({rows.length})
        </h3>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="text-xs text-primary hover:underline flex items-center gap-1"
          data-testid="conflict-add-toggle"
        >
          <Plus className="w-3 h-3" />
          {showForm ? "Anuluj" : "Dodaj konflikt"}
        </button>
      </div>

      {showForm && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2 mb-3 p-3 rounded bg-muted dark:bg-card/40">
          <select
            value={form.client_id}
            onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}
            className="rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          >
            <option value="">-- klient --</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={form.type}
            onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as ConflictRow["type"] }))}
            className="rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          >
            <option value="blacklist">Blacklist (zakaz)</option>
            <option value="current_employment">Obecne zatrudnienie</option>
            <option value="nda">NDA / cooling-off</option>
            <option value="competitor">Klient konkurencyjny</option>
          </select>
          <input
            placeholder="Powód (opcjonalnie)"
            value={form.reason}
            onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
            className="rounded border border-border dark:border-border px-2 py-1 text-sm bg-card dark:bg-muted"
          />
          <button
            onClick={handleCreate}
            disabled={saving}
            className="rounded bg-red-600 text-white text-sm px-3 py-1 hover:bg-red-700 disabled:opacity-50"
            data-testid="conflict-save"
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
        <p className="text-sm text-muted-foreground">Brak aktywnych konfliktów.</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((c) => (
            <li
              key={c.id}
              className="flex items-center gap-3 rounded border border-border dark:border-border px-3 py-2 text-sm"
            >
              <span
                className={`text-xs px-2 py-0.5 rounded-full border ${TYPE_COLOR[c.type]}`}
              >
                {TYPE_LABEL[c.type] ?? c.type}
              </span>
              <span className="font-medium text-foreground dark:text-muted-foreground">
                {clientName(c.client_id)}
              </span>
              {c.reason && (
                <span className="text-xs text-muted-foreground flex-1 truncate">
                  {c.reason}
                </span>
              )}
              <button
                onClick={() => handleDeactivate(c.id)}
                className="text-muted-foreground hover:text-destructive"
                aria-label="Dezaktywuj"
              >
                <X className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
