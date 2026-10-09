"use client";

import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useMyEmailNotifications,
  useSetMyEmailNotification,
  type MyEmailNotification,
} from "@/lib/api/emailNotifications";

function EmailRow({
  item,
  pending,
  onToggle,
}: {
  item: MyEmailNotification;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const switchId = `my-email-${item.id}`;
  // Zdanie „wyłączone przez Ciebie” powtarzałoby pozycję przełącznika.
  const note = item.state === "self_off" ? null : item.note;
  return (
    <li className="flex items-start gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <label htmlFor={switchId} className="text-sm font-medium text-foreground">
          {item.label}
        </label>
        <p className="mt-0.5 text-xs text-muted-foreground">{item.description}</p>
        {note && (
          <p
            id={`${switchId}-note`}
            className="mt-1 text-xs font-medium text-warning-muted-foreground"
          >
            {note}
          </p>
        )}
      </div>
      <Switch
        id={switchId}
        checked={item.self_enabled}
        disabled={pending}
        onCheckedChange={onToggle}
        aria-describedby={note ? `${switchId}-note` : undefined}
      />
    </li>
  );
}

/**
 * „Maile do Ciebie” w zakładce „Moje”: każdy mail, który może trafić do tego
 * konta, z własnym wyłącznikiem. Przełącznik pokazuje WYBÓR konta; gdy mail
 * i tak nie przychodzi (firmowo wyłączony, wyciszona kategoria dzwonka),
 * mówi to zdanie pod opisem. Dzwonek i zadania zostają bez zmian.
 */
export function MyEmailNotificationsCard() {
  const query = useMyEmailNotifications();
  const mutation = useSetMyEmailNotification();
  const pendingKind = mutation.isPending ? mutation.variables?.kind : null;

  return (
    <section aria-labelledby="my-emails-heading" className="space-y-2">
      <h2 id="my-emails-heading" className="text-sm font-semibold text-foreground">
        Maile do Ciebie
      </h2>
      <p className="text-sm text-muted-foreground">
        Maile, które NEXUS wysyła na Twój adres. Każdy możesz wyłączyć tylko
        sobie — powiadomienie w dzwonku i zadanie w „Czeka na Ciebie” zostają.
      </p>

      {query.isError && (
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
        <>
          {!query.data.channel_ready && (
            <p
              role="status"
              className="rounded-lg border border-warning/30 bg-warning-muted px-4 py-3 text-sm text-warning-muted-foreground"
            >
              Wysyłka maili z NEXUSA nie jest teraz skonfigurowana — żaden
              z tych maili nie wychodzi. Twoje ustawienia zostają zapisane.
            </p>
          )}
          {query.data.items.length > 0 ? (
            <ul className="divide-y divide-border rounded-xl border border-border bg-card">
              {query.data.items.map((item) => (
                <EmailRow
                  key={item.id}
                  item={item}
                  pending={pendingKind === item.id}
                  onToggle={(enabled) =>
                    mutation.mutate({ kind: item.id, enabled })
                  }
                />
              ))}
            </ul>
          ) : (
            <p className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
              Na Twoje konto nie trafia żaden z automatycznych maili NEXUSA.
            </p>
          )}
          {query.data.not_applicable.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer font-medium text-primary">
                Maile, które nie dotyczą Twojej roli (
                {query.data.not_applicable.length})
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
                {query.data.not_applicable.map((item) => (
                  <li key={item.id}>{item.label}</li>
                ))}
              </ul>
            </details>
          )}
          {query.data.always_on.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Zawsze przychodzą maile o bezpieczeństwie konta:{" "}
              {query.data.always_on
                .map((item) => item.label.toLocaleLowerCase("pl"))
                .join(", ")}
              .
            </p>
          )}
        </>
      )}
    </section>
  );
}

export default MyEmailNotificationsCard;
