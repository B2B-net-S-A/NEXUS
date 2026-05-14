"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Mail,
  Plug,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { microsoft365Api } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";

export default function Microsoft365Card() {
  const queryClient = useQueryClient();
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const {
    data: status,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["m365-connection"],
    queryFn: () => microsoft365Api.getConnection().then((r) => r.data),
    // Poll more often while backfill is in progress.
    refetchInterval: (query) => {
      const connected = query.state.data?.connected;
      const backfilling = query.state.data?.backfill_in_progress;
      return connected && backfilling ? 15_000 : 60_000;
    },
    staleTime: 15_000,
  });

  const connectMutation = useMutation({
    mutationFn: () => microsoft365Api.getAuthorizeUrl().then((r) => r.data),
    onSuccess: (data) => {
      if (data?.authorize_url) {
        window.location.href = data.authorize_url;
      }
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => microsoft365Api.triggerSync().then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["m365-connection"] });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: () => microsoft365Api.disconnect().then((r) => r.data),
    onSuccess: () => {
      setConfirmDisconnect(false);
      queryClient.invalidateQueries({ queryKey: ["m365-connection"] });
    },
  });

  const connected = !!status?.connected;
  const backfillInProgress = connected && status?.backfill_in_progress;
  const hasError = connected && !!status?.last_error;
  const requiresReconnect = !!status?.requires_reconnect;

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border dark:border-border p-6">
      {/* Header */}
      <div className="flex items-start gap-4 mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
          <Mail className="w-6 h-6 text-primary" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-foreground dark:text-foreground">
              Microsoft 365
            </h3>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                isLoading
                  ? "bg-muted text-muted-foreground"
                  : requiresReconnect
                    ? "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                    : connected && !hasError
                      ? "bg-green-100 text-green-700"
                      : hasError
                        ? "bg-destructive/15 text-destructive"
                        : "bg-muted text-muted-foreground",
              )}
            >
              {isLoading
                ? "Sprawdzanie..."
                : requiresReconnect
                  ? "Wymagane ponowne podłączenie"
                  : connected && !hasError
                    ? "Połączony"
                    : hasError
                      ? "Błąd synchronizacji"
                      : "Niepołączony"}
            </span>
          </div>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">
            Wątki email z kandydatami, wysyłka, kalendarz i zaproszenia na interview
          </p>
        </div>
      </div>

      {/* Connected meta */}
      {connected && (
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="bg-muted dark:bg-muted rounded-xl p-3">
            <p className="text-xs text-muted-foreground dark:text-muted-foreground mb-0.5">
              Skrzynka
            </p>
            <p className="text-sm font-medium text-foreground dark:text-foreground truncate">
              {status?.mailbox_upn ?? "—"}
            </p>
          </div>
          <div className="bg-muted dark:bg-muted rounded-xl p-3">
            <p className="text-xs text-muted-foreground dark:text-muted-foreground mb-0.5">
              Ostatnia synchronizacja
            </p>
            <p className="text-sm font-medium text-foreground dark:text-foreground">
              {status?.last_sync_at
                ? formatRelativeTime(status.last_sync_at)
                : "Jeszcze nie synchronizowano"}
            </p>
          </div>
        </div>
      )}

      {/* Reconnect-required banner (amber) — token decryption broke server-side
          (e.g. encryption key rotation). User must re-run OAuth. */}
      {requiresReconnect && (
        <div className="flex items-start gap-2 text-sm text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50 rounded-xl px-4 py-3 mb-4">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div className="min-w-0 flex-1">
            <p className="font-medium">Wymagane ponowne podłączenie Microsoft 365</p>
            <p className="text-xs mt-0.5 text-amber-700 dark:text-amber-300">
              Po stronie serwera zmieniła się konfiguracja szyfrowania tokenów
              {status?.mailbox_upn ? ` dla skrzynki ${status.mailbox_upn}` : ""}.
              Kliknij „Połącz ponownie”, żeby przywrócić synchronizację. Twoje
              dotychczasowe maile i wątki pozostają nienaruszone.
            </p>
            <button
              onClick={() => connectMutation.mutate()}
              disabled={connectMutation.isPending}
              className="mt-2 inline-flex items-center gap-2 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors"
            >
              {connectMutation.isPending ? (
                <>
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Przygotowuję...
                </>
              ) : (
                <>
                  <Plug className="w-3 h-3" />
                  Połącz ponownie
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Backfill banner */}
      {backfillInProgress && (
        <div className="flex items-start gap-2 text-sm text-primary bg-primary/10 border border-primary/20 rounded-xl px-4 py-3 mb-4">
          <Loader2 className="w-4 h-4 flex-shrink-0 mt-0.5 animate-spin" />
          <div>
            <p className="font-medium">Pobieramy historię (ostatnie 12 miesięcy)</p>
            <p className="text-xs text-primary mt-0.5">
              Może to chwilę potrwać — wątki zaczną pojawiać się na profilach
              kandydatów po zakończeniu backfilla.
            </p>
          </div>
        </div>
      )}

      {/* Error banner */}
      {hasError && (
        <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-xl px-4 py-3 mb-4">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="font-medium">Błąd synchronizacji</p>
            <p className="text-xs text-destructive mt-0.5 break-words">
              {status?.last_error}
            </p>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        {!connected ? (
          <button
            onClick={() => connectMutation.mutate()}
            disabled={connectMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {connectMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Przygotowuję...
              </>
            ) : (
              <>
                <Plug className="w-4 h-4" />
                Połącz z Microsoft 365
              </>
            )}
          </button>
        ) : (
          <>
            <button
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending || backfillInProgress}
              className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
              title={
                backfillInProgress
                  ? "Backfill w toku — poczekaj na jego zakończenie"
                  : undefined
              }
            >
              {syncMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Synchronizuję...
                </>
              ) : (
                <>
                  <RefreshCw className="w-4 h-4" />
                  Synchronizuj teraz
                </>
              )}
            </button>

            {!confirmDisconnect ? (
              <button
                onClick={() => setConfirmDisconnect(true)}
                className="flex items-center gap-2 px-4 py-2 border border-border dark:border-border text-muted-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted rounded-lg text-sm font-medium transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                Rozłącz
              </button>
            ) : (
              <div className="flex items-center gap-2 px-3 py-2 border border-destructive/20 bg-destructive/10 text-destructive rounded-lg text-sm">
                <span>Potwierdź rozłączenie?</span>
                <button
                  onClick={() => disconnectMutation.mutate()}
                  disabled={disconnectMutation.isPending}
                  className="font-semibold hover:underline"
                >
                  Tak, rozłącz
                </button>
                <span>·</span>
                <button
                  onClick={() => setConfirmDisconnect(false)}
                  className="hover:underline"
                >
                  Anuluj
                </button>
              </div>
            )}
          </>
        )}

        {!connected && (
          <a
            href="https://portal.azure.com"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 border border-border dark:border-border text-muted-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted rounded-lg text-sm font-medium transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            Azure Portal
          </a>
        )}
      </div>

      {syncMutation.isSuccess && !syncMutation.isPending && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-green-700">
          <CheckCircle2 className="w-3.5 h-3.5" />
          Synchronizacja uruchomiona w tle — odśwież za chwilę, żeby zobaczyć wynik.
        </p>
      )}
    </div>
  );
}
