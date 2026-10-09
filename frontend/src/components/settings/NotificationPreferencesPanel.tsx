"use client";

import { Lock } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useNotificationPreferences,
  useSetNotificationCategoryMuted,
  type NotificationCategoryPreference,
} from "@/lib/api/notificationPreferences";
import {
  useUpdateUserPreferences,
  useUserPreferences,
} from "@/lib/api/userPreferences";

function receivedLabel(count: number): string {
  return `${count} w ostatnich 30 dniach`;
}

function CategoryRow({
  category,
  pending,
  onToggle,
}: {
  category: NotificationCategoryPreference;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  // Wyłączenie dla roli wygrywa z własnym przełącznikiem — pokazujemy stan
  // faktyczny (nic nie przychodzi), a nie zapisane życzenie konta.
  const roleMuted = category.role_muted === true;
  const enabled = !category.muted && !roleMuted;
  const switchId = `notif-cat-${category.key}`;
  return (
    <li className="flex items-start gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <label
          htmlFor={switchId}
          className="text-sm font-medium text-foreground"
        >
          {category.label}
        </label>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {category.description}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {receivedLabel(category.received_30d)}
          {category.mandatory && (
            <span className="ml-2 inline-flex items-center gap-1 text-muted-foreground">
              <Lock className="h-3 w-3" aria-hidden />
              Zawsze włączone
            </span>
          )}
        </p>
        {roleMuted && (
          <p className="mt-1 text-xs font-medium text-warning-muted-foreground">
            Wyłączone dla Twojej roli przez administratora
          </p>
        )}
      </div>
      <Switch
        id={switchId}
        checked={enabled}
        disabled={category.mandatory || roleMuted || pending}
        onCheckedChange={onToggle}
        aria-describedby={`${switchId}-state`}
      />
      <span id={`${switchId}-state`} className="sr-only">
        {category.mandatory
          ? "Kategoria obowiązkowa"
          : roleMuted
            ? "Wyłączone dla Twojej roli przez administratora"
            : enabled
              ? "Włączone"
              : "Wyłączone"}
      </span>
    </li>
  );
}

/**
 * Własny wyłącznik porannego skrótu. Karta jest tylko dla kont, których rola
 * w ogóle dostaje skrót (`daily_digest_email_available`) — pozostałym
 * przełącznik niczego by nie zmieniał.
 */
function DigestEmailCard() {
  const query = useUserPreferences();
  const mutation = useUpdateUserPreferences();
  const switchId = "notif-daily-digest-email";

  if (query.isError) {
    return (
      <div
        role="alert"
        className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
      >
        Nie udało się wczytać ustawień maili.{" "}
        <button
          type="button"
          onClick={() => query.refetch()}
          className="font-medium underline"
        >
          Ponów
        </button>
      </div>
    );
  }
  if (!query.isSuccess || !query.data.daily_digest_email_available) return null;

  return (
    <section aria-labelledby="notif-mail-heading" className="space-y-2">
      <h2 id="notif-mail-heading" className="text-sm font-semibold text-foreground">
        Maile
      </h2>
      {mutation.isError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {apiErrorMessage(mutation.error, "Nie udało się zapisać zmiany.")}
        </div>
      )}
      <div className="flex items-start gap-4 rounded-xl border border-border bg-card px-4 py-3">
        <div className="min-w-0 flex-1">
          <label htmlFor={switchId} className="text-sm font-medium text-foreground">
            Poranny skrót „Twój dzień w NEXUSIE”
          </label>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Mail w dni robocze o 8:00 z tym, co na Ciebie czeka. Wyłączasz go
            tylko sobie.
          </p>
        </div>
        <Switch
          id={switchId}
          checked={query.data.daily_digest_email_enabled}
          disabled={mutation.isPending}
          onCheckedChange={(enabled) =>
            mutation.mutate({ daily_digest_email_enabled: enabled })
          }
        />
      </div>
    </section>
  );
}

export function NotificationPreferencesPanel() {
  const query = useNotificationPreferences();
  const mutation = useSetNotificationCategoryMuted();

  const pendingKey = mutation.isPending ? mutation.variables?.category : null;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Wybierz, które powiadomienia mają trafiać do dzwonka. Wyłączona
        kategoria znika z dzwonka i nie pokazuje się jako dymek na ekranie.
        Kategorię możesz też wyłączyć prosto z dzwonka ikoną dzwonka
        z kreską przy powiadomieniu.
      </p>

      {query.isError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          Nie udało się wczytać ustawień powiadomień.{" "}
          <button
            type="button"
            onClick={() => query.refetch()}
            className="font-medium underline"
          >
            Ponów
          </button>
        </div>
      )}

      {mutation.isError && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {apiErrorMessage(mutation.error, "Nie udało się zapisać zmiany.")}
        </div>
      )}

      {query.isPending && (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      )}

      {query.isSuccess && (
        <ul className="divide-y divide-border rounded-xl border border-border bg-card">
          {query.data.categories.map((category) => (
            <CategoryRow
              key={category.key}
              category={category}
              pending={pendingKey === category.key}
              onToggle={(enabled) =>
                mutation.mutate({ category: category.key, muted: !enabled })
              }
            />
          ))}
        </ul>
      )}

      <DigestEmailCard />
    </div>
  );
}
