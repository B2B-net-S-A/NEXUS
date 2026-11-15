"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker";
import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useCreateManual, type IssueCurrency } from "@/lib/api/issued-invoices";

type BuyerMode = "client" | "other";

/**
 * Faktura z ręki (E6): klient z kartoteki albo dowolny nabywca (firma bez
 * klienta w NEXUSIE, kontraktor). Powstaje szkic z jedną pozycją — resztę
 * uzupełniasz na karcie faktury. Brakujący adres NEXUS bierze z kartoteki
 * kontrahentów po NIP-ie.
 */
export function ManualInvoiceDialog({ onClose }: { onClose: () => void }) {
  const { showToast } = useToast();
  const router = useRouter();
  const create = useCreateManual();
  const [mode, setMode] = useState<BuyerMode>("client");
  const [client, setClient] = useState<ClientRef | null>(null);
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [address, setAddress] = useState("");
  const [address2, setAddress2] = useState("");
  const [currency, setCurrency] = useState<IssueCurrency>("PLN");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (mode === "client" && !client) {
      setError("Wybierz klienta.");
      return;
    }
    if (mode === "other" && !name.trim() && !number.trim()) {
      setError("Podaj nazwę albo NIP nabywcy.");
      return;
    }
    create.mutate(
      mode === "client"
        ? { client_id: client!.id, currency }
        : {
            buyer: { name, number, address_l1: address, address_l2: address2 },
            currency,
          },
      {
        onSuccess: (card) => {
          showToast("Utworzono szkic faktury", "success");
          onClose();
          router.push(`/finance/faktury/${card.id}`);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się utworzyć szkicu.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Nowa faktura"
      description="Faktura bez zamówienia w NEXUSIE. Pozycje i daty uzupełnisz w szkicu."
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={create.isPending}>
            {create.isPending ? "Tworzenie…" : "Utwórz szkic"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <div role="radiogroup" aria-label="Nabywca" className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="manual-buyer"
              checked={mode === "client"}
              onChange={() => setMode("client")}
            />
            Klient z kartoteki
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="manual-buyer"
              checked={mode === "other"}
              onChange={() => setMode("other")}
            />
            Inny nabywca
          </label>
        </div>
        {mode === "client" ? (
          <FormField label="Klient">
            <ClientSinglePicker value={client} onChange={setClient} queryKey="issued-manual-clients" />
          </FormField>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Nazwa nabywcy" htmlFor="manual-name">
              <Input id="manual-name" value={name} onChange={(event) => setName(event.target.value)} />
            </FormField>
            <FormField label="NIP albo VAT UE" htmlFor="manual-number">
              <Input id="manual-number" value={number} onChange={(event) => setNumber(event.target.value)} />
            </FormField>
            <FormField label="Adres (ulica)" htmlFor="manual-address">
              <Input id="manual-address" value={address} onChange={(event) => setAddress(event.target.value)} />
            </FormField>
            <FormField label="Kod i miejscowość" htmlFor="manual-address2">
              <Input id="manual-address2" value={address2} onChange={(event) => setAddress2(event.target.value)} />
            </FormField>
          </div>
        )}
        <FormField label="Waluta" htmlFor="manual-currency">
          <select
            id="manual-currency"
            className="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground sm:w-40"
            value={currency}
            onChange={(event) => setCurrency(event.target.value as IssueCurrency)}
          >
            <option value="PLN">PLN</option>
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
          </select>
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
