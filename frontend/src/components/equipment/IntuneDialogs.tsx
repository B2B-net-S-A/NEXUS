"use client";

import { useDeferredValue, useState } from "react";
import { Search } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useEquipmentItems } from "@/lib/api/equipment";
import {
  useLinkIntuneDevice,
  useResolveIntuneDevice,
  type IntuneDiscrepancy,
  type IntuneResolution,
} from "@/lib/api/equipment-intune";

import { CATEGORY_LABELS, ITEM_STATUS_LABELS, itemIdentifier } from "./equipment-format";
import { deviceLabel } from "./intune-format";

export type ResolveTarget = { row: IntuneDiscrepancy; resolution: IntuneResolution };

export function ResolveDialog({ target, onClose }: { target: ResolveTarget; onClose: () => void }) {
  const { showToast } = useToast();
  const resolve = useResolveIntuneDevice();
  const [note, setNote] = useState("");
  const explained = target.resolution === "wyjasnione";
  const deviceId = target.row.device?.id;

  const submit = () => {
    if (!deviceId) return;
    resolve.mutate(
      { deviceId, resolution: target.resolution, note: note.trim() || null },
      {
        onSuccess: () => {
          showToast(explained ? "Oznaczone jako wyjaśnione" : "Urządzenie pominięte", "success");
          onClose();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={explained ? "Rozjazd wyjaśniony" : "Pomiń urządzenie"}
      description={
        explained
          ? "Rozjazd zniknie z listy. Notatka zostaje przy urządzeniu."
          : "Urządzenie nie będzie pokazywane jako rozjazd (np. sprzęt testowy albo klienta)."
      }
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={resolve.isPending}>
            {resolve.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <p className="text-sm font-medium">{deviceLabel(target.row)}</p>
        <label className="block space-y-1 text-sm">
          <span className="text-xs text-muted-foreground">Notatka (opcjonalnie)</span>
          <Textarea
            value={note}
            maxLength={500}
            rows={3}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Np. laptop oddany do serwisu, wpis w Intune zostanie usunięty."
          />
        </label>
      </div>
    </AppModal>
  );
}

export function LinkDialog({ row, onClose }: { row: IntuneDiscrepancy; onClose: () => void }) {
  const { showToast } = useToast();
  const link = useLinkIntuneDevice();
  // Podpowiedź „przypisz do …”: zaczynamy od osoby, która używa urządzenia.
  const [query, setQuery] = useState(row.device?.user?.name ?? "");
  const deferred = useDeferredValue(query.trim());
  const enabled = deferred.length >= 2;
  const items = useEquipmentItems({ q: deferred }, enabled);
  const found = items.data?.items.slice(0, 8) ?? [];
  const deviceId = row.device?.id;

  const choose = (itemId: number) => {
    if (!deviceId) return;
    link.mutate(
      { deviceId, itemId },
      {
        onSuccess: () => {
          showToast("Powiązano z egzemplarzem", "success");
          onClose();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się powiązać."), "error"),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Powiąż z egzemplarzem"
      description="Wybierz pozycję z rejestru, która jest tym urządzeniem (np. gdy S/N w rejestrze ma literówkę)."
      size="lg"
    >
      <div className="space-y-3">
        <p className="text-sm font-medium">{deviceLabel(row)}</p>
        <div className="relative">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj pozycji w rejestrze"
            placeholder="S/N, numer ewidencyjny, model albo osoba…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9 pl-8"
          />
        </div>
        {!enabled ? (
          <p className="text-sm text-muted-foreground">Wpisz co najmniej 2 znaki.</p>
        ) : items.isLoading ? (
          <p className="text-sm text-muted-foreground">Szukanie…</p>
        ) : items.isError ? (
          <p className="text-sm text-destructive">
            {apiErrorMessage(items.error, "Nie udało się przeszukać rejestru.")}
          </p>
        ) : found.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nic nie pasuje.</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {found.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate">
                    {CATEGORY_LABELS[item.category]} {item.model.name}
                    {item.inventory_number ? ` (${item.inventory_number})` : ""}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {itemIdentifier(item)} · {item.holder?.name ?? ITEM_STATUS_LABELS[item.status].toLowerCase()}
                  </span>
                </span>
                <Button size="sm" variant="outline" onClick={() => choose(item.id)} disabled={link.isPending}>
                  Powiąż
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppModal>
  );
}
