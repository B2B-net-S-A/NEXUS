"use client";

import { Lock } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useNotificationPreferences,
  useSetNotificationCategoryMuted,
  type NotificationCategoryPreference,
} from "@/lib/api/notificationPreferences";

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
  const enabled = !category.muted;
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
      </div>
      <Switch
        id={switchId}
        checked={enabled}
        disabled={category.mandatory || pending}
        onCheckedChange={onToggle}
        aria-describedby={`${switchId}-state`}
      />
      <span id={`${switchId}-state`} className="sr-only">
        {category.mandatory
          ? "Kategoria obowiązkowa"
          : enabled
            ? "Włączone"
            : "Wyłączone"}
      </span>
    </li>
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
    </div>
  );
}
