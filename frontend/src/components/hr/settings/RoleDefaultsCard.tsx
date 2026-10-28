"use client";

import { useState } from "react";
import { ArrowDown, ArrowUp, Pencil, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { ROLE_LABELS } from "@/components/settings/admin/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDeleteRoleDefault,
  useReorderRoleDefaults,
  useRoleDefaults,
  useSaveRoleDefault,
  type RoleDefault,
} from "@/lib/api/hr-time";
import { resolveViewState } from "@/lib/view-state";

import { moveItem } from "@/components/hr/time/TemplatesDialog";

/**
 * Role NEXUSA, dla których Kadry ustawiają domyślny opis. Bez `user`
 * (wycofany podgląd); wycofane role sprzed 0411 to tylko aliasy rekrutera.
 */
export const ROLE_DEFAULT_ROLES = [
  "employee",
  "recruiter",
  "delivery_lead",
  "head_of_recruitment",
  "talent_community_manager",
  "finance",
  "trainee",
  "automation",
  "admin",
] as const;

const ALL_ROLES = "__all__";

export function roleLabel(role: string | null): string {
  if (role == null) return "Wszystkie role";
  return ROLE_LABELS[role] ?? role;
}

interface Draft {
  id: number | null;
  label: string;
  role: string;
  project: string;
  description: string;
  active: boolean;
}

const EMPTY: Draft = {
  id: null,
  label: "",
  role: ALL_ROLES,
  project: "",
  description: "",
  active: true,
};

/**
 * Ustawienia → Kadry → „Domyślne opisy” (jak `RoleDefaultsManager` Compassa):
 * rola → etykieta, projekt, opis, aktywny, kolejność. „Wypełnij miesiąc”
 * bierze najbardziej szczegółowy aktywny opis: rola+projekt > rola > projekt
 * > wszystkie role (`time_fill.resolve_role_default`), przy remisie — wyższy
 * na liście.
 */
export function RoleDefaultsCard() {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const defaults = useRoleDefaults();
  const save = useSaveRoleDefault();
  const remove = useDeleteRoleDefault();
  const reorder = useReorderRoleDefaults();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const items = defaults.data ?? [];
  const state = resolveViewState({
    isLoading: defaults.isLoading,
    isError: defaults.isError,
    error: defaults.error,
    isSuccess: defaults.isSuccess,
    isEmpty: items.length === 0,
  });
  const busy = save.isPending || remove.isPending || reorder.isPending;

  const edit = (item: RoleDefault) => {
    setError(null);
    setDraft({
      id: item.id,
      label: item.label,
      role: item.applies_to_role ?? ALL_ROLES,
      project: item.project ?? "",
      description: item.default_description,
      active: item.is_active,
    });
  };

  const submit = async () => {
    setError(null);
    const label = draft.label.trim();
    const description = draft.description.trim();
    if (!label || !description) {
      setError("Podaj etykietę i opis.");
      return;
    }
    try {
      await save.mutateAsync({
        id: draft.id ?? undefined,
        label,
        default_description: description,
        applies_to_role: draft.role === ALL_ROLES ? null : draft.role,
        project: draft.project.trim() || null,
        is_active: draft.active,
        ...(draft.id == null ? { sort_order: items.length } : {}),
      });
      showToast(draft.id == null ? "Domyślny opis dodany" : "Domyślny opis zapisany", "success");
      setDraft(EMPTY);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać opisu."));
    }
  };

  const toggle = async (item: RoleDefault, active: boolean) => {
    try {
      await save.mutateAsync({ id: item.id, is_active: active });
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się zmienić opisu."), "error");
    }
  };

  const drop = async (item: RoleDefault) => {
    const ok = await askConfirm({
      title: `Usunąć opis „${item.label}”?`,
      description:
        "„Wypełnij miesiąc” przestanie go podpowiadać. Wpisy, które już z niego powstały, zostają. Żeby tylko wstrzymać opis, wyłącz go przełącznikiem.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await remove.mutateAsync(item.id);
      if (draft.id === item.id) setDraft(EMPTY);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się usunąć opisu."), "error");
    }
  };

  const move = async (index: number, delta: -1 | 1) => {
    try {
      await reorder.mutateAsync(moveItem(items, index, delta));
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się zmienić kolejności."), "error");
    }
  };

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-base font-semibold text-foreground">Domyślne opisy godzin</h2>
        <p className="text-sm text-muted-foreground">
          Opis, który „Wypełnij miesiąc” wpisuje osobie bez własnego szablonu. Wygrywa
          najbardziej szczegółowy: rola z projektem, rola, projekt, wszystkie role; przy
          remisie — wyżej na liście.
        </p>
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">
          Brak domyślnych opisów — „Wypełnij miesiąc” wpisuje „Realizacja usług zgodnie z umową”
          (B2B i zlecenie) albo „Praca standardowa” (umowa o pracę).
        </p>
      ) : state !== "ready" ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => defaults.refetch()}
        />
      ) : (
        <ul className="divide-y divide-border/60">
          {items.map((item, index) => (
            <li key={item.id} className="flex items-start gap-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">
                  {item.label}
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {roleLabel(item.applies_to_role)}
                    {item.project ? ` · ${item.project}` : ""}
                  </span>
                </p>
                <p className="line-clamp-2 text-xs text-muted-foreground">
                  {item.default_description}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                <Switch
                  checked={item.is_active}
                  disabled={busy}
                  aria-label={`Aktywny: ${item.label}`}
                  onCheckedChange={(next) => void toggle(item, next)}
                  className="mr-1"
                />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Przesuń wyżej: ${item.label}`}
                  disabled={busy || index === 0}
                  onClick={() => void move(index, -1)}
                >
                  <ArrowUp className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Przesuń niżej: ${item.label}`}
                  disabled={busy || index === items.length - 1}
                  onClick={() => void move(index, 1)}
                >
                  <ArrowDown className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Edytuj: ${item.label}`}
                  disabled={busy}
                  onClick={() => edit(item)}
                >
                  <Pencil className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  variant="quiet"
                  size="icon-sm"
                  aria-label={`Usuń: ${item.label}`}
                  disabled={busy}
                  onClick={() => void drop(item)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <fieldset className="space-y-3 rounded-lg border border-border/60 p-3">
        <legend className="px-1 text-xs font-semibold text-muted-foreground">
          {draft.id == null ? "Nowy opis" : "Edycja opisu"}
        </legend>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Etykieta" htmlFor="hr-role-default-label">
            <Input
              id="hr-role-default-label"
              value={draft.label}
              maxLength={120}
              placeholder="np. Rekruter — praca standardowa"
              onChange={(event) => setDraft({ ...draft, label: event.target.value })}
            />
          </FormField>
          <FormField label="Rola" htmlFor="hr-role-default-role">
            <Select value={draft.role} onValueChange={(role) => setDraft({ ...draft, role })}>
              <SelectTrigger id="hr-role-default-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_ROLES}>Wszystkie role</SelectItem>
                {ROLE_DEFAULT_ROLES.map((role) => (
                  <SelectItem key={role} value={role}>
                    {roleLabel(role)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField label="Projekt" htmlFor="hr-role-default-project" description="Opcjonalnie.">
            <Input
              id="hr-role-default-project"
              value={draft.project}
              maxLength={200}
              onChange={(event) => setDraft({ ...draft, project: event.target.value })}
            />
          </FormField>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <Switch
              checked={draft.active}
              aria-label="Aktywny"
              onCheckedChange={(active) => setDraft({ ...draft, active })}
            />
            Aktywny
          </label>
          <FormField label="Opis" htmlFor="hr-role-default-description" className="sm:col-span-2">
            <Textarea
              id="hr-role-default-description"
              rows={2}
              maxLength={2000}
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </FormField>
        </div>
        <div className="flex justify-end gap-2">
          {draft.id != null ? (
            <Button variant="ghost" size="sm" onClick={() => setDraft(EMPTY)}>
              Anuluj edycję
            </Button>
          ) : null}
          <Button size="sm" onClick={() => void submit()} disabled={busy}>
            {draft.id == null ? "Dodaj opis" : "Zapisz zmiany"}
          </Button>
        </div>
      </fieldset>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </Card>
  );
}
