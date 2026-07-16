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

// Sześć warstw silnika — spójne z backendowym built-in (scoring_service.py):
// 35 + 30 + 12 + 8 + 5 + 10 = 100. Edytor był 5-warstwowy (M3-SCORE/UI):
// ukrywał warstwę Champion i każdy zapisany profil dostawał champion_fit=0
// (cicho wyłączona warstwa), a stare 5-kluczowe rekordy w runtime dostają
// domyślne +10 PONAD budżet 100.
const DEFAULT_WEIGHTS: Required<ScoringWeights> = {
  semantic: 35,
  skills: 30,
  salary: 12,
  location: 8,
  availability: 5,
  champion_fit: 10,
};

const LAYER_LABELS: Record<keyof ScoringWeights, string> = {
  semantic: "Dopasowanie semantyczne (CV ↔ opis oferty)",
  skills: "Umiejętności (must / nice)",
  salary: "Zarobki",
  location: "Lokalizacja / tryb pracy",
  availability: "Dostępność",
  champion_fit: "Champion fit (profil idealnego kandydata)",
};

const LAYER_COLORS: Record<keyof ScoringWeights, string> = {
  semantic: "bg-purple-500",
  skills: "bg-primary",
  salary: "bg-emerald-500",
  location: "bg-amber-500",
  availability: "bg-rose-500",
  champion_fit: "bg-cyan-500",
};

function sum(w: ScoringWeights): number {
  return (
    w.semantic +
    w.skills +
    w.salary +
    w.location +
    w.availability +
    (w.champion_fit ?? 0)
  );
}

/**
 * Normalizacja do 6 jawnych warstw. Historyczny rekord bez `champion_fit`
 * dostaje 10 — tyle właśnie dolicza mu legacy runtime, więc edycja od razu
 * pokazuje realną sumę (110) i wymusza rebalans do 100 przed zapisem.
 */
function normalizeWeights(w: ScoringWeights): Required<ScoringWeights> {
  return { ...w, champion_fit: w.champion_fit ?? 10 };
}

interface ProfileEditorProps {
  initial?: ScoringWeightProfile | null;
  onSaved: () => void;
  onCancel: () => void;
}

function ProfileEditor({ initial, onSaved, onCancel }: ProfileEditorProps) {
  const [name, setName] = useState(initial?.name ?? "Nowy profil");
  const [weights, setWeights] = useState<Required<ScoringWeights>>(
    initial?.weights ? normalizeWeights(initial.weights) : DEFAULT_WEIGHTS
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
    <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 font-semibold text-lg text-foreground dark:text-foreground bg-transparent border-b border-border dark:border-border focus:outline-none focus:border-primary px-1"
          placeholder="Nazwa profilu"
        />
        <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground dark:text-muted-foreground">
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
        className="flex h-3 rounded-full overflow-hidden border border-border dark:border-border"
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
            <label className="text-xs font-medium text-foreground dark:text-muted-foreground w-64">
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
              className="w-16 px-2 py-1 text-xs text-right border border-border dark:border-border rounded-md bg-card dark:bg-muted dark:text-foreground"
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
          className="text-primary hover:text-primary/80 hover:underline"
        >
          Przywróć domyślne
        </button>
      </div>

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive flex items-start gap-2">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          {error}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-2 border-t border-border dark:border-border">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs text-muted-foreground dark:text-muted-foreground hover:text-foreground"
        >
          Anuluj
        </button>
        <button
          onClick={handleSubmit}
          disabled={!valid || createMut.isPending || updateMut.isPending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary hover:bg-primary/90 text-white rounded-lg disabled:opacity-50 font-medium"
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
      className="flex items-center gap-4 border border-border dark:border-border bg-card dark:bg-muted rounded-lg px-4 py-3"
      data-testid={`scoring-weight-profile-${profile.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="font-semibold text-sm text-foreground dark:text-foreground">
            {profile.name}
          </p>
          {!profile.active && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
              nieaktywny
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1 text-[11px] text-muted-foreground dark:text-muted-foreground">
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
        className="text-xs text-primary hover:text-primary/80 hover:underline"
      >
        Edytuj
      </button>
      <button
        onClick={onDelete}
        className="text-xs text-destructive hover:text-red-800"
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
          className="text-muted-foreground hover:text-foreground dark:text-muted-foreground"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-500" />
            Profile wag scoringu
          </h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground">
            Domyślnie: semantic 35 + skills 30 + salary 12 + location 8 +
            availability 5 + champion 10 (suma 100). Własne profile ułatwią
            tunowanie pod konkretnego klienta (np. &quot;klient woli
            seniorów&quot; → boost skills).
          </p>
        </div>
        {editing === null && (
          <button
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-sm font-medium shadow-sm"
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
        <p className="text-sm text-muted-foreground text-center py-10">Ładowanie…</p>
      )}
      {error && (
        <p className="text-sm text-destructive text-center py-6">
          Nie udało się pobrać profili
        </p>
      )}
      {!isLoading && data && data.length === 0 && editing === null && (
        <div className="text-center py-10 text-muted-foreground dark:text-muted-foreground text-sm border border-dashed border-border dark:border-border rounded-xl">
          Brak profili — scoring używa domyślnych wag (35/30/12/8/5/10).
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
