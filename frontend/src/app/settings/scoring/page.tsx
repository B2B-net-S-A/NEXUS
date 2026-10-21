"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, Trash2, Plus, Sparkles, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  scoringWeightsApi,
  type ScoringWeightProfile,
  type ScoringWeights,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";

// Sześć warstw silnika — te same liczby co built-in w scoring_service.py
// (SEMANTIC_MAX … CHAMPION_FIT_MAX): 60 + 10 + 15 + 5 + 0 + 10 = 100. Zgodność
// pilnuje backend/tests/test_scoring_profile_resolution_and_patch.py — do
// 21.10.2026 ekran pokazywał 35/30/12/8/5/10, czyli wagi sprzed 17.08.
const DEFAULT_WEIGHTS: Required<ScoringWeights> = {
  semantic: 60,
  skills: 10,
  salary: 15,
  location: 5,
  availability: 0,
  champion_fit: 10,
};

const LAYER_LABELS: Record<keyof ScoringWeights, string> = {
  semantic: "Podobieństwo CV do rekrutacji",
  skills: "Umiejętności",
  salary: "Stawka",
  location: "Lokalizacja i tryb pracy",
  availability: "Dostępność",
  champion_fit: "Wynik screeningu",
};

/** Co liczy każda waga — jednym zdaniem, po ludzku, tak jak liczy silnik. */
const LAYER_HINTS: Record<keyof ScoringWeights, string> = {
  semantic: "AI porównuje CV i profil z treścią rekrutacji",
  skills: "technologie z listy: wymagane 2×, mile widziane 1×",
  salary: "każdy dostaje tyle samo — ponad budżet to plakietka, nie punkty",
  location: "pół za tryb pracy, pół za miasto",
  availability: "wyłączona — w pomiarze z 17.08 pogarszała trafność",
  champion_fit: "nie wchodzi do „Dop.” — silnik pomija tę wagę",
};

/** Warstwy, które składają się na „Dop.” (bez wyniku screeningu). */
const FIT_LAYERS: (keyof ScoringWeights)[] = [
  "semantic",
  "skills",
  "location",
  "salary",
  "availability",
];

/**
 * Udział warstwy w „Dop.”: silnik bierze pięć wag bez screeningu i przelicza je
 * do 100 (`base_fit_profile` w request_matching_context.py), więc 60 z 90 to 67%.
 */
function fitShares(w: Required<ScoringWeights>): Record<string, number> {
  const total = FIT_LAYERS.reduce((acc, layer) => acc + w[layer], 0) || 1;
  return Object.fromEntries(FIT_LAYERS.map((layer) => [layer, (w[layer] * 100) / total]));
}

/** Jak dziś liczy się „Dop.” — tylko do odczytu, zmienia je profil. */
function DefaultWeights() {
  const shares = fitShares(DEFAULT_WEIGHTS);
  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-card p-5 dark:border-border dark:bg-muted"
      aria-labelledby="default-weights-title"
    >
      <div className="flex items-center gap-2">
        <h2 id="default-weights-title" className="flex-1 text-base font-semibold text-foreground">
          Z czego składa się „Dop.” — dla wszystkich rekrutacji
        </h2>
        <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">udział w ocenie</span>
      </div>
      <ul className="space-y-2.5">
        {FIT_LAYERS.map((layer) => (
          <li key={layer} className="grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_3rem] items-center gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">{LAYER_LABELS[layer]}</p>
              <p className="text-xs text-muted-foreground">{LAYER_HINTS[layer]}</p>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div
                className={cn("h-full rounded-full", LAYER_COLORS[layer])}
                style={{ width: `${shares[layer]}%` }}
              />
            </div>
            <span className="text-right text-sm font-semibold tabular-nums text-foreground">
              {Math.round(shares[layer])}%
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        O kolejności decydują podobieństwo CV, umiejętności i lokalizacja. Stawka dodaje każdemu
        tyle samo, a wynik screeningu nie wchodzi do „Dop.”.
      </p>
    </section>
  );
}

const LAYER_COLORS: Record<keyof ScoringWeights, string> = {
  semantic: "bg-chart-1",
  skills: "bg-chart-2",
  salary: "bg-muted-foreground",
  location: "bg-chart-3",
  availability: "bg-chart-4",
  champion_fit: "bg-chart-5",
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
      setError(apiErrorMessage(e, "Błąd zapisu"));
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
      setError(apiErrorMessage(e, "Błąd zapisu"));
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-0 flex-1 min-w-0 font-semibold text-lg text-foreground dark:text-foreground bg-transparent border-b border-border dark:border-border focus:outline-hidden focus:border-primary px-1"
          placeholder="Nazwa profilu"
        />
        <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground dark:text-muted-foreground">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
            className="accent-primary"
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
          <div key={layer} className="flex flex-wrap sm:flex-nowrap items-center gap-x-3 gap-y-1">
            <label className="text-xs font-medium text-foreground dark:text-muted-foreground w-full sm:w-64 sm:shrink-0">
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
              className="w-0 flex-1 min-w-0 accent-primary"
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
            ? "bg-success-muted text-success-muted-foreground border border-success/30"
            : "bg-warning-muted text-warning-muted-foreground border border-warning/30"
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
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
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
  canEdit,
  onEdit,
  onDelete,
}: {
  profile: ScoringWeightProfile;
  canEdit: boolean;
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
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-[11px] text-muted-foreground dark:text-muted-foreground">
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
      {canEdit && (
        <>
          <button
            onClick={onEdit}
            className="text-xs text-primary hover:text-primary/80 hover:underline"
          >
            Edytuj
          </button>
          <button
            onClick={onDelete}
            className="text-xs text-destructive hover:text-destructive/80"
            title="Usuń"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </>
      )}
    </li>
  );
}

export default function ScoringWeightsPage() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);
  const isAllowed =
    hasRole(user, "admin", "delivery_lead", "head_of_recruitment") &&
    hasSectionAccess(user, "insights", "read");
  const canEdit =
    hasRole(user, "admin") && hasSectionAccess(user, "insights", "write");
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["scoring-weights"],
    queryFn: () => scoringWeightsApi.list().then((r) => r.data),
    enabled: hydrated && isAllowed,
  });

  const [editing, setEditing] = useState<ScoringWeightProfile | null | "new">(null);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const deleteMut = useMutation({
    mutationFn: (id: number) => scoringWeightsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scoring-weights"] }),
  });

  useEffect(() => {
    // Close editor after successful mutation
  }, [data]);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }

  if (!isAllowed) {
    return (
      <div className="p-6 text-muted-foreground">
        Brak dostępu do profili wag scoringu.
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {confirmDialog}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0 basis-64">
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            Ranking kandydatów
          </h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground">
            Co liczy się najbardziej, gdy NEXUS układa kandydatów w kolejności „Dopasowanie”.
          </p>
        </div>
        {canEdit && editing === null && (
          <button
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1.5 bg-primary hover:bg-primary/90 text-white px-3 py-1.5 rounded-lg text-sm font-medium shadow-xs"
            data-testid="add-scoring-weight-profile"
          >
            <Plus className="w-4 h-4" />
            Nowy profil
          </button>
        )}
      </div>

      <DefaultWeights />

      <div>
        <h2 className="text-base font-semibold text-foreground">Własne profile wag</h2>
        <p className="text-sm text-muted-foreground">
          Aktywny profil zastępuje wagi domyślne — np. gdy liczy się bardziej doświadczenie, więcej wagi
          dostają „Umiejętności”.
        </p>
      </div>

      {!canEdit && (
        <p className="rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground">
          Tryb podglądu. Profile może zmieniać wyłącznie administrator z prawem
          zapisu do sekcji Insights.
        </p>
      )}

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
          Brak własnych profili — wszędzie działają wagi domyślne powyżej.
        </div>
      )}
      {data && data.length > 0 && (
        <ul className="space-y-2">
          {data.map((p) => (
            <ProfileRow
              key={p.id}
              profile={p}
              canEdit={canEdit}
              onEdit={() => setEditing(p)}
              onDelete={async () => {
                if (
                  canEdit &&
                  (await askConfirm({
                    title: `Usunąć profil "${p.name}"?`,
                    confirmLabel: "Usuń",
                    variant: "destructive",
                  }))
                ) {
                  deleteMut.mutate(p.id);
                }
              }}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
