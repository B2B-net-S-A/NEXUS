"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, Save, Trash2, Plus, Sparkles, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  scoringWeightsApi,
  type ScoringWeightProfile,
  type ScoringWeights,
} from "@/lib/api";

const DEFAULT_WEIGHTS: ScoringWeights = {
  semantic: 40,
  skills: 30,
  salary: 15,
  location: 10,
  availability: 5,
};

const LAYER_LABELS: Record<keyof ScoringWeights, string> = {
  semantic: "Dopasowanie semantyczne (CV ↔ opis oferty)",
  skills: "Umiejętności (must / nice)",
  salary: "Zarobki",
  location: "Lokalizacja / tryb pracy",
  availability: "Dostępność",
};

const LAYER_COLORS: Record<keyof ScoringWeights, string> = {
  semantic: "bg-purple-500",
  skills: "bg-blue-500",
  salary: "bg-emerald-500",
  location: "bg-amber-500",
  availability: "bg-rose-500",
};

function sum(w: ScoringWeights): number {
  return w.semantic + w.skills + w.salary + w.location + w.availability;
}

interface ProfileEditorProps {
  initial?: ScoringWeightProfile | null;
  onSaved: () => void;
  onCancel: () => void;
}

function ProfileEditor({ initial, onSaved, onCancel }: ProfileEditorProps) {
  const [name, setName] = useState(initial?.name ?? "Nowy profil");
  const [weights, setWeights] = useState<ScoringWeights>(
    initial?.weights ?? DEFAULT_WEIGHTS
  );
  const [active, setActive] = useState(initial?.active ?? true);
  const [error, setError] = useState<string | null>(null);

  const total = sum(weights);
  const valid = total === 100 && name.trim().length >= 2;

  const qc = useQueryClient();
  const createMut = useMutation({
    mutationFn: (payload: {
      name: string;
      weights: ScoringWeights;
      active: boolean;
    }) => scoringWeightsApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scoring-weights"] });
      onSaved();
    },
    onError: (e: unknown) => {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd zapisu")
          : "Błąd zapisu";
      setError(String(msg));
    },
  });
  const updateMut = useMutation({
    mutationFn: (payload: {
      name: string;
      weights: ScoringWeights;
      active: boolean;
    }) => scoringWeightsApi.update(initial!.id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scoring-weights"] });
      onSaved();
    },
    onError: (e: unknown) => {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data
              ?.detail ?? "Błąd zapisu")
          : "Błąd zapisu";
      setError(String(msg));
    },
  });

  const handleSubmit = () => {
    if (!valid) {
      setError(`Suma wag musi wynosić 100 (obecnie: ${total})`);
      return;
    }
    setError(null);
    const payload = { name: name.trim(), weights, active };
    if (initial) updateMut.mutate(payload);
    else createMut.mutate(payload);
  };

  const updateLayer = (layer: keyof ScoringWeights, value: number) => {
    setWeights((prev) => ({ ...prev, [layer]: value }));
  };

  const resetDefault = () => setWeights(DEFAULT_WEIGHTS);

  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 font-semibold text-lg text-gray-900 dark:text-gray-100 bg-transparent border-b border-gray-200 dark:border-gray-700 focus:outline-none focus:border-blue-500 px-1"
          placeholder="Nazwa profilu"
        />
        <label className="inline-flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
            className="accent-blue-600"
          />
          Aktywny
        </label>
      </div>

      {/* Stacked bar preview */}
      <div
        className="flex h-3 rounded-full overflow-hidden border border-gray-200 dark:border-gray-700"
        role="img"
        aria-label={`Rozkład wag: ${total}/100`}
      >
        {(Object.keys(weights) as Array<keyof ScoringWeights>).map((layer) => {
          const pct = (weights[layer] / Math.max(total, 1)) * 100;
          if (pct <= 0) return null;
          return (
            <div
              key={layer}
              className={cn("h-full", LAYER_COLORS[layer])}
              style={{ width: `${pct}%` }}
              title={`${LAYER_LABELS[layer]}: ${weights[layer]}`}
            />
          );
        })}
      </div>

      <div className="space-y-3">
        {(Object.keys(weights) as Array<keyof ScoringWeights>).map((layer) => (
          <div key={layer} className="flex items-center gap-3">
            <label className="text-xs font-medium text-gray-700 dark:text-gray-300 w-64">
              <span
                className={cn("inline-block w-2 h-2 rounded-full mr-2", LAYER_COLORS[layer])}
                aria-hidden
              />
              {LAYER_LABELS[layer]}
            </label>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={weights[layer]}
              onChange={(e) => updateLayer(layer, Number(e.target.value))}
              className="flex-1 accent-blue-600"
            />
            <input
              type="number"
              min={0}
              max={100}
              value={weights[layer]}
              onChange={(e) => updateLayer(layer, Number(e.target.value) || 0)}
              className="w-16 px-2 py-1 text-xs text-right border border-gray-200 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 dark:text-gray-100"
            />
          </div>
        ))}
      </div>

      <div
        className={cn(
          "flex items-center justify-between text-xs font-medium px-3 py-2 rounded-lg",
          total === 100
            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
            : "bg-amber-50 text-amber-700 border border-amber-200"
        )}
      >
        <span>Suma: {total} / 100</span>
        <button
          onClick={resetDefault}
          className="text-blue-600 hover:text-blue-800 hover:underline"
        >
          Przywróć domyślne
        </button>
      </div>

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-700">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:text-gray-800"
        >
          Anuluj
        </button>
        <button
          onClick={handleSubmit}
          disabled={!valid || createMut.isPending || updateMut.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 font-medium"
        >
          <Save className="w-3.5 h-3.5" />
          {initial ? "Zapisz zmiany" : "Utwórz profil"}
        </button>
      </div>
    </div>
  );
}

function ProfileRow({
  profile,
  onEdit,
  onDelete,
}: {
  profile: ScoringWeightProfile;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const total = sum(profile.weights);
  return (
    <li
      className="flex items-center gap-4 border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg px-4 py-3"
      data-testid={`scoring-weight-profile-${profile.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="font-semibold text-sm text-gray-900 dark:text-gray-100">
            {profile.name}
          </p>
          {!profile.active && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">
              nieaktywny
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1 text-[11px] text-gray-500 dark:text-gray-400">
          {(Object.keys(profile.weights) as Array<keyof ScoringWeights>).map((k) => (
            <span key={k}>
              <span
                className={cn(
                  "inline-block w-1.5 h-1.5 rounded-full mr-1",
                  LAYER_COLORS[k]
                )}
                aria-hidden
              />
              {profile.weights[k]}
            </span>
          ))}
          <span className="ml-auto">suma: {total}</span>
        </div>
      </div>
      <button
        onClick={onEdit}
        className="text-xs text-blue-600 hover:text-blue-800 hover:underline"
      >
        Edytuj
      </button>
      <button
        onClick={onDelete}
        className="text-xs text-red-600 hover:text-red-800"
        title="Usuń"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </li>
  );
}

export default function ScoringWeightsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["scoring-weights"],
    queryFn: () => scoringWeightsApi.list().then((r) => r.data),
  });

  const [editing, setEditing] = useState<ScoringWeightProfile | null | "new">(null);

  const deleteMut = useMutation({
    mutationFn: (id: number) => scoringWeightsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scoring-weights"] }),
  });

  useEffect(() => {
    // Close editor after successful mutation
  }, [data]);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link
          href="/settings"
          className="text-gray-500 hover:text-gray-700 dark:text-gray-400"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-500" />
            Profile wag scoringu
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Domyślnie: semantic 40 + skills 30 + salary 15 + location 10 +
            availability 5. Własne profile ułatwią tunowanie pod konkretnego
            klienta (np. &quot;klient woli seniorów&quot; → boost skills).
          </p>
        </div>
        {editing === null && (
          <button
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium shadow-sm"
            data-testid="add-scoring-weight-profile"
          >
            <Plus className="w-4 h-4" />
            Nowy profil
          </button>
        )}
      </div>

      {editing === "new" && (
        <ProfileEditor
          onSaved={() => setEditing(null)}
          onCancel={() => setEditing(null)}
        />
      )}
      {editing && editing !== "new" && (
        <ProfileEditor
          initial={editing}
          onSaved={() => setEditing(null)}
          onCancel={() => setEditing(null)}
        />
      )}

      {isLoading && (
        <p className="text-sm text-gray-400 text-center py-10">Ładowanie…</p>
      )}
      {error && (
        <p className="text-sm text-red-600 text-center py-6">
          Nie udało się pobrać profili
        </p>
      )}
      {!isLoading && data && data.length === 0 && editing === null && (
        <div className="text-center py-10 text-gray-500 dark:text-gray-400 text-sm border border-dashed border-gray-200 dark:border-gray-700 rounded-xl">
          Brak profili — scoring używa domyślnych wag (40/30/15/10/5).
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="space-y-2">
          {data.map((p) => (
            <ProfileRow
              key={p.id}
              profile={p}
              onEdit={() => setEditing(p)}
              onDelete={() => {
                if (confirm(`Usunąć profil "${p.name}"?`)) deleteMut.mutate(p.id);
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
