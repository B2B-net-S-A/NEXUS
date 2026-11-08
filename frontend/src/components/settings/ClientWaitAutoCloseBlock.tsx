"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CLIENT_WAIT_SETTINGS_KEY,
  fetchClientWaitSettings,
  saveClientWaitSettings,
} from "@/lib/api/clientWait";

/**
 * Wyłącznik automatycznego zamykania par bez odpowiedzi klienta (08.11.2026).
 * Działa od razu, bez wdrożenia; zmienia Head of Recruitment i admin.
 */
export function ClientWaitAutoCloseBlock({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const query = useQuery({
    queryKey: CLIENT_WAIT_SETTINGS_KEY,
    queryFn: fetchClientWaitSettings,
    retry: false,
  });
  const save = useMutation({
    mutationFn: saveClientWaitSettings,
    onSuccess: (value) => {
      queryClient.setQueryData(CLIENT_WAIT_SETTINGS_KEY, value);
      setNotice({
        ok: true,
        text: value.auto_close
          ? "Włączone. Pary starsze niż 30 dni dostają jeszcze 7 dni."
          : "Wyłączone. NEXUS nie zamyka par sam.",
      });
    },
    onError: (error) =>
      setNotice({ ok: false, text: apiErrorMessage(error, "Nie udało się zapisać ustawienia.") }),
  });

  return (
    <section
      data-testid="client-wait-auto-close"
      className="mt-4 rounded-xl border border-border bg-card p-4"
    >
      <h3 className="text-sm font-semibold">Odpowiedź klienta</h3>
      {query.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się odczytać ustawienia.")}
        </p>
      ) : null}
      {query.isSuccess ? (
        <label className="mt-2 flex items-start gap-2.5">
          <Switch
            checked={query.data.auto_close}
            disabled={!canEdit || save.isPending}
            onCheckedChange={(checked) => save.mutate(checked)}
            aria-label="Zamykaj automatycznie po 30 dniach bez odpowiedzi klienta"
            className="mt-0.5"
          />
          <span className="min-w-0 text-sm">
            <span className="font-medium">
              Zamykaj automatycznie po 30 dniach bez odpowiedzi klienta
            </span>
            <span className="block text-xs text-muted-foreground">
              Dotyczy kart w „CV wysłane”. Proces kończy się jako „Klient nie odpowiedział”,
              kandydat nie dostaje maila.
            </span>
          </span>
        </label>
      ) : null}
      {notice ? (
        <p
          role="status"
          className={`mt-2 text-xs ${notice.ok ? "text-muted-foreground" : "text-destructive"}`}
        >
          {notice.text}
        </p>
      ) : null}
    </section>
  );
}
