"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ClientBuyer } from "@/lib/api/issued-invoices";

const EMPTY: ClientBuyer = {
  name: "",
  number: "",
  address_l1: "",
  address_l2: "",
  country: "PL",
  delivery_l1: "",
  delivery_l2: "",
  delivery_country: "",
};
const MAX_BUYERS = 10;

interface ClientBuyersEditorProps {
  label: string;
  buyers: ClientBuyer[];
  /** Ile kontraktów ma już przypisanego nabywcę (zapisuje się przy wyborze w szkicu). */
  mappedContracts: number;
  onChange: (buyers: ClientBuyer[]) => void;
}

/**
 * Nabywcy klienta, gdy nabywca zależy od kontraktu osoby (np. kilka spółek
 * klienta, nabywca z UE z adresem doręczenia w innym kraju). Pusta lista =
 * nabywcą jest klient z kartoteki. Kontrakt przypisuje się raz — wyborem
 * nabywcy w szkicu faktury; kolejne szkice biorą go same.
 */
export function ClientBuyersEditor({
  label,
  buyers,
  mappedContracts,
  onChange,
}: ClientBuyersEditorProps) {
  const update = (index: number, patch: Partial<ClientBuyer>) =>
    onChange(buyers.map((buyer, i) => (i === index ? { ...buyer, ...patch } : buyer)));

  return (
    <details className="md:col-span-4">
      <summary className="cursor-pointer text-xs font-medium text-foreground">
        Nabywcy per kontrakt{buyers.length ? `: ${buyers.length}` : ""}
        {mappedContracts ? ` · przypisane kontrakty: ${mappedContracts}` : ""}
      </summary>
      <ul className="mt-2 space-y-2">
        {buyers.map((buyer, index) => (
          <li
            key={buyer.code ?? `new-${index}`}
            className="grid gap-2 rounded-md border border-border/60 p-2 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_4rem_2.5rem]"
          >
            <Input
              aria-label={`Nazwa nabywcy ${index + 1} — ${label}`}
              placeholder="nazwa nabywcy"
              value={buyer.name}
              onChange={(e) => update(index, { name: e.target.value })}
            />
            <Input
              aria-label={`NIP albo VAT UE nabywcy ${index + 1} — ${label}`}
              placeholder="NIP albo VAT UE"
              value={buyer.number}
              onChange={(e) => update(index, { number: e.target.value })}
            />
            <Input
              aria-label={`Kraj nabywcy ${index + 1} — ${label}`}
              placeholder="PL"
              maxLength={2}
              value={buyer.country}
              onChange={(e) => update(index, { country: e.target.value.toUpperCase() })}
            />
            <Button
              size="sm"
              variant="ghost"
              aria-label={`Usuń nabywcę ${index + 1} — ${label}`}
              onClick={() => onChange(buyers.filter((_, i) => i !== index))}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </Button>
            <Input
              className="md:col-span-2"
              aria-label={`Adres nabywcy ${index + 1} — ${label}`}
              placeholder="adres: ulica, kod, miasto"
              value={buyer.address_l1}
              onChange={(e) => update(index, { address_l1: e.target.value })}
            />
            <span className="hidden md:block md:col-span-2" />
            <Input
              className="md:col-span-2"
              aria-label={`Adres doręczenia nabywcy ${index + 1} — ${label}`}
              placeholder="adres doręczenia, gdy inny (opcjonalnie)"
              value={buyer.delivery_l1}
              onChange={(e) => update(index, { delivery_l1: e.target.value })}
            />
            <Input
              aria-label={`Kraj doręczenia nabywcy ${index + 1} — ${label}`}
              placeholder="kraj"
              maxLength={2}
              value={buyer.delivery_country}
              onChange={(e) => update(index, { delivery_country: e.target.value.toUpperCase() })}
            />
          </li>
        ))}
      </ul>
      <Button
        size="sm"
        variant="outline"
        className="mt-2"
        disabled={buyers.length >= MAX_BUYERS}
        onClick={() => onChange([...buyers, { ...EMPTY }])}
      >
        <Plus className="h-4 w-4" aria-hidden />
        Dodaj nabywcę
      </Button>
    </details>
  );
}
