"use client";

import { useId, useState } from "react";
import { AlertCircle, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { ScopeInfoDto, ServiceAccountConfigDto, ServiceAccountDto } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

import {
  activeKeysLabel,
  countActiveKeys,
  groupScopes,
  shortScopeLabel,
} from "./api-keys-model";
import { ServiceAccountForm } from "./ServiceAccountForm";
import { ServiceAccountKeys } from "./ServiceAccountKeys";
import { ServiceAccountWrites } from "./ServiceAccountWrites";
import type { AccountWritesState, ApiKeysActions, RevealedApiKey } from "./types";

export interface ServiceAccountCardProps {
  account: ServiceAccountDto;
  scopeCatalog: readonly ScopeInfoDto[];
  config: ServiceAccountConfigDto;
  now: Date;
  actions: ApiKeysActions;
  revealed: RevealedApiKey | null;
  onRevealed: (revealed: RevealedApiKey) => void;
  onDismissRevealed: () => void;
  writes: AccountWritesState | undefined;
  onWritesOpenChange: (open: boolean) => void;
}

export function ServiceAccountCard({
  account,
  scopeCatalog,
  config,
  now,
  actions,
  revealed,
  onRevealed,
  onDismissRevealed,
  writes,
  onWritesOpenChange,
}: ServiceAccountCardProps) {
  const headingId = useId();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"toggle" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [writesOpen, setWritesOpen] = useState(false);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const scopeGroups = groupScopes(account.scopes, scopeCatalog);
  const activeKeys = countActiveKeys(account.keys, now);

  const run = async (kind: "toggle" | "delete", action: () => Promise<unknown>, fallback: string) => {
    setError(null);
    setBusy(kind);
    try {
      await action();
    } catch (err) {
      setError(apiErrorMessage(err, fallback));
    } finally {
      setBusy(null);
    }
  };

  const setActive = async (next: boolean) => {
    if (!next) {
      const confirmed = await askConfirm({
        title: `Wyłączyć konto „${account.name}”?`,
        description:
          "Wszystkie klucze tego konta od razu przestaną działać (401). Klucze zostają — po ponownym włączeniu konta zadziałają, o ile nie wygasły i nie zostały odwołane.",
        confirmLabel: "Wyłącz konto",
        variant: "destructive",
      });
      if (!confirmed) return;
    }
    await run(
      "toggle",
      () => actions.updateAccount(account.id, { is_active: next }),
      next ? "Nie udało się włączyć konta." : "Nie udało się wyłączyć konta.",
    );
  };

  const remove = async () => {
    const confirmed = await askConfirm({
      title: `Usunąć konto „${account.name}”?`,
      description:
        "Konto i wszystkie jego klucze znikną od razu, a automatyzacje dostaną odmowę (401). Jeśli chcesz zachować ślad, kto i kiedy korzystał z konta, wyłącz je zamiast usuwać.",
      confirmLabel: "Usuń konto",
      variant: "destructive",
    });
    if (!confirmed) return;
    await run("delete", () => actions.deleteAccount(account.id), "Nie udało się usunąć konta.");
  };

  return (
    <article
      aria-labelledby={headingId}
      className={cn(
        "space-y-4 rounded-xl border border-border bg-card p-4 md:p-5",
        !account.is_active && "bg-muted/30",
      )}
    >
      {confirmDialog}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={headingId} className="text-base font-semibold text-foreground [overflow-wrap:anywhere]">
              {account.name}
            </h2>
            <Badge variant="outline" size="md" className="font-mono">
              {account.slug}
            </Badge>
            {!account.is_active ? (
              <Badge variant="warning" size="md">
                Wyłączone
              </Badge>
            ) : null}
          </div>
          {account.description ? (
            <p className="text-sm text-muted-foreground [overflow-wrap:anywhere]">{account.description}</p>
          ) : null}
          <p className={cn("text-xs", activeKeys === 0 ? "text-warning-muted-foreground" : "text-muted-foreground")}>
            {activeKeysLabel(activeKeys)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-2 text-sm text-foreground">
            <Switch
              checked={account.is_active}
              disabled={busy !== null}
              onCheckedChange={(checked) => void setActive(checked)}
              aria-label={`Konto ${account.name} aktywne`}
            />
            Aktywne
          </label>
          {!editing ? (
            <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(true)} disabled={busy !== null}>
              <Pencil className="size-4" aria-hidden />
              Edytuj
            </Button>
          ) : null}
          <Button
            type="button"
            variant="quiet"
            size="sm"
            onClick={() => void remove()}
            loading={busy === "delete"}
            disabled={busy !== null}
          >
            <Trash2 className="size-4" aria-hidden />
            Usuń konto
          </Button>
        </div>
      </header>

      {error ? (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}

      {editing ? (
        <div className="rounded-lg border border-border p-3 md:p-4">
          <ServiceAccountForm
            mode="edit"
            scopeCatalog={scopeCatalog}
            initial={{
              slug: account.slug,
              name: account.name,
              description: account.description,
              scopes: account.scopes,
            }}
            onSubmit={async (values) => {
              await actions.updateAccount(account.id, {
                name: values.name,
                description: values.description,
                scopes: values.scopes,
              });
              setEditing(false);
            }}
            onCancel={() => setEditing(false)}
          />
        </div>
      ) : (
        <section aria-label="Uprawnienia" className="space-y-1.5">
          {scopeGroups.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Brak uprawnień — klucze tego konta nie otworzą żadnej trasy.
            </p>
          ) : (
            scopeGroups.map((group) => (
              <div key={group.id} className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
                <span className="shrink-0 text-xs font-medium text-muted-foreground sm:w-44">{group.title}</span>
                <ul className="flex min-w-0 flex-wrap gap-1.5">
                  {group.scopes.map((scope) => (
                    <li
                      key={scope.value}
                      title={`${scope.label} · ${scope.value}`}
                      className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-xs text-foreground"
                    >
                      {shortScopeLabel(scope.label)}
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </section>
      )}

      <ServiceAccountKeys
        account={account}
        config={config}
        now={now}
        revealed={revealed}
        onDismissRevealed={onDismissRevealed}
        onIssueKey={async (payload) => {
          const response = await actions.issueKey(account.id, payload);
          onRevealed({ accountId: account.id, keyLabel: response.key.label, apiKey: response.api_key });
        }}
        onRevokeKey={(keyId, reason) => actions.revokeKey(account.id, keyId, reason)}
      />

      <ServiceAccountWrites
        accountName={account.name}
        keys={account.keys}
        open={writesOpen}
        onOpenChange={(open) => {
          setWritesOpen(open);
          onWritesOpenChange(open);
        }}
        state={writes}
      />
    </article>
  );
}
