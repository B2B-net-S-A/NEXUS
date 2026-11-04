"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  notificationDeliveryApi,
  type NotificationDeliveryOverview,
  type NotificationDeliveryType,
  type NotificationSilencedKind,
  type NotificationDeliveryUpdate,
} from "@/lib/api/notificationDelivery";
import { pluralPl } from "@/lib/plural-pl";
import { hasSectionAccess } from "@/lib/section-access";
import { isForbiddenError } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";

export const NOTIFICATION_DELIVERY_QUERY_KEY = ["settings-notification-delivery"] as const;

/** Mail, którego zasięg znamy co do osoby (poranny skrót). */
const DAILY_DIGEST_ID = "daily_digest";

/** Przełącznik czekający na potwierdzenie — wyłączenie dotyczy całej firmy. */
type PendingOff =
  | { kind: "global" }
  | { kind: "type"; item: NotificationDeliveryType };

function recipientsLabel(count: number): string {
  return `${count} ${pluralPl(count, "odbiorca", "odbiorców", "odbiorców")}`;
}

function peopleDative(count: number): string {
  return `${count} ${pluralPl(count, "osobie", "osobom", "osobom")}`;
}

function CompanyWideBadge({ recipients }: { recipients?: number | null }) {
  return (
    <Badge variant="warning" size="sm" className="whitespace-nowrap">
      cała firma{typeof recipients === "number" ? ` · ${recipientsLabel(recipients)}` : ""}
    </Badge>
  );
}

function selfDisabledLabel(count: number): string {
  if (count === 1) return "1 osoba wyłączyła sobie ten mail";
  const few = count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14);
  return `${count} ${few ? "osoby wyłączyły" : "osób wyłączyło"} sobie ten mail`;
}

/** Firmowe „włączone” nie znaczy „dostają wszyscy” — kto wyłączył mail sobie. */
function SelfDisabledNote({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer font-medium text-primary">
        {selfDisabledLabel(names.length)}
      </summary>
      <p className="mt-1 text-muted-foreground">{names.join(", ")}</p>
    </details>
  );
}

function formatTime(value: string | null): string {
  if (!value) return "Brak danych";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Brak danych" : date.toLocaleString("pl-PL");
}

function channelLabel(channel: string): string {
  return ({ email: "E-mail", inapp: "NEXUS (ikony paska)", in_app: "NEXUS (ikony paska)", client_panel: "Panel klientów" } as Record<string, string>)[channel] ?? channel;
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

function NotificationTable({ items, enabled, busy, digestRecipients, onToggle }: {
  items: NotificationDeliveryType[];
  enabled: boolean;
  busy: boolean;
  digestRecipients: number | null;
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
                {item.editable && item.required && (
                  <Badge variant="soft" size="sm" className="ml-2 whitespace-nowrap align-middle">
                    obowiązkowy
                  </Badge>
                )}
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
                    <div className="flex flex-wrap items-center gap-2">
                      <Toggle checked={item.email_enabled} disabled={busy} label={`E-mail: ${item.label}`} onChange={() => onToggle(item)} />
                      <CompanyWideBadge recipients={item.id === DAILY_DIGEST_ID ? digestRecipients : null} />
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {item.effective_enabled
                        ? "Zezwolono na wysyłkę nowych zdarzeń."
                        : !enabled && item.email_enabled
                          ? "Wysyłka globalna jest wyłączona."
                          : item.paused_reason
                            ? `Wstrzymany: ${item.paused_reason}`
                            : "Ten typ maila jest wyłączony."}
                    </p>
                    <SelfDisabledNote names={item.self_disabled ?? []} />
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

/** Baner z 29.10.2026: rodzaj wyłączony dla firmy, a NEXUS tworzy w nim
 *  dzwonki — „Nowa osoba” i „Prep” tak startowały i nikt o tym nie wiedział. */
function SilencedBanner({ items, windowDays, busy, onEnable, onKeepOff }: {
  items: NotificationSilencedKind[];
  windowDays: number;
  busy: boolean;
  onEnable: (id: string) => void;
  onKeepOff: (id: string) => void;
}) {
  return (
    <section
      aria-labelledby="notification-silenced-heading"
      className="rounded-xl border border-warning/40 bg-warning-muted p-5 text-warning-muted-foreground"
    >
      <h2 id="notification-silenced-heading" className="font-semibold">
        Maile wyłączone dla całej firmy, choć NEXUS tworzy w nich dzwonki
      </h2>
      <p className="mt-1 text-sm">
        Te rodzaje nikomu nie wychodzą mailem. Włącz je albo zostaw wyłączone — decyzja trafi do Historii zdarzeń.
      </p>
      <ul className="mt-3 divide-y divide-warning/25">
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
            <div className="min-w-0">
              <p className="font-medium">{item.label}</p>
              <p className="text-sm">
                {item.bells} {pluralPl(item.bells, "dzwonek", "dzwonki", "dzwonków")} w {windowDays} dni bez maila,{" "}
                {item.unread} {pluralPl(item.unread, "nieprzeczytany", "nieprzeczytane", "nieprzeczytanych")}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={busy} aria-label={`Włącz: ${item.label}`} onClick={() => onEnable(item.id)}>
                Włącz
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                aria-label={`Zostaw wyłączone: ${item.label}`}
                onClick={() => onKeepOff(item.id)}
              >
                Zostaw wyłączone
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export interface NotificationDeliverySettingsProps {
  /** Przejście do zakładki „Moje” (wyłączenie maila tylko sobie). Bez tego
   *  ekran prowadzi linkiem do pozycji „Moje powiadomienia”. */
  onGoToMine?: () => void;
}

export default function NotificationDeliverySettings({ onGoToMine }: NotificationDeliverySettingsProps = {}) {
  // Cel pytania zostaje po zamknięciu okna (`offOpen`), żeby tytuł nie znikał
  // w trakcie animacji zamykania.
  const [pendingOff, setPendingOff] = useState<PendingOff | null>(null);
  const [offOpen, setOffOpen] = useState(false);
  // Powód wstrzymania maila obowiązkowego (26.10.2026) — wymagany przez API.
  const [pauseReason, setPauseReason] = useState("");
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
  const update = (enabled: boolean, changed?: NotificationDeliveryType, reason?: string, keepOff?: string) => {
    if (busy) return;
    const input: NotificationDeliveryUpdate = {
      enabled,
      types: editable.map((item) => ({
        id: item.id,
        email_enabled: item.id === changed?.id ? !item.email_enabled : item.email_enabled,
      })),
      ...(reason ? { reason } : {}),
      ...(keepOff ? { keep_off: [keepOff] } : {}),
    };
    save.mutate(input);
  };
  const silenced = data.silenced ?? [];
  const enableSilenced = (id: string) => {
    const item = editable.find((type) => type.id === id);
    if (item && !item.email_enabled) update(data.enabled, item);
  };
  const keepSilencedOff = (id: string) => update(data.enabled, undefined, undefined, id);
  // Włączenie zapisuje się od razu. Wyłączenie zabiera mail wszystkim, więc
  // najpierw pyta — 09.10.2026 jedno kliknięcie wyłączyło skrót 28 osobom.
  const askOff = (target: PendingOff) => {
    setPendingOff(target);
    setPauseReason("");
    setOffOpen(true);
  };
  const toggleGlobal = () => {
    if (busy) return;
    if (data.enabled) askOff({ kind: "global" });
    else update(true);
  };
  const toggleType = (item: NotificationDeliveryType) => {
    if (busy) return;
    if (item.email_enabled) askOff({ kind: "type", item });
    else update(data.enabled, item);
  };
  const pendingRequired = pendingOff?.kind === "type" && pendingOff.item.required === true;
  const confirmOff = () => {
    if (!pendingOff || !offOpen) return;
    if (pendingRequired && !pauseReason.trim()) return;
    if (pendingOff.kind === "global") update(false);
    else update(data.enabled, pendingOff.item, pendingRequired ? pauseReason.trim() : undefined);
    setOffOpen(false);
  };
  const digestRecipients = data.daily_digest_recipients ?? null;
  const pendingDigest =
    pendingOff?.kind === "type" && pendingOff.item.id === DAILY_DIGEST_ID && digestRecipients !== null;
  const offTitle = !pendingOff
    ? ""
    : pendingOff.kind === "global"
      ? "Wyłączasz automatyczne maile całej firmie"
      : pendingDigest
        ? `Wyłączasz ten mail ${peopleDative(digestRecipients ?? 0)}`
        : pendingRequired
          ? "Wstrzymujesz mail obowiązkowy całej firmie"
          : "Wyłączasz ten mail całej firmie";
  const lastChange = data.updated_at ? formatTime(data.updated_at) : null;

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        Te przełączniki działają <strong className="font-semibold text-foreground">dla całej firmy</strong>.
        Żeby wyłączyć mail tylko sobie, przejdź do zakładki „Moje”.
      </p>
      <section className="rounded-xl border border-border bg-card p-5" aria-labelledby="notification-delivery-heading">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 id="notification-delivery-heading" className="font-semibold">Automatyczne powiadomienia e-mail</h2>
            <p className="mt-1 text-sm text-muted-foreground">Wysyłka wymaga włączenia jej globalnie oraz dla danego typu.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <CompanyWideBadge />
            <Toggle checked={data.enabled} disabled={busy} label="Automatyczna wysyłka e-mail" onChange={toggleGlobal} />
          </div>
        </div>
        <p className="mt-4 text-sm">Po włączeniu wysyłane są tylko nowe zdarzenia. Starsze wiadomości są wykluczone z wysyłki; powiadomienia w NEXUSIE pozostają.</p>
        {data.send_not_before && <p className="mt-2 text-xs text-muted-foreground">Bieżąca wysyłka obejmuje zdarzenia od: {formatTime(data.send_not_before)}.</p>}
        {lastChange && (
          <p className="mt-2 text-xs text-muted-foreground">
            Ostatnia zmiana: {lastChange}{data.updated_by_name ? ` · ${data.updated_by_name}` : ""}
          </p>
        )}
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

      {silenced.length > 0 && (
        <SilencedBanner
          items={silenced}
          windowDays={data.silenced_window_days ?? 7}
          busy={busy}
          onEnable={enableSilenced}
          onKeepOff={keepSilencedOff}
        />
      )}

      <section aria-labelledby="notification-types-heading" className="space-y-3">
        <h2 id="notification-types-heading" className="font-semibold">Rodzaje powiadomień</h2>
        <NotificationTable items={editable} enabled={data.enabled} busy={busy} digestRecipients={digestRecipients} onToggle={toggleType} />
      </section>

      <section className="space-y-3" aria-labelledby="notification-security-heading">
        <h2 id="notification-security-heading" className="font-semibold">Bezpieczeństwo konta</h2>
        <p className="text-sm text-muted-foreground">Te wiadomości działają niezależnie od powyższych przełączników, gdy użytkownik wykonuje odpowiednią czynność.</p>
        <NotificationTable items={required} enabled={data.enabled} busy digestRecipients={null} onToggle={() => {}} />
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

      <AppModal
        open={offOpen && pendingOff !== null}
        onOpenChange={(open) => {
          if (!open) setOffOpen(false);
        }}
        title={offTitle}
        description="To nie jest ustawienie Twojego konta."
        footer={
          <>
            <Button variant="outline" onClick={() => setOffOpen(false)}>Anuluj</Button>
            <Button
              variant="destructive"
              onClick={confirmOff}
              disabled={pendingRequired && !pauseReason.trim()}
            >
              {pendingRequired ? "Wstrzymaj wszystkim" : "Wyłącz wszystkim"}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-foreground">
          <p>
            {pendingOff?.kind === "type"
              ? `${pendingOff.item.label} — ten mail przestanie wychodzić do wszystkich odbiorców w firmie.`
              : "Żaden automatyczny mail nie wyjdzie do nikogo w firmie, dopóki wysyłka nie zostanie włączona ponownie."}
          </p>
          {pendingRequired && (
            <div className="space-y-1">
              <label htmlFor="required-mail-pause-reason" className="font-medium">
                Powód wstrzymania
              </label>
              <p className="text-xs text-muted-foreground">
                Ten mail niesie sprawy, na które ktoś czeka. Powód trafi do Historii zdarzeń
                i do „Moje konto” każdej osoby, która go dostaje.
              </p>
              <Textarea
                id="required-mail-pause-reason"
                rows={3}
                maxLength={500}
                value={pauseReason}
                onChange={(event) => setPauseReason(event.target.value)}
              />
            </div>
          )}
          {pendingRequired ? null : onGoToMine ? (
            <Button
              variant="tertiary"
              className="h-auto px-0"
              onClick={() => {
                setOffOpen(false);
                onGoToMine();
              }}
            >
              Chcę wyłączyć tylko sobie
            </Button>
          ) : (
            <Link
              href="/settings?item=my-notifications"
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              Chcę wyłączyć tylko sobie
            </Link>
          )}
        </div>
      </AppModal>
    </div>
  );
}
