"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  notificationDeliveryApi,
  type NotificationDeliveryOverview,
  type NotificationDeliveryType,
  type NotificationDeliveryUpdate,
} from "@/lib/api/notificationDelivery";
import { hasSectionAccess } from "@/lib/section-access";
import { isForbiddenError } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

export const NOTIFICATION_DELIVERY_QUERY_KEY = ["settings-notification-delivery"] as const;

function formatTime(value: string | null): string {
  if (!value) return "Brak danych";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Brak danych" : date.toLocaleString("pl-PL");
}

function channelLabel(channel: string): string {
  return ({ email: "E-mail", inapp: "Dzwonek NEXUS", in_app: "Dzwonek NEXUS", client_panel: "Panel klientów" } as Record<string, string>)[channel] ?? channel;
}

function providerLabel(kind: string): string {
  return ({ graph_app: "Microsoft 365 — skrzynka systemowa", graph_delegated: "Microsoft 365 — podłączona skrzynka", smtp: "SMTP", none: "Brak dostawcy" } as Record<string, string>)[kind] ?? kind;
}

function observedStatus(status: string): string {
  return ({
    ok: "Ostatnia obserwacja: wysyłka działała",
    healthy: "Ostatnia obserwacja: wysyłka działała",
    degraded: "Ostatnia obserwacja: problem z wysyłką",
    error: "Ostatnia obserwacja: błąd wysyłki",
    cooldown: "Wysyłka czasowo wstrzymana po błędzie",
    unconfigured: "Brak konfiguracji wysyłki",
    unknown: "Brak potwierdzenia poprawnej wysyłki",
  } as Record<string, string>)[status] ?? "Brak potwierdzenia poprawnej wysyłki";
}

function Toggle({ checked, disabled, label, onChange }: {
  checked: boolean;
  disabled: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-label={label}
      aria-checked={checked}
      disabled={disabled}
      onClick={onChange}
      className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${checked ? "bg-primary" : "bg-muted-foreground"}`} />
      {checked ? "Włączone" : "Wyłączone"}
    </button>
  );
}

function NotificationTable({ items, enabled, busy, onToggle }: {
  items: NotificationDeliveryType[];
  enabled: boolean;
  busy: boolean;
  onToggle: (item: NotificationDeliveryType) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted text-muted-foreground">
          <tr>
            <th scope="col" className="px-4 py-3">Powiadomienie</th>
            <th scope="col" className="px-4 py-3">Wyzwalacz i odbiorcy</th>
            <th scope="col" className="px-4 py-3">Kanały</th>
            <th scope="col" className="px-4 py-3">Nadawca e-mail</th>
            <th scope="col" className="px-4 py-3">E-mail</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <th scope="row" className="min-w-40 px-4 py-4 font-medium">
                {item.label}
                <span className="mt-1 block text-xs font-normal text-muted-foreground">{item.module}</span>
              </th>
              <td className="min-w-64 max-w-md px-4 py-4">
                <p>{item.trigger}</p>
                <details className="mt-2">
                  <summary className="cursor-pointer font-medium text-primary">Do kogo trafia</summary>
                  <p className="mt-2 text-muted-foreground">{item.recipient_rule}</p>
                </details>
              </td>
              <td className="px-4 py-4 text-muted-foreground">{item.channels.map(channelLabel).join(", ")}</td>
              <td className="px-4 py-4">
                <span className="break-all">{item.sender || "Nie skonfigurowano"}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{providerLabel(item.provider_kind)}</span>
                {item.provider_status && <span className="mt-1 block text-xs text-muted-foreground">{observedStatus(item.provider_status)}</span>}
              </td>
              <td className="min-w-44 px-4 py-4">
                {item.editable ? (
                  <>
                    <Toggle checked={item.email_enabled} disabled={busy} label={`E-mail: ${item.label}`} onChange={() => onToggle(item)} />
                    <p className="mt-2 text-xs text-muted-foreground">
                      {item.effective_enabled
                        ? "Zezwolono na wysyłkę nowych zdarzeń."
                        : !enabled && item.email_enabled
                          ? "Wysyłka globalna jest wyłączona."
                          : "Ten typ maila jest wyłączony."}
                    </p>
                  </>
                ) : (
                  <span className="text-muted-foreground">Bez przełącznika — bezpieczeństwo konta</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function NotificationDeliverySettings() {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);
  const canRead = hasRole(user, "admin") && hasSectionAccess(user, "system_admin", "read");
  const canWrite = canRead && hasSectionAccess(user, "system_admin", "write");
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: NOTIFICATION_DELIVERY_QUERY_KEY,
    queryFn: notificationDeliveryApi.get,
    enabled: hydrated && canRead,
  });
  const save = useMutation({
    mutationFn: notificationDeliveryApi.update,
    onSuccess: (result: NotificationDeliveryOverview) => {
      queryClient.setQueryData(NOTIFICATION_DELIVERY_QUERY_KEY, result);
      void queryClient.invalidateQueries({ queryKey: NOTIFICATION_DELIVERY_QUERY_KEY });
    },
  });

  if (!hydrated) return <p role="status">Ładowanie ustawień…</p>;
  if (!canRead) return <QueryStateNotice state="forbidden" />;
  if (query.isError) return <QueryStateNotice state={isForbiddenError(query.error) ? "forbidden" : "error"} onRetry={() => { void query.refetch(); }} />;
  if (!query.data) return <p role="status">Ładowanie ustawień powiadomień…</p>;

  const data = query.data;
  const editable = data.types.filter((item) => item.editable);
  const required = data.types.filter((item) => !item.editable);
  const busy = !canWrite || save.isPending || query.isFetching;
  const update = (enabled: boolean, changed?: NotificationDeliveryType) => {
    if (busy) return;
    const input: NotificationDeliveryUpdate = {
      enabled,
      types: editable.map((item) => ({
        id: item.id,
        email_enabled: item.id === changed?.id ? !item.email_enabled : item.email_enabled,
      })),
    };
    save.mutate(input);
  };

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-border bg-card p-5" aria-labelledby="notification-delivery-heading">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 id="notification-delivery-heading" className="font-semibold">Automatyczne powiadomienia e-mail</h2>
            <p className="mt-1 text-sm text-muted-foreground">Wysyłka wymaga włączenia jej globalnie oraz dla danego typu.</p>
          </div>
          <Toggle checked={data.enabled} disabled={busy} label="Automatyczna wysyłka e-mail" onChange={() => update(!data.enabled)} />
        </div>
        <p className="mt-4 text-sm">Po włączeniu wysyłane są tylko nowe zdarzenia. Starsze wiadomości są wykluczone z wysyłki; historia w dzwonku NEXUS pozostaje.</p>
        {data.send_not_before && <p className="mt-2 text-xs text-muted-foreground">Bieżąca wysyłka obejmuje zdarzenia od: {formatTime(data.send_not_before)}.</p>}
        {!canWrite && <p className="mt-2 text-sm text-muted-foreground">Masz dostęp tylko do odczytu.</p>}
        <div className="mt-3 text-sm" aria-live="polite">
          {save.isPending && <p>Zapisuję ustawienia…</p>}
          {save.isSuccess && !save.isPending && <p>Ustawienia zapisane.</p>}
          {save.isError && <p role="alert" className="text-destructive">Nie udało się zapisać ustawień. Sprawdź połączenie i spróbuj ponownie.</p>}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5" aria-labelledby="notification-provider-heading">
        <h2 id="notification-provider-heading" className="font-semibold">Nadawca i stan poczty</h2>
        <p className="mt-2 break-all text-sm">{providerLabel(data.provider.kind)}: <strong>{data.provider.sender || "Nie skonfigurowano nadawcy"}</strong></p>
        <p className="mt-1 text-sm text-muted-foreground">{data.provider.configured ? "Konfiguracja jest obecna." : "Brak wymaganej konfiguracji."} {observedStatus(data.provider.observed_status)}</p>
        <p className="mt-2 text-sm text-muted-foreground">Przełączniki określają zgodę na wysyłkę. Nie potwierdzają sprawności połączenia z pocztą.</p>
        <dl className="mt-3 grid gap-3 text-xs text-muted-foreground sm:grid-cols-2">
          <div><dt>Ostatnia udana wysyłka</dt><dd>{formatTime(data.provider.last_success_at)}</dd></div>
          <div><dt>Ostatni błąd wysyłki</dt><dd>{formatTime(data.provider.last_failure_at)}{data.provider.failure_code ? ` (${data.provider.failure_code})` : ""}</dd></div>
          {data.provider.cooldown_until && <div><dt>Przerwa po błędzie do</dt><dd>{formatTime(data.provider.cooldown_until)}</dd></div>}
        </dl>
      </section>

      <section aria-labelledby="notification-types-heading" className="space-y-3">
        <h2 id="notification-types-heading" className="font-semibold">Rodzaje powiadomień</h2>
        <NotificationTable items={editable} enabled={data.enabled} busy={busy} onToggle={(item) => update(data.enabled, item)} />
      </section>

      <section className="space-y-3" aria-labelledby="notification-security-heading">
        <h2 id="notification-security-heading" className="font-semibold">Bezpieczeństwo konta</h2>
        <p className="text-sm text-muted-foreground">Te wiadomości działają niezależnie od powyższych przełączników, gdy użytkownik wykonuje odpowiednią czynność.</p>
        <NotificationTable items={required} enabled={data.enabled} busy onToggle={() => {}} />
      </section>

      <section className="rounded-xl border border-border bg-card p-5" aria-labelledby="notification-backlog-heading">
        <h2 id="notification-backlog-heading" className="font-semibold">Kolejka powiadomień czatu</h2>
        <p className="mt-2 text-sm text-muted-foreground">Poniższe liczby dotyczą wyłącznie maili o nieprzeczytanych wiadomościach czatu.</p>
        <dl className="mt-3 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-muted-foreground">Oczekujące lub do ponowienia</dt><dd className="mt-1 font-semibold">{data.backlog.pending_retry}</dd></div>
          <div><dt className="text-muted-foreground">Potencjalnie gotowe (maksymalnie)</dt><dd className="mt-1 font-semibold">{data.backlog.ready_upper_bound}</dd></div>
          <div><dt className="text-muted-foreground">Niepewny wynik wysyłki</dt><dd className="mt-1 font-semibold">{data.backlog.uncertain}</dd></div>
          <div><dt className="text-muted-foreground">Starsze, wykluczone z wysyłki</dt><dd className="mt-1 font-semibold">{data.backlog.legacy_suppressed}</dd></div>
        </dl>
        <p className="mt-3 text-xs text-muted-foreground">Włączenie powiadomień nie uruchamia wysyłki zaległości.</p>
      </section>

      <section className="space-y-3" aria-labelledby="notification-excluded-heading">
        <h2 id="notification-excluded-heading" className="font-semibold">Pozostałe kanały</h2>
        {data.excluded_channels.map((channel) => (
          <details key={channel.id} className="rounded-xl border border-border bg-card p-4 text-sm">
            <summary className="cursor-pointer font-medium">{channel.label}</summary>
            <p className="mt-2 text-muted-foreground">{channel.description}</p>
          </details>
        ))}
      </section>
    </div>
  );
}
