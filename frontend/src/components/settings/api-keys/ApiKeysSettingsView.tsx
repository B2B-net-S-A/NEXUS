"use client";

// Ustawienia → „Klucze API” (14.10.2026): konta serwisowe i ich klucze
// `X-API-Key` dla automatyzacji wołających API integracyjne v1
// (`/api/integrations/v1`, rozliczenia klientów). Komponent jest czysto
// prezentacyjny — dane i zapisy przychodzą z propsów (`app/settings/api-keys`
// z react-query, harness `/preview/api-keys` z danymi fikcyjnymi), więc ten
// sam ekran da się obejrzeć bez sieci.

import { useState } from "react";
import { AlertTriangle, KeyRound, Loader2, Plus } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";

import { ServiceAccountCard } from "./ServiceAccountCard";
import { ServiceAccountForm } from "./ServiceAccountForm";
import type { AccountWritesState, ApiKeysActions, ApiKeysLoad, RevealedApiKey } from "./types";

export interface ApiKeysSettingsViewProps {
  load: ApiKeysLoad;
  actions: ApiKeysActions;
  /** „Ostatnie zapisy” per konto — klucz to `account.id`. */
  writes: Readonly<Record<number, AccountWritesState | undefined>>;
  onWritesOpenChange: (accountId: number, open: boolean) => void;
  /** Tylko dla harnessu: klucz pokazany od wejścia. */
  initialRevealedKey?: RevealedApiKey | null;
  /** Tylko dla harnessu: formularz nowego konta otwarty od wejścia. */
  initialCreating?: boolean;
  /** Zegar do statusów i „ostatniego użycia”; domyślnie teraz. */
  now?: Date;
}

const WRAP = "container mx-auto max-w-5xl space-y-6 md:px-4 md:py-8";

export function ApiKeysSettingsView({
  load,
  actions,
  writes,
  onWritesOpenChange,
  initialRevealedKey = null,
  initialCreating = false,
  now: nowProp,
}: ApiKeysSettingsViewProps) {
  const [creating, setCreating] = useState(initialCreating);
  const [revealed, setRevealed] = useState<RevealedApiKey | null>(initialRevealedKey);
  const now = nowProp ?? new Date();

  return (
    <div className={WRAP}>
      <header className="space-y-2">
        <h1 className="text-2xl font-bold text-foreground">Klucze API</h1>
        <p className="text-sm text-muted-foreground">
          Klucze dla automatyzacji (n8n, Power Automate, Make, skrypty), które wołają API integracyjne{" "}
          <code className="font-mono text-foreground">/api/integrations/v1</code> — klienci, kontrakty, zamówienia,
          zużycie MD, finanse i faktury. Klucz wysyła się w nagłówku{" "}
          <code className="font-mono text-foreground">X-API-Key</code> i widać go tylko raz, przy wydaniu.
        </p>
        <p className="text-xs text-muted-foreground">Dokumentacja: docs/api/integracje-v1.md w repo</p>
      </header>

      {load.status === "loading" ? (
        <p className="flex min-h-[200px] items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin" aria-hidden />
          Pobieram konta serwisowe…
        </p>
      ) : load.status === "error" ? (
        <QueryStateNotice
          state={load.forbidden ? "forbidden" : "error"}
          description={load.message}
          onRetry={load.onRetry}
        />
      ) : (
        <>
          {!load.config.enabled ? (
            <p
              role="status"
              className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>
                Klucze API są wyłączone na serwerze — żaden klucz nie zadziała, dopóki administrator systemu ich nie
                włączy. Konta i klucze można przygotować już teraz.
              </span>
            </p>
          ) : null}

          {creating ? (
            <section aria-label="Nowe konto serwisowe" className="rounded-xl border border-border bg-card p-4 md:p-5">
              <h2 className="mb-4 text-base font-semibold text-foreground">Nowe konto serwisowe</h2>
              <ServiceAccountForm
                mode="create"
                scopeCatalog={load.scopes}
                onSubmit={async (values) => {
                  await actions.createAccount({
                    slug: values.slug,
                    name: values.name,
                    description: values.description,
                    scopes: values.scopes,
                  });
                  setCreating(false);
                }}
                onCancel={() => setCreating(false)}
              />
            </section>
          ) : load.accounts.length > 0 ? (
            <div>
              <Button type="button" onClick={() => setCreating(true)}>
                <Plus className="size-4" aria-hidden />
                Nowe konto
              </Button>
            </div>
          ) : null}

          {load.accounts.length === 0 ? (
            !creating ? (
              <EmptyState
                icon={KeyRound}
                title="Nie ma jeszcze żadnego konta serwisowego"
                description="Załóż konto dla automatyzacji, nadaj mu uprawnienia i wydaj klucz."
                action={
                  <Button type="button" onClick={() => setCreating(true)}>
                    <Plus className="size-4" aria-hidden />
                    Nowe konto
                  </Button>
                }
                className="rounded-xl border border-dashed border-border"
              />
            ) : null
          ) : (
            <div className="space-y-4">
              {load.accounts.map((account) => (
                <ServiceAccountCard
                  key={account.id}
                  account={account}
                  scopeCatalog={load.scopes}
                  config={load.config}
                  now={now}
                  actions={actions}
                  revealed={revealed?.accountId === account.id ? revealed : null}
                  onRevealed={setRevealed}
                  onDismissRevealed={() => setRevealed(null)}
                  writes={writes[account.id]}
                  onWritesOpenChange={(open) => onWritesOpenChange(account.id, open)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
