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
import { useCreateAdvance, type IssueCurrency } from "@/lib/api/issued-invoices";
import { warsawToday } from "@/lib/warsaw-date";

/** Faktura zaliczkowa (minimalnie): klient, waluta, data otrzymania zaliczki → szkic. */
export function AdvanceDialog({ onClose }: { onClose: () => void }) {
  const { showToast } = useToast();
  const router = useRouter();
  const create = useCreateAdvance();
  const [client, setClient] = useState<ClientRef | null>(null);
  const [currency, setCurrency] = useState<IssueCurrency>("PLN");
  const [receivedOn, setReceivedOn] = useState(warsawToday());
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!client) {
      setError("Wybierz klienta.");
      return;
    }
    create.mutate(
      { client_id: client.id, currency, received_on: receivedOn },
      {
        onSuccess: (card) => {
          showToast("Utworzono szkic faktury zaliczkowej", "success");
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
      title="Faktura zaliczkowa"
      description="Zaliczka na pełną wartość zamówienia. Pozycje i kwotę uzupełnisz w szkicu."
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
        <FormField label="Klient">
          <ClientSinglePicker value={client} onChange={setClient} queryKey="issued-advance-clients" />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Waluta" htmlFor="advance-currency">
            <select
              id="advance-currency"
              className="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground"
              value={currency}
              onChange={(event) => setCurrency(event.target.value as IssueCurrency)}
            >
              <option value="PLN">PLN</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
            </select>
          </FormField>
          <FormField label="Data otrzymania zaliczki" htmlFor="advance-received">
            <Input
              id="advance-received"
              type="date"
              value={receivedOn}
              max={warsawToday()}
              onChange={(event) => setReceivedOn(event.target.value)}
            />
          </FormField>
        </div>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
