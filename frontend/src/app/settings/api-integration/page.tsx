"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  Copy,
  Trash2,
  Key,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Power,
} from "lucide-react";
import {
  oauthClientsApi,
  type OAuthClientDto,
  type ScopeInfoDto,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatRelativeTime(iso: string | null): string {
  if (!iso) return "nigdy nie używany";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffMs = now - then;
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "przed chwilą";
  if (minutes < 60) return `${minutes} min temu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h temu`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} dni temu`;
  const months = Math.floor(days / 30);
  return `${months} mies. temu`;
}

// ── Sub-components ───────────────────────────────────────────────────────────

interface CreateClientFormProps {
  scopes: ScopeInfoDto[];
  onCreated: (clientSecret: string, name: string) => void;
  onCancel: () => void;
}

function CreateClientForm({ scopes, onCreated, onCancel }: CreateClientFormProps) {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const createMutation = useMutation({
    mutationFn: () =>
      oauthClientsApi
        .create({ name, scopes: Array.from(selected) })
        .then((r) => r.data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["oauth-clients"] });
      onCreated(data.client_secret, data.client.name);
    },
    onError: (err: unknown) => {
      setError(
        err instanceof Error ? err.message : "Nie udało się utworzyć klienta",
      );
    },
  });

  const toggle = (scope: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  };

  const submit = () => {
    if (!name.trim()) {
      setError("Podaj nazwę klienta");
      return;
    }
    setError(null);
    createMutation.mutate();
  };

  return (
    <div className="p-6 bg-card border border-border rounded-xl">
      <h3 className="text-lg font-semibold text-foreground mb-4">
        Nowy klient OAuth
      </h3>

      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium text-foreground mb-1 block">
            Nazwa
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="np. n8n Production / ChatGPT"
            className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-ring"
          />
        </div>

        <div>
          <label className="text-sm font-medium text-foreground mb-2 block">
            Uprawnienia (scopes)
          </label>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {scopes.map((s) => (
              <label
                key={s.value}
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-muted/50 rounded cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={selected.has(s.value)}
                  onChange={() => toggle(s.value)}
                  className="rounded"
                />
                <span className="text-sm text-foreground">{s.label}</span>
                <span className="ml-auto text-xs font-mono text-muted-foreground">
                  {s.value}
                </span>
              </label>
            ))}
          </div>
        </div>

        {error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-md flex items-center gap-2 text-sm text-rose-500">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={createMutation.isPending}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50"
          >
            {createMutation.isPending ? "Tworzenie…" : "Utwórz klienta"}
          </button>
        </div>
      </div>
    </div>
  );
}

interface SecretRevealCardProps {
  clientName: string;
  clientSecret: string;
  onClose: () => void;
}

function SecretRevealCard({
  clientName,
  clientSecret,
  onClose,
}: SecretRevealCardProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(clientSecret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-6 bg-amber-500/5 border-2 border-amber-500/30 rounded-xl">
      <div className="flex items-start gap-3 mb-4">
        <AlertCircle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
        <div>
          <h3 className="text-base font-semibold text-foreground">
            Zapisz teraz secret dla &ldquo;{clientName}&rdquo;
          </h3>
          <p className="text-sm text-muted-foreground mt-1">
            Po zamknięciu tego okna sekret nie będzie już dostępny. NEXUS
            przechowuje wyłącznie hash. Aby go odzyskać, trzeba usunąć i
            stworzyć klienta od nowa.
          </p>
        </div>
      </div>

      <div className="bg-background border border-border rounded-md p-3 font-mono text-sm break-all">
        {clientSecret}
      </div>

      <div className="flex gap-2 mt-4 justify-end">
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          {copied ? (
            <>
              <CheckCircle2 className="w-4 h-4" />
              Skopiowano
            </>
          ) : (
            <>
              <Copy className="w-4 h-4" />
              Skopiuj
            </>
          )}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 text-sm border border-border rounded-md hover:bg-muted"
        >
          Zamknij
        </button>
      </div>
    </div>
  );
}

interface ClientRowProps {
  client: OAuthClientDto;
  scopes: ScopeInfoDto[];
  onChange: () => void;
}

function ClientRow({ client, scopes, onChange }: ClientRowProps) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<"toggle" | "delete" | null>(null);

  const labelFor = (value: string) =>
    scopes.find((s) => s.value === value)?.label ?? value;

  const toggleEnabled = useMutation({
    mutationFn: () =>
      oauthClientsApi
        .update(client.id, { enabled: !client.enabled })
        .then((r) => r.data),
    onMutate: () => setPending("toggle"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["oauth-clients"] });
      onChange();
    },
    onSettled: () => setPending(null),
  });

  const remove = useMutation({
    mutationFn: () => oauthClientsApi.remove(client.id),
    onMutate: () => setPending("delete"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["oauth-clients"] });
      onChange();
    },
    onSettled: () => setPending(null),
  });

  return (
    <div
      className={cn(
        "p-4 bg-card border rounded-xl transition-opacity",
        client.enabled ? "border-border" : "border-border opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Key className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold text-foreground">
              {client.name}
            </h3>
            {!client.enabled && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-500">
                Wyłączony
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground space-y-0.5 mt-2">
            <div>
              <span className="font-mono">{client.client_id}</span>
            </div>
            <div>
              {client.last_used_at
                ? `Ostatnio użyty: ${formatRelativeTime(client.last_used_at)}`
                : "Nigdy nie używany"}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            {client.scopes.length === 0 && (
              <span className="text-xs text-muted-foreground italic">
                Brak uprawnień
              </span>
            )}
            {client.scopes.map((s) => (
              <span
                key={s}
                className="text-xs px-2 py-0.5 rounded-full bg-muted text-foreground"
                title={s}
              >
                {labelFor(s)}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <button
            type="button"
            onClick={() => toggleEnabled.mutate()}
            disabled={pending !== null}
            className={cn(
              "p-2 rounded-md transition-colors",
              client.enabled
                ? "text-emerald-500 hover:bg-emerald-500/10"
                : "text-muted-foreground hover:bg-muted",
              "disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            title={client.enabled ? "Wyłącz" : "Włącz"}
          >
            {pending === "toggle" ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Power className="w-4 h-4" />
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              if (confirm(`Usunąć klienta "${client.name}"?`)) {
                remove.mutate();
              }
            }}
            disabled={pending !== null}
            className="p-2 text-rose-500 hover:bg-rose-500/10 rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
            title="Usuń"
          >
            {pending === "delete" ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ApiIntegrationPage() {
  const [showForm, setShowForm] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<{
    name: string;
    secret: string;
  } | null>(null);

  const clientsQuery = useQuery({
    queryKey: ["oauth-clients"],
    queryFn: () => oauthClientsApi.list().then((r) => r.data),
  });

  const scopesQuery = useQuery({
    queryKey: ["oauth-scopes"],
    queryFn: () => oauthClientsApi.scopes().then((r) => r.data),
  });

  // Auto-collapse the create form once we've revealed a secret.
  useEffect(() => {
    if (revealedSecret) setShowForm(false);
  }, [revealedSecret]);

  const isLoading = clientsQuery.isLoading || scopesQuery.isLoading;

  if (isLoading) {
    return (
      <div className="container max-w-4xl mx-auto py-8 px-4">
        <div className="flex items-center justify-center min-h-[400px]">
          <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
        </div>
      </div>
    );
  }

  if (clientsQuery.error || scopesQuery.error) {
    return (
      <div className="container max-w-4xl mx-auto py-8 px-4">
        <div className="p-6 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-2 text-rose-500">
          <AlertCircle className="w-5 h-5" />
          <span>
            Nie udało się załadować klientów OAuth. Sprawdź uprawnienia
            administratora.
          </span>
        </div>
      </div>
    );
  }

  const clients = clientsQuery.data ?? [];
  const scopes = scopesQuery.data ?? [];

  return (
    <div className="container max-w-4xl mx-auto py-8 px-4">
      <div className="mb-6">
        <Link
          href="/settings"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Ustawienia
        </Link>
        <h1 className="text-2xl font-bold text-foreground mt-2">
          Integracja z API
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Zarządzaj kluczami OAuth2 dla zewnętrznych systemów (n8n, ChatGPT,
          Zapier, ...). Każdy klient otrzymuje własny client_id + secret z
          ograniczonymi uprawnieniami.
        </p>
      </div>

      {revealedSecret && (
        <div className="mb-6">
          <SecretRevealCard
            clientName={revealedSecret.name}
            clientSecret={revealedSecret.secret}
            onClose={() => setRevealedSecret(null)}
          />
        </div>
      )}

      {showForm ? (
        <div className="mb-6">
          <CreateClientForm
            scopes={scopes}
            onCreated={(secret, name) => setRevealedSecret({ name, secret })}
            onCancel={() => setShowForm(false)}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="mb-6 inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm"
        >
          <Plus className="w-4 h-4" />
          Dodaj klienta
        </button>
      )}

      <div className="space-y-3">
        {clients.length === 0 && (
          <div className="p-8 text-center bg-muted/30 rounded-xl border border-dashed">
            <Key className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              Brak skonfigurowanych klientów OAuth.
            </p>
          </div>
        )}
        {clients.map((c) => (
          <ClientRow
            key={c.id}
            client={c}
            scopes={scopes}
            onChange={() => clientsQuery.refetch()}
          />
        ))}
      </div>
    </div>
  );
}
