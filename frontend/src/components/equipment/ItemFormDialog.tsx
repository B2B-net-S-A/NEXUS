"use client";

import { useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
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
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCreateItem,
  useEquipmentModels,
  useUpdateItem,
  type EquipmentItem,
  type EquipmentItemStatus,
  type EquipmentOwnership,
  type ItemInput,
} from "@/lib/api/equipment";

import { CATEGORY_LABELS, ITEM_STATUS_LABELS } from "./equipment-format";

interface ItemFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Edycja istniejącej pozycji; brak = nowa pozycja. */
  item?: EquipmentItem | null;
}

interface FormState {
  model_id: string;
  inventory_number: string;
  serial_number: string;
  imei: string;
  iccid: string;
  phone_number: string;
  access_card_number: string;
  ownership: EquipmentOwnership;
  status: EquipmentItemStatus;
  purchase_date: string;
  location: string;
  notes: string;
}

function initial(item?: EquipmentItem | null): FormState {
  return {
    model_id: item ? String(item.model.id) : "",
    inventory_number: item?.inventory_number ?? "",
    serial_number: item?.serial_number ?? "",
    imei: item?.imei ?? "",
    iccid: item?.iccid ?? "",
    phone_number: item?.phone_number ?? "",
    access_card_number: item?.access_card_number ?? "",
    ownership: item?.ownership ?? "nasz",
    status: item?.status ?? "na_stanie",
    purchase_date: item?.purchase_date ?? "",
    location: item?.location ?? "",
    notes: item?.notes ?? "",
  };
}

const EDITABLE_STATUSES: EquipmentItemStatus[] = ["na_stanie", "serwis", "wycofany", "zgubiony"];

/**
 * „Dodaj pozycję” i edycja egzemplarza. Bez pól na PUK, klucz BitLocker i PESEL (D10).
 * Rodzic montuje okno tylko na czas edycji (``key`` = pozycja) — formularz
 * startuje z jej wartości i nie gubi wpisów przy odświeżeniu listy.
 */
export function ItemFormDialog({ open, onOpenChange, item }: ItemFormDialogProps) {
  const { showToast } = useToast();
  const models = useEquipmentModels(open);
  const create = useCreateItem();
  const update = useUpdateItem(item?.id ?? 0);
  const [form, setForm] = useState<FormState>(() => initial(item));
  const [error, setError] = useState<string | null>(null);

  const model = useMemo(
    () => models.data?.find((entry) => String(entry.id) === form.model_id) ?? null,
    [models.data, form.model_id],
  );
  const category = model?.category ?? item?.category ?? null;
  const set = (patch: Partial<FormState>) => setForm((prev) => ({ ...prev, ...patch }));
  const pending = create.isPending || update.isPending;
  const issued = item?.status === "wydany";

  const submit = () => {
    if (!form.model_id) {
      setError("Wybierz model z cennika.");
      return;
    }
    const payload: ItemInput = {
      model_id: Number(form.model_id),
      inventory_number: form.inventory_number.trim() || null,
      serial_number: form.serial_number.trim() || null,
      imei: form.imei.trim() || null,
      iccid: form.iccid.trim() || null,
      phone_number: form.phone_number.trim() || null,
      access_card_number: form.access_card_number.trim() || null,
      ownership: form.ownership,
      purchase_date: form.purchase_date || null,
      location: form.location.trim() || null,
      notes: form.notes.trim() || null,
      ...(issued ? {} : { status: form.status }),
    };
    setError(null);
    const done = {
      onSuccess: () => {
        showToast(item ? "Zapisano zmiany" : "Pozycja dodana", "success");
        onOpenChange(false);
      },
      onError: (err: unknown) => setError(apiErrorMessage(err, "Nie udało się zapisać pozycji.")),
    };
    if (item) update.mutate(payload, done);
    else create.mutate(payload as ItemInput & { model_id: number }, done);
  };

  const field = (key: keyof FormState, label: string, placeholder?: string) => (
    <FormField label={label} htmlFor={`eq-item-${key}`}>
      <Input
        id={`eq-item-${key}`}
        value={form[key]}
        placeholder={placeholder}
        onChange={(event) => set({ [key]: event.target.value } as Partial<FormState>)}
      />
    </FormField>
  );

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={item ? "Edytuj pozycję" : "Dodaj pozycję"}
      description="Jedna pozycja to jeden egzemplarz. Wartość pochodzi z cennika modelu."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending}>
            {pending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Model z cennika" htmlFor="eq-item-model" required className="sm:col-span-2">
          <Select value={form.model_id} onValueChange={(value) => set({ model_id: value })}>
            <SelectTrigger id="eq-item-model">
              <SelectValue
                placeholder={models.isLoading ? "Wczytywanie cennika…" : "Wybierz model"}
              />
            </SelectTrigger>
            <SelectContent>
              {(models.data ?? [])
                .filter((entry) => entry.is_active || String(entry.id) === form.model_id)
                .map((entry) => (
                  <SelectItem key={entry.id} value={String(entry.id)}>
                    {CATEGORY_LABELS[entry.category]} · {entry.name}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </FormField>
        {field("inventory_number", "Numer ewidencyjny", "np. 221, T-061")}
        {category === "karta_sim" ? (
          <>
            {field("phone_number", "Numer telefonu", "500 000 000")}
            {field("iccid", "ICCID")}
          </>
        ) : category === "karta_dostepu" ? (
          field("access_card_number", "Numer karty")
        ) : category === "telefon" ? (
          <>
            {field("imei", "IMEI")}
            {field("serial_number", "Numer seryjny")}
          </>
        ) : (
          field("serial_number", "Numer seryjny / Service tag")
        )}
        <FormField label="Właściciel" htmlFor="eq-item-ownership">
          <Select
            value={form.ownership}
            onValueChange={(value) => set({ ownership: value as EquipmentOwnership })}
          >
            <SelectTrigger id="eq-item-ownership">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="nasz">Nasz</SelectItem>
              <SelectItem value="klienta">Klienta</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label="Stan"
          htmlFor="eq-item-status"
          description={issued ? "Pozycja jest wydana — stan zmieni zwrot." : undefined}
        >
          <Select
            value={form.status}
            disabled={issued}
            onValueChange={(value) => set({ status: value as EquipmentItemStatus })}
          >
            <SelectTrigger id="eq-item-status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(issued ? (["wydany"] as EquipmentItemStatus[]) : EDITABLE_STATUSES).map(
                (status) => (
                  <SelectItem key={status} value={status}>
                    {ITEM_STATUS_LABELS[status]}
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Data zakupu" htmlFor="eq-item-purchase">
          <Input
            id="eq-item-purchase"
            type="date"
            value={form.purchase_date}
            onChange={(event) => set({ purchase_date: event.target.value })}
          />
        </FormField>
        {field("location", "Gdzie leży", "np. szafka B")}
        <FormField
          label="Notatka"
          htmlFor="eq-item-notes"
          className="sm:col-span-2"
          description="Bez kodów PUK, kluczy BitLocker, PESEL-i i prywatnych e-maili — NEXUS ich nie przyjmie."
        >
          <Textarea
            id="eq-item-notes"
            rows={2}
            value={form.notes}
            onChange={(event) => set({ notes: event.target.value })}
          />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
