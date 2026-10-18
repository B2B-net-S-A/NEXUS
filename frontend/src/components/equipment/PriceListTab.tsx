"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCreateModel,
  useEquipmentModels,
  useUpdateModel,
  type EquipmentCategory,
  type EquipmentModel,
} from "@/lib/api/equipment";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  formatPln,
  isNoValueCategory,
} from "./equipment-format";

interface ModelForm {
  category: EquipmentCategory;
  name: string;
  manufacturer: string;
  price: string;
  is_active: boolean;
}

function ModelDialog({
  model,
  onClose,
}: {
  model: EquipmentModel | null;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const create = useCreateModel();
  const update = useUpdateModel();
  const [form, setForm] = useState<ModelForm>({
    category: model?.category ?? "laptop",
    name: model?.name ?? "",
    manufacturer: model?.manufacturer ?? "",
    price: model?.price_pln ?? "",
    is_active: model?.is_active ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const noValue = isNoValueCategory(form.category);
  const pending = create.isPending || update.isPending;

  const submit = () => {
    const price = form.price.trim().replace(",", ".");
    if (price && !(Number(price) >= 0)) {
      setError("Cena musi być liczbą nie mniejszą niż zero.");
      return;
    }
    const payload = {
      category: form.category,
      name: form.name.trim(),
      manufacturer: form.manufacturer.trim() || null,
      price_pln: noValue || !price ? null : price,
      is_active: form.is_active,
    };
    setError(null);
    const done = {
      onSuccess: () => {
        showToast(model ? "Cennik zapisany" : "Model dodany", "success");
        onClose();
      },
      onError: (err: unknown) => setError(apiErrorMessage(err, "Nie udało się zapisać modelu.")),
    };
    if (model) update.mutate({ id: model.id, ...payload }, done);
    else create.mutate(payload, done);
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={model ? "Edytuj model" : "Dodaj model do cennika"}
      description="Zmiana ceny nie zmienia protokołów — wartości są w nich zamrożone."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending || !form.name.trim()}>
            {pending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Kategoria" htmlFor="eq-model-category">
          <Select
            value={form.category}
            disabled={Boolean(model)}
            onValueChange={(value) => setForm({ ...form, category: value as EquipmentCategory })}
          >
            <SelectTrigger id="eq-model-category">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORY_ORDER.map((category) => (
                <SelectItem key={category} value={category}>
                  {CATEGORY_LABELS[category]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Model" htmlFor="eq-model-name" required>
          <Input
            id="eq-model-name"
            placeholder="np. Dell Vostro 3530, 16 GB"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </FormField>
        <FormField label="Producent" htmlFor="eq-model-manufacturer">
          <Input
            id="eq-model-manufacturer"
            value={form.manufacturer}
            onChange={(event) => setForm({ ...form, manufacturer: event.target.value })}
          />
        </FormField>
        <FormField
          label="Cena (zł)"
          htmlFor="eq-model-price"
          description={noValue ? "Karta SIM i karta dostępu są w protokole bez wartości." : undefined}
        >
          <Input
            id="eq-model-price"
            inputMode="decimal"
            disabled={noValue}
            value={noValue ? "" : form.price}
            onChange={(event) => setForm({ ...form, price: event.target.value })}
          />
        </FormField>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <Switch
            checked={form.is_active}
            onCheckedChange={(checked) => setForm({ ...form, is_active: checked })}
          />
          W użyciu (nieaktywny model nie pojawia się przy dodawaniu pozycji)
        </label>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/** Cennik: model w kategorii z ceną, z której liczy się wartość w protokole (D5). */
export function PriceListTab() {
  const models = useEquipmentModels();
  const [editing, setEditing] = useState<EquipmentModel | "new" | null>(null);
  const rows = models.data ?? [];
  const state = resolveViewState({
    isLoading: models.isLoading,
    error: models.error,
    isSuccess: models.isSuccess,
    isEmpty: rows.length === 0,
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center">
        <p className="text-sm text-muted-foreground">
          Wartość pozycji w protokole pochodzi z ceny modelu.
        </p>
        <Button className="ml-auto" variant="outline" onClick={() => setEditing("new")}>
          <Plus className="h-4 w-4" aria-hidden />
          Dodaj model
        </Button>
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie cennika…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => models.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Cennik jest pusty. Dodaj pierwszy model albo zaimportuj pliki recepcji.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[720px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Kategoria</TableHead>
                <TableHead className={CALM_HEAD}>Model</TableHead>
                <TableHead className={CALM_HEAD}>Producent</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Cena</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Pozycji</TableHead>
                <TableHead className={CALM_HEAD} />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((model) => (
                <TableRow key={model.id} className={`${CALM_ROW} h-[44px]`}>
                  <TableCell>{CATEGORY_LABELS[model.category]}</TableCell>
                  <TableCell className={model.is_active ? "" : "text-muted-foreground"}>
                    {model.name}
                    {model.is_active ? null : " (nieużywany)"}
                  </TableCell>
                  <TableCell>
                    {model.manufacturer ?? <span className={CALM_EMPTY}>—</span>}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {isNoValueCategory(model.category) ? "bez wartości" : formatPln(model.price_pln)}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>{model.items ?? 0}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => setEditing(model)}>
                      Edytuj
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing ? (
        <ModelDialog
          key={editing === "new" ? "new" : editing.id}
          model={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
    </div>
  );
}
