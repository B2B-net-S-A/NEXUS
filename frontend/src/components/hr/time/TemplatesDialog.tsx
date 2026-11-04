"use client";

import { useState } from "react";
import { ArrowDown, ArrowUp, Pencil, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDeleteTemplate,
  useMyTemplates,
  useReorderTemplates,
  useSaveTemplate,
  type TimesheetTemplate,
} from "@/lib/api/hr-time";
import { resolveViewState } from "@/lib/view-state";

export interface TemplatesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Draft {
  id: number | null;
  name: string;
  project: string;
  description: string;
}

const EMPTY: Draft = { id: null, name: "", project: "", description: "" };

/** Przesunięcie pozycji o jedno miejsce (bez zmiany tablicy wejściowej). */
export function moveItem<T>(items: readonly T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return [...items];
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/**
 * „Moje szablony opisów” (jak „snippety” Compassa): krótkie opisy, które
 * wstawia się jednym kliknięciem w oknie wpisu i w „Wypełnij miesiąc”.
 * Dodaj, edytuj, usuń, kolejność strzałkami. Szablony są tylko osoby.
 */
export function TemplatesDialog({ open, onOpenChange }: TemplatesDialogProps) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const templates = useMyTemplates(open);
  const save = useSaveTemplate();
  const remove = useDeleteTemplate();
  const reorder = useReorderTemplates();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const items = templates.data?.items ?? [];
  const state = resolveViewState({
    isLoading: templates.isLoading,
    isError: templates.isError,
    error: templates.error,
    isSuccess: templates.isSuccess,
    isEmpty: items.length === 0,
  });
  const busy = save.isPending || remove.isPending || reorder.isPending;

  const edit = (item: TimesheetTemplate) => {
    setError(null);
    setDraft({
      id: item.id,
      name: item.name,
      project: item.project ?? "",
      description: item.description,
    });
  };

  const submit = async () => {
    setError(null);
    const name = draft.name.trim();
    const description = draft.description.trim();
    if (!name || !description) {
      setError("Podaj nazwę i opis szablonu.");
      return;
    }
    try {
      await save.mutateAsync({
        id: draft.id ?? undefined,
        name,
        description,
        project: draft.project.trim() || null,
        // Nowy szablon na końcu listy.
        ...(draft.id == null ? { sort_order: items.length } : {}),
      });
      setDraft(EMPTY);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać szablonu."));
    }
  };

  const drop = async (item: TimesheetTemplate) => {
    const ok = await askConfirm({
      title: `Usunąć szablon „${item.name}”?`,
      description: "Wpisy, w których go użyto, zostają bez zmian.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    setError(null);
    try {
      await remove.mutateAsync(item.id);
      if (draft.id === item.id) setDraft(EMPTY);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się usunąć szablonu."));
    }
  };

  const move = async (index: number, delta: -1 | 1) => {
    setError(null);
    try {
      await reorder.mutateAsync(moveItem(items, index, delta));
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zmienić kolejności."));
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Moje szablony opisów"
      description="Opisy, których używasz najczęściej — wstawisz je jednym kliknięciem przy wpisie dnia i w „Wypełnij miesiąc”."
      footer={
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Zamknij
        </Button>
      }
    >
      <div className="space-y-4">
        {state === "loading" ? (
          <p className="text-sm text-muted-foreground">Wczytywanie szablonów…</p>
        ) : state === "empty" ? (
          <p className="text-sm text-muted-foreground">
            Nie masz jeszcze szablonów. Dodaj pierwszy poniżej.
          </p>
        ) : state !== "ready" ? (
          <QueryStateNotice
            state={state === "forbidden" || state === "not_found" ? state : "error"}
            onRetry={() => templates.refetch()}
          />
        ) : (
          <ul className="divide-y divide-border/60 rounded-lg border border-border/60">
            {items.map((item, index) => (
              <li key={item.id} className="flex items-start gap-2 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground">
                    {item.name}
                    {item.project ? (
                      <span className="ml-2 text-xs font-normal text-muted-foreground">
                        {item.project}
                      </span>
                    ) : null}
                  </p>
                  <p className="line-clamp-2 text-xs text-muted-foreground">{item.description}</p>
                </div>
                <div className="flex shrink-0 items-center">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Przesuń wyżej: ${item.name}`}
                    disabled={busy || index === 0}
                    onClick={() => void move(index, -1)}
                  >
                    <ArrowUp className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Przesuń niżej: ${item.name}`}
                    disabled={busy || index === items.length - 1}
                    onClick={() => void move(index, 1)}
                  >
                    <ArrowDown className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Edytuj: ${item.name}`}
                    disabled={busy}
                    onClick={() => edit(item)}
                  >
                    <Pencil className="h-4 w-4" aria-hidden />
                  </Button>
                  <Button
                    variant="quiet"
                    size="icon-sm"
                    aria-label={`Usuń: ${item.name}`}
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
            {draft.id == null ? "Nowy szablon" : "Edycja szablonu"}
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Nazwa" htmlFor="time-template-name">
              <Input
                id="time-template-name"
                value={draft.name}
                maxLength={80}
                placeholder="np. Code review"
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </FormField>
            <FormField label="Projekt" htmlFor="time-template-project" description="Opcjonalnie.">
              <Input
                id="time-template-project"
                value={draft.project}
                maxLength={200}
                onChange={(event) => setDraft({ ...draft, project: event.target.value })}
              />
            </FormField>
            <FormField label="Opis" htmlFor="time-template-description" className="sm:col-span-2">
              <Textarea
                id="time-template-description"
                rows={2}
                value={draft.description}
                maxLength={2000}
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
              {draft.id == null ? "Dodaj szablon" : "Zapisz zmiany"}
            </Button>
          </div>
        </fieldset>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      {confirmDialog}
    </AppModal>
  );
}
