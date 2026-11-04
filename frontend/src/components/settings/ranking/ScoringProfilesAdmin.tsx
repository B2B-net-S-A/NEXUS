"use client";

/**
 * Profile wag klienta i osoby — stare trasy CRUD administratora (D3: panel
 * „Ranking kandydatów” zmienia tylko wagi ogólne). Każda zmiana trafia do
 * historii panelu jako „edycja administratora” i NIE przechodzi pomiaru —
 * dlatego ten edytor widzi wyłącznie admin.
 *
 * Decyzja Artura 22.10.2026 (audyt F60): tutaj powstaje WYŁĄCZNIE profil
 * klienta albo osoby. Profil ogólny (bez klienta i osoby) to wagi dla
 * wszystkich — zmienia je tylko panel, po pomiarze; na liście jest do odczytu
 * (serwer i tak odmawia 409).
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Plus, Save, Trash2 } from "lucide-react";

import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import api, {
  scoringWeightsApi,
  type ScoringWeightProfile,
  type ScoringWeightProfileCreate,
  type ScoringWeights,
} from "@/lib/api";
import type { DirectoryPerson } from "@/lib/request-board";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

// Sześć warstw silnika — te same liczby co built-in w scoring_service.py
// (SEMANTIC_MAX … CHAMPION_FIT_MAX): 60 + 10 + 15 + 5 + 0 + 10 = 100. Zgodność
// pilnuje backend/tests/test_scoring_profile_resolution_and_patch.py (czyta ten plik) — do
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

/** Profil ogólny — wagi dla wszystkich, zmienia je tylko panel. */
function isGeneral(profile: ScoringWeightProfile): boolean {
  return profile.client_id == null && profile.user_id == null;
}

type Scope = "client" | "user";

/** Wybór klienta albo osoby — bez niego nowy profil byłby profilem ogólnym. */
function ScopePicker({
  scope,
  onScope,
  client,
  onClient,
  userId,
  onUserId,
}: {
  scope: Scope;
  onScope: (scope: Scope) => void;
  client: ClientRef | null;
  onClient: (client: ClientRef | null) => void;
  userId: string;
  onUserId: (userId: string) => void;
}) {
  // Ten sam klucz co inne listy osób — jedno zapytanie na ekran.
  const people = useQuery<DirectoryPerson[]>({
    queryKey: ["users-directory"],
    queryFn: () => api.get("/api/users").then((r) => r.data),
    staleTime: 60_000,
    enabled: scope === "user",
  });
  const active = (Array.isArray(people.data) ? people.data : [])
    .filter((person) => person.is_active !== false)
    .sort((a, b) => a.name.localeCompare(b.name, "pl"));

  return (
    <fieldset className="min-w-0 space-y-2">
      <legend className="text-xs font-medium text-foreground">
        Dla kogo ten profil
      </legend>
      <div className="flex flex-wrap gap-4 text-sm text-foreground">
        {(
          [
            ["client", "Klient"],
            ["user", "Osoba"],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="inline-flex items-center gap-1.5">
            <input
              type="radio"
              name="scoring-profile-scope"
              value={value}
              checked={scope === value}
              onChange={() => onScope(value)}
              className="accent-primary"
            />
            {label}
          </label>
        ))}
      </div>
      {scope === "client" ? (
        <ClientSinglePicker
          value={client}
          onChange={onClient}
          queryKey="scoring-profile-clients"
        />
      ) : people.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(people.error, "Nie udało się pobrać listy osób.")}
        </p>
      ) : (
        <select
          aria-label="Osoba"
          value={userId}
          onChange={(e) => onUserId(e.target.value)}
          disabled={!people.isSuccess}
          className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground"
        >
          <option value="">
            {people.isSuccess ? "Wybierz osobę…" : "Ładowanie listy osób…"}
          </option>
          {active.map((person) => (
            <option key={person.id} value={person.id}>
              {person.name}
            </option>
          ))}
        </select>
      )}
      <p className="text-xs text-muted-foreground">
        Wagi ogólne zmienia się wyżej, w panelu — po pomiarze na historii.
      </p>
    </fieldset>
  );
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
  const [scope, setScope] = useState<Scope>("client");
  const [client, setClient] = useState<ClientRef | null>(null);
  const [userId, setUserId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const total = sum(weights);
  // Istniejący profil zostaje przy swoim kliencie albo osobie (PATCH bez
  // tych pól ich nie zmienia); nowy musi mieć jedno z dwóch.
  const scoped = Boolean(initial) || (scope === "client" ? client !== null : userId !== "");
  const valid = total === 100 && name.trim().length >= 2 && scoped;

  const qc = useQueryClient();
  const createMut = useMutation({
    mutationFn: (payload: ScoringWeightProfileCreate) =>
      scoringWeightsApi.create(payload),
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
      setError(
        scoped
          ? `Suma wag musi wynosić 100 (obecnie: ${total})`
          : "Wybierz klienta albo osobę.",
      );
      return;
    }
    setError(null);
    const payload = { name: name.trim(), weights, active };
    if (initial) updateMut.mutate(payload);
    else
      createMut.mutate(
        scope === "client"
          ? { ...payload, client_id: client!.id }
          : { ...payload, user_id: Number(userId) },
      );
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

      {!initial && (
        <ScopePicker
          scope={scope}
          onScope={setScope}
          client={client}
          onClient={setClient}
          userId={userId}
          onUserId={setUserId}
        />
      )}

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
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">
            {isGeneral(profile)
              ? "wagi ogólne — zmienia się w panelu"
              : profile.user_id != null
                ? "osoba"
                : "klient"}
          </span>
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

export function ScoringProfilesAdmin() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["scoring-weights"],
    queryFn: () => scoringWeightsApi.list().then((r) => r.data),
  });
  const [editing, setEditing] = useState<ScoringWeightProfile | null | "new">(null);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteMut = useMutation({
    mutationFn: (id: number) => scoringWeightsApi.remove(id),
    onSuccess: () => {
      setDeleteError(null);
      qc.invalidateQueries({ queryKey: ["scoring-weights"] });
      qc.invalidateQueries({ queryKey: ["scoring-panel"] });
    },
    onError: (e: unknown) => setDeleteError(apiErrorMessage(e, "Nie udało się usunąć profilu.")),
  });
  const onSaved = () => {
    setEditing(null);
    qc.invalidateQueries({ queryKey: ["scoring-panel"] });
  };

  return (
    <div className="space-y-3">
      {confirmDialog}
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 basis-64 text-sm text-muted-foreground">
          Profil klienta albo osoby zastępuje wagi ogólne. Zmiana tutaj działa od razu, bez
          pomiaru na historii — zostaje w historii zmian. Wagi ogólne zmienia się tylko
          w panelu wyżej.
        </p>
        {editing === null && (
          <button
            type="button"
            onClick={() => setEditing("new")}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
            data-testid="add-scoring-weight-profile"
          >
            <Plus className="h-4 w-4" />
            Nowy profil
          </button>
        )}
      </div>
      {editing === "new" && <ProfileEditor onSaved={onSaved} onCancel={() => setEditing(null)} />}
      {editing && editing !== "new" && (
        <ProfileEditor initial={editing} onSaved={onSaved} onCancel={() => setEditing(null)} />
      )}
      {query.isLoading && <p className="text-sm text-muted-foreground">Ładowanie profili…</p>}
      {query.isError && (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się pobrać profili.")}
        </p>
      )}
      {deleteError && (
        <p role="alert" className="text-sm text-destructive">
          {deleteError}
        </p>
      )}
      {query.isSuccess && query.data.length === 0 && editing === null && (
        <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
          Brak profili — wszędzie działają wagi ogólne.
        </p>
      )}
      {query.isSuccess && query.data.length > 0 && (
        <ul className="space-y-2">
          {query.data.map((p) => (
            <ProfileRow
              key={p.id}
              profile={p}
              canEdit={!isGeneral(p)}
              onEdit={() => setEditing(p)}
              onDelete={async () => {
                if (
                  await askConfirm({
                    title: `Usunąć profil „${p.name}”?`,
                    confirmLabel: "Usuń",
                    variant: "destructive",
                  })
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
