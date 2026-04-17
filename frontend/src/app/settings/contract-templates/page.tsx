"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { ArrowLeft, Plus, Trash2, Save, X, Pencil } from "lucide-react";

interface ContractTemplate {
  id: number;
  name: string;
  contract_type: string;
  content_jinja: string;
  is_default: boolean;
  created_by: number | null;
}

const STARTER_JINJA = `<h1>Umowa o świadczenie usług IT</h1>
<p><strong>Nr:</strong> {{ contract.id }}</p>
<p>Zawarta w dniu {{ contract.start_date }} pomiędzy:</p>
<p><strong>{{ client.name }}</strong> (Zamawiający)</p>
<p>a</p>
<p><strong>{{ candidate.full_name }}</strong> (Wykonawca)</p>

<h2>§1 Przedmiot umowy</h2>
<p>Wykonawca zobowiązuje się do świadczenia usług w roli {{ job.title or '—' }}
  w ramach projektu {{ contract.project_name or '—' }} (zespół: {{ contract.team_name or '—' }}).</p>

<h2>§2 Wynagrodzenie</h2>
<p>Stawka: {{ contract.rate_candidate }} {{ contract.currency }} / {{ contract.rate_unit }}.</p>

<h2>§3 Okres obowiązywania</h2>
<p>Od {{ contract.start_date }} do {{ contract.end_date or 'bezterminowo' }}.</p>

<h2>§4 Podpisy</h2>
<p>…</p>`;

function TemplateEditor({
  template,
  onCancel,
  onSaved,
}: {
  template: Partial<ContractTemplate> | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    name: template?.name ?? "",
    contract_type: template?.contract_type ?? "b2b",
    content_jinja: template?.content_jinja ?? STARTER_JINJA,
    is_default: template?.is_default ?? false,
  });
  const [error, setError] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      if (template?.id) {
        return api.patch(`/api/contract-templates/${template.id}`, payload);
      }
      return api.post("/api/contract-templates", payload);
    },
    onSuccess: () => onSaved(),
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? (err instanceof Error ? err.message : "Błąd"));
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        saveMutation.mutate(form);
      }}
      className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm p-4 space-y-3"
    >
      {error && (
        <div className="text-sm text-red-700 bg-red-50 dark:bg-red-900/30 dark:text-red-300 rounded px-3 py-2 whitespace-pre-wrap">
          {error}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="block">
          <span className="block text-xs text-gray-500 mb-1">Nazwa</span>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700"
          />
        </label>
        <label className="block">
          <span className="block text-xs text-gray-500 mb-1">Typ kontraktu</span>
          <select
            value={form.contract_type}
            onChange={(e) => setForm({ ...form, contract_type: e.target.value })}
            className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700"
          >
            <option value="b2b">B2B</option>
            <option value="uop">UoP</option>
            <option value="uzlecenie">Zlecenie</option>
            <option value="annex">Aneks</option>
          </select>
        </label>
      </div>
      <label className="block">
        <span className="block text-xs text-gray-500 mb-1">Zawartość (Jinja2 + HTML)</span>
        <textarea
          rows={20}
          value={form.content_jinja}
          onChange={(e) => setForm({ ...form, content_jinja: e.target.value })}
          className="w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg text-xs font-mono bg-white dark:bg-gray-700"
        />
      </label>
      <label className="inline-flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.is_default}
          onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
        />
        Ustaw jako domyślny dla tego typu kontraktu
      </label>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700 rounded-lg"
        >
          <X className="w-4 h-4 inline mr-1" /> Anuluj
        </button>
        <button
          type="submit"
          disabled={saveMutation.isPending}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
        >
          <Save className="w-4 h-4 inline mr-1" />
          {saveMutation.isPending ? "Zapisywanie…" : "Zapisz"}
        </button>
      </div>
      <div className="text-xs text-gray-500 dark:text-gray-400 pt-2 border-t border-gray-100 dark:border-gray-700">
        Dostępne zmienne: <code>{"{{ contract.* }}"}</code> · <code>{"{{ candidate.* }}"}</code>
        {" · "}<code>{"{{ client.* }}"}</code> · <code>{"{{ job.* }}"}</code>.
        Np. <code>{"{{ candidate.full_name }}"}</code>, <code>{"{{ contract.rate_candidate }}"}</code>.
      </div>
    </form>
  );
}

export default function ContractTemplatesPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<Partial<ContractTemplate> | null>(null);

  const { data } = useQuery<ContractTemplate[]>({
    queryKey: ["contract-templates"],
    queryFn: () => api.get("/api/contract-templates").then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/contract-templates/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-templates"] }),
  });

  return (
    <RequireRole roles={["admin"]}>
      <div className="space-y-4 max-w-5xl">
        <Link
          href="/settings"
          className="inline-flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Ustawienia
        </Link>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Szablony kontraktów</h1>
          {!editing && (
            <button
              onClick={() => setEditing({})}
              className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2"
            >
              <Plus className="w-4 h-4" /> Nowy szablon
            </button>
          )}
        </div>

        {editing && (
          <TemplateEditor
            template={editing.id ? editing : null}
            onCancel={() => setEditing(null)}
            onSaved={() => {
              queryClient.invalidateQueries({ queryKey: ["contract-templates"] });
              setEditing(null);
            }}
          />
        )}

        {!editing && (
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden">
            {!data || data.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-500 italic">
                Brak szablonów — utwórz pierwszy, żeby TAC mógł generować umowy z 1 kliknięcia.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-700/40 text-xs uppercase text-gray-500 dark:text-gray-400">
                  <tr>
                    <th className="text-left px-3 py-2">Nazwa</th>
                    <th className="text-left px-3 py-2">Typ</th>
                    <th className="text-left px-3 py-2">Domyślny</th>
                    <th className="text-right px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((t) => (
                    <tr key={t.id} className="border-t border-gray-100 dark:border-gray-700">
                      <td className="px-3 py-2 font-medium">{t.name}</td>
                      <td className="px-3 py-2 uppercase text-xs text-gray-500">
                        {t.contract_type}
                      </td>
                      <td className="px-3 py-2 text-gray-500">
                        {t.is_default ? "Tak" : "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <div className="inline-flex gap-1">
                          <button
                            onClick={() => setEditing(t)}
                            className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                            title="Edytuj"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => {
                              if (window.confirm(`Usunąć szablon "${t.name}"?`)) {
                                deleteMutation.mutate(t.id);
                              }
                            }}
                            className="p-1.5 rounded hover:bg-red-50 text-red-500"
                            title="Usuń"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </RequireRole>
  );
}
