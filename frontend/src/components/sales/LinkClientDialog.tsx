"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientOptions, useLinkClient, type Ref } from "@/lib/api/sales";

interface LinkClientDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  company: Ref;
  current: Ref | null;
}

/**
 * Powiązanie firmy sprzedaży z klientem NEXUSA (decyzja Artura 27.10.2026):
 * tylko wskazanie, że to ta sama firma. Klienta, DL i rekrutacje zakłada
 * Delivery jak dziś — stąd nie powstaje nic poza powiązaniem.
 */
export function LinkClientDialog({ open, onOpenChange, company, current }: LinkClientDialogProps) {
  const [q, setQ] = useState(company.name);
  const [debounced, setDebounced] = useState(company.name);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(q), 250);
    return () => window.clearTimeout(timer);
  }, [q]);
  const options = useClientOptions(debounced);
  const link = useLinkClient(company.id);
  const { showError, showSuccess } = useToast();

  const choose = (clientId: number | null) =>
    link.mutate(clientId, {
      onSuccess: (linked) => {
        showSuccess(linked ? `Powiązano z klientem ${linked.name}.` : "Zdjęto powiązanie z klientem.");
        onOpenChange(false);
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić powiązania.")),
    });

  const items = options.data ?? [];
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Powiąż z klientem NEXUSA"
      description="Wskaż klienta, który jest tą samą firmą. Rekrutacje i Delivery Leada ustawia Delivery."
      size="md"
      footer={
        <>
          {current && (
            <Button variant="quiet" onClick={() => choose(null)} loading={link.isPending}>
              Zdejmij powiązanie
            </Button>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </>
      }
    >
      <Input
        aria-label="Szukaj klienta"
        value={q}
        placeholder="Nazwa klienta…"
        onChange={(event) => setQ(event.target.value)}
        autoFocus
      />
      <ul className="mt-2 max-h-64 overflow-y-auto rounded-md border border-border" aria-label="Klienci">
        {debounced.trim().length < 2 ? (
          <li className="px-3 py-2 text-sm text-muted-foreground">Wpisz co najmniej 2 litery.</li>
        ) : options.isError ? (
          <li className="px-3 py-2 text-sm text-destructive">
            Nie udało się wyszukać klientów. Spróbuj jeszcze raz.
          </li>
        ) : options.isSuccess && items.length === 0 ? (
          <li className="px-3 py-2 text-sm text-muted-foreground">Nie ma takiego klienta w NEXUSIE.</li>
        ) : (
          items.map((client) => (
            <li key={client.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-muted"
                onClick={() => choose(client.id)}
                disabled={link.isPending}
              >
                <span>{client.name}</span>
                {current?.id === client.id && <span className="text-xs text-muted-foreground">powiązany</span>}
              </button>
            </li>
          ))
        )}
      </ul>
    </AppModal>
  );
}
