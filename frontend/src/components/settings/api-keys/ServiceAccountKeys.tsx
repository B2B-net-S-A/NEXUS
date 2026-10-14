"use client";

import { Fragment, useId, useState, type FormEvent } from "react";
import { AlertCircle, KeyRound, Plus } from "lucide-react";

import { SecretRevealCard } from "@/components/settings/SecretRevealCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type {
  ServiceAccountConfigDto,
  ServiceAccountDto,
  ServiceAccountKeyCreatePayload,
  ServiceAccountKeyDto,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl } from "@/lib/date-pl";

import {
  KEY_STATUS_LABEL,
  expiryPreview,
  expiryWarning,
  expiryWarningLabel,
  keyStatus,
  lastUsedLabel,
  parseTtlDays,
  sortKeys,
  type KeyStatus,
} from "./api-keys-model";
import type { RevealedApiKey } from "./types";

const STATUS_BADGE: Record<KeyStatus, "success" | "danger" | "neutral"> = {
  active: "success",
  expired: "danger",
  revoked: "neutral",
};

const COLUMNS = 6;

export interface ServiceAccountKeysProps {
  account: ServiceAccountDto;
  config: ServiceAccountConfigDto;
  now: Date;
  /** Klucz właśnie wydany na TYM koncie (pokazywany raz). */
  revealed: RevealedApiKey | null;
  onDismissRevealed: () => void;
  onIssueKey: (payload: ServiceAccountKeyCreatePayload) => Promise<unknown>;
  onRevokeKey: (keyId: string, reason: string | null) => Promise<unknown>;
}

export function ServiceAccountKeys({
  account,
  config,
  now,
  revealed,
  onDismissRevealed,
  onIssueKey,
  onRevokeKey,
}: ServiceAccountKeysProps) {
  const [issuing, setIssuing] = useState(false);
  const [revokingKeyId, setRevokingKeyId] = useState<string | null>(null);
  const keys = sortKeys(account.keys, now);

  return (
    <section aria-label={`Klucze konta ${account.name}`} className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Klucze</h3>
        {!issuing ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setRevokingKeyId(null);
              setIssuing(true);
            }}
          >
            <Plus className="size-4" aria-hidden />
            Wydaj klucz
          </Button>
        ) : null}
      </div>

      {revealed ? (
        <SecretRevealCard
          title={<>Zapisz teraz klucz „{revealed.keyLabel}”</>}
          description="Klucz widać tylko teraz — NEXUS przechowuje wyłącznie jego skrót. Zgubiony klucz trzeba zastąpić: wydaj nowy i odwołaj ten."
          secret={revealed.apiKey}
          onClose={onDismissRevealed}
        >
          <p className="text-xs text-muted-foreground">
            Wysyłaj go w nagłówku <code className="font-mono text-foreground">{config.header}</code>. Szybkie
            sprawdzenie: <code className="font-mono text-foreground">GET /api/integrations/v1/me</code>.
          </p>
        </SecretRevealCard>
      ) : null}

      {issuing ? (
        <IssueKeyForm
          config={config}
          now={now}
          accountActive={account.is_active}
          onSubmit={async (payload) => {
            await onIssueKey(payload);
            setIssuing(false);
          }}
          onCancel={() => setIssuing(false)}
        />
      ) : null}

      {keys.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
          <KeyRound className="size-4 shrink-0" aria-hidden />
          To konto nie ma jeszcze klucza. Wydaj pierwszy, żeby automatyzacja mogła się logować.
        </p>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[760px] text-sm">
            <caption className="sr-only">Klucze konta {account.name}</caption>
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th scope="col" className="sticky left-0 z-10 bg-card px-3 py-2 font-medium">
                  Klucz
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Wydany
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Wygasa
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Ostatnie użycie
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Status
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <Fragment key={key.key_id}>
                  <KeyRow
                    keyItem={key}
                    now={now}
                    revoking={revokingKeyId === key.key_id}
                    onStartRevoke={() => {
                      setIssuing(false);
                      setRevokingKeyId(key.key_id);
                    }}
                  />
                  {revokingKeyId === key.key_id ? (
                    <tr className="border-b border-border last:border-b-0">
                      <td colSpan={COLUMNS} className="bg-muted/30 px-3 py-3">
                        <RevokeKeyForm
                          keyItem={key}
                          onRevoke={async (reason) => {
                            await onRevokeKey(key.key_id, reason);
                            setRevokingKeyId(null);
                          }}
                          onCancel={() => setRevokingKeyId(null)}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function KeyRow({
  keyItem,
  now,
  revoking,
  onStartRevoke,
}: {
  keyItem: ServiceAccountKeyDto;
  now: Date;
  revoking: boolean;
  onStartRevoke: () => void;
}) {
  const status = keyStatus(keyItem, now);
  const warning = expiryWarning(keyItem, now);
  return (
    <tr className="border-b border-border align-top last:border-b-0">
      <th scope="row" className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-normal">
        <span className="block font-medium text-foreground [overflow-wrap:anywhere]">{keyItem.label}</span>
        <span className="block font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {keyItem.key_id}
        </span>
      </th>
      <td className="px-3 py-2 whitespace-nowrap">{formatIsoDatePl(keyItem.created_at)}</td>
      <td className="px-3 py-2">
        <span className="block whitespace-nowrap">{formatIsoDatePl(keyItem.expires_at)}</span>
        {warning ? (
          <Badge variant={warning.kind === "expired" ? "danger" : "warning"} size="sm" className="mt-1">
            {expiryWarningLabel(warning)}
          </Badge>
        ) : null}
      </td>
      <td className="px-3 py-2">{lastUsedLabel(keyItem, now)}</td>
      <td className="px-3 py-2">
        <Badge variant={STATUS_BADGE[status]} size="md">
          {KEY_STATUS_LABEL[status]}
        </Badge>
        {status === "revoked" && keyItem.revoke_reason ? (
          <span className="mt-1 block text-xs text-muted-foreground [overflow-wrap:anywhere]">
            Powód: {keyItem.revoke_reason}
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2 text-right">
        {status === "active" && !revoking ? (
          <Button
            type="button"
            variant="quiet"
            size="sm"
            onClick={onStartRevoke}
            aria-label={`Odwołaj klucz ${keyItem.label}`}
          >
            Odwołaj
          </Button>
        ) : null}
      </td>
    </tr>
  );
}

function IssueKeyForm({
  config,
  now,
  accountActive,
  onSubmit,
  onCancel,
}: {
  config: ServiceAccountConfigDto;
  now: Date;
  accountActive: boolean;
  onSubmit: (payload: ServiceAccountKeyCreatePayload) => Promise<unknown>;
  onCancel: () => void;
}) {
  const id = useId();
  const [label, setLabel] = useState("");
  const [days, setDays] = useState(String(config.default_ttl_days));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ttl = parseTtlDays(days, config.max_ttl_days);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!label.trim()) {
      setError("Podaj nazwę klucza — po niej poznasz, gdzie jest używany.");
      return;
    }
    if (ttl.error !== null) {
      setError(ttl.error);
      return;
    }
    setError(null);
    setPending(true);
    try {
      await onSubmit({ label: label.trim(), expires_in_days: ttl.days });
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się wydać klucza."));
    } finally {
      setPending(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      aria-label="Wydaj klucz"
      noValidate
      className="space-y-3 rounded-lg border border-border bg-muted/30 p-3"
    >
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_12rem]">
        <div>
          <label htmlFor={`${id}-label`} className="mb-1 block text-sm font-medium text-foreground">
            Nazwa klucza
          </label>
          <Input
            id={`${id}-label`}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="np. n8n — import zużycia MD"
            maxLength={120}
            autoComplete="off"
          />
        </div>
        <div>
          <label htmlFor={`${id}-days`} className="mb-1 block text-sm font-medium text-foreground">
            Ważność (dni)
          </label>
          <Input
            id={`${id}-days`}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            inputMode="numeric"
            autoComplete="off"
            invalid={ttl.error !== null}
          />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Najdłużej {config.max_ttl_days} dni.
        {ttl.days !== null ? ` Klucz wygaśnie ${expiryPreview(ttl.days, now)}.` : ""}
        {!accountActive ? " Konto jest wyłączone — klucz zadziała dopiero po jego włączeniu." : ""}
      </p>
      {error ? (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
          Anuluj
        </Button>
        <Button type="submit" size="sm" loading={pending}>
          Wydaj klucz
        </Button>
      </div>
    </form>
  );
}

function RevokeKeyForm({
  keyItem,
  onRevoke,
  onCancel,
}: {
  keyItem: ServiceAccountKeyDto;
  onRevoke: (reason: string | null) => Promise<unknown>;
  onCancel: () => void;
}) {
  const id = useId();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const { askConfirm, confirmDialog } = useConfirmV2();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const confirmed = await askConfirm({
      title: `Odwołać klucz „${keyItem.label}”?`,
      description:
        "Automatyzacje używające tego klucza od razu dostaną odmowę (401). Odwołania nie da się cofnąć — w razie potrzeby wydaj nowy klucz.",
      confirmLabel: "Odwołaj klucz",
      variant: "destructive",
    });
    if (!confirmed) return;
    setError(null);
    setPending(true);
    try {
      await onRevoke(reason.trim() || null);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się odwołać klucza."));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} aria-label={`Odwołanie klucza ${keyItem.label}`} noValidate className="space-y-2">
      {confirmDialog}
      <label htmlFor={`${id}-reason`} className="block text-sm font-medium text-foreground">
        Powód odwołania <span className="font-normal text-muted-foreground">(opcjonalnie)</span>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={`${id}-reason`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="np. wymiana klucza, wyciek, koniec automatyzacji"
          maxLength={255}
          autoComplete="off"
          className="min-w-0 flex-1 basis-64"
        />
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
          Anuluj
        </Button>
        <Button type="submit" variant="destructive" size="sm" loading={pending}>
          Odwołaj klucz
        </Button>
      </div>
      {error ? (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      ) : null}
    </form>
  );
}
