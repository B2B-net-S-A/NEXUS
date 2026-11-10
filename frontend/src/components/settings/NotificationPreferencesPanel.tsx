"use client";

import { Lock } from "lucide-react";

import { MyEmailNotificationsCard } from "@/components/settings/MyEmailNotificationsCard";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
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

const PIPELINE_CATEGORY = "pipeline";

/**
 * Ruchy kandydatów innych rekruterów w rekrutacjach, które konto prowadzi
 * (10.11.2026, `users.stage_moves_all_led_jobs`). Domyślnie tylko własni
 * kandydaci plus Interview Klient, Akceptacja i Zatrudniony.
 */
function StageMovesScope() {
  const query = useUserPreferences();
  const mutation = useUpdateUserPreferences();

  if (query.isError) {
    return (
      <p role="alert" className="mt-2 text-xs text-destructive">
        Nie udało się wczytać, czyje ruchy dostajesz.
      </p>
    );
  }
  if (!query.isSuccess) return null;

  const value = query.data.stage_moves_all_led_jobs ? "all" : "mine";
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-border bg-muted/40 px-3 py-2">
      <RadioGroup
        value={value}
        aria-label="Czyje ruchy dostajesz"
        disabled={mutation.isPending}
        onValueChange={(next) =>
          mutation.mutate({ stage_moves_all_led_jobs: next === "all" })
        }
      >
        <label className="flex items-start gap-2 text-xs" htmlFor="stage-moves-mine">
          <RadioGroupItem id="stage-moves-mine" value="mine" className="mt-0.5" />
          <span>
            <span className="block font-medium text-foreground">Tylko moi kandydaci</span>
            <span className="block text-muted-foreground">
              Plus Interview Klient, Akceptacja i Zatrudniony w rekrutacjach,
              które prowadzisz.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-xs" htmlFor="stage-moves-all">
          <RadioGroupItem id="stage-moves-all" value="all" className="mt-0.5" />
          <span>
            <span className="block font-medium text-foreground">
              Wszyscy kandydaci w rekrutacjach, które prowadzę
            </span>
            <span className="block text-muted-foreground">
              Każdy ruch innych rekruterów, także Screening i Odrzucony.
            </span>
          </span>
        </label>
      </RadioGroup>
      {mutation.isError && (
        <p role="alert" className="text-xs text-destructive">
          {apiErrorMessage(mutation.error, "Nie udało się zapisać wyboru.")}
        </p>
      )}
    </div>
  );
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
        {category.key === PIPELINE_CATEGORY && enabled && <StageMovesScope />}
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

export function NotificationPreferencesPanel() {
  const query = useNotificationPreferences();
  const mutation = useSetNotificationCategoryMuted();

  const pendingKey = mutation.isPending ? mutation.variables?.category : null;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Wybierz, które powiadomienia mają do Ciebie trafiać. Wyłączona
        kategoria znika z ikon górnego paska („CV”, „Rekrutacje”,
        „Wiadomości”, „Kalendarz”) i nie pokazuje się jako dymek na ekranie.
        Każda ikona ma jeden temat; reszta przychodzi jako dymek i mail.
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

      <MyEmailNotificationsCard />
    </div>
  );
}
