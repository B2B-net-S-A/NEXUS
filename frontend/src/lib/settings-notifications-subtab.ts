// Zakładka ekranu Ustawienia → Powiadomienia wybierana adresem (`?sub=`).
//
// Ten sam wzorzec co `settings-admin-subtab.ts`: efekt zależy od WARTOŚCI
// parametru (miękka nawigacja nie odmontowuje strony), a wybór użytkownika
// trafia do adresu przez History API. Różnica: zakładka domyślna zależy od
// pozycji, z której ekran otwarto („Moje powiadomienia” → „moje”,
// „Powiadomienia” w Systemie → „role”), a część zakładek widzi tylko admin.
import { useCallback, useEffect, useState } from "react";

export const NOTIFICATIONS_SUBTAB_KEYS = ["moje", "role", "maile", "etapy"] as const;

export type NotificationsSubTab = (typeof NOTIFICATIONS_SUBTAB_KEYS)[number];

/** Nazwa parametru w adresie: `/settings?item=notifications&sub=maile`. */
export const NOTIFICATIONS_SUBTAB_PARAM = "sub";

export function isNotificationsSubTab(
  value: string | null | undefined,
): value is NotificationsSubTab {
  return (
    typeof value === "string" &&
    (NOTIFICATIONS_SUBTAB_KEYS as readonly string[]).includes(value)
  );
}

/**
 * Zakładka do pokazania: żądana, jeśli istnieje i konto ją widzi; inaczej
 * domyślna; a gdy i tej konto nie widzi — pierwsza dostępna („moje”).
 */
export function resolveNotificationsSubTab(
  requested: string | null | undefined,
  available: readonly NotificationsSubTab[],
  fallback: NotificationsSubTab,
): NotificationsSubTab {
  if (isNotificationsSubTab(requested) && available.includes(requested)) {
    return requested;
  }
  if (available.includes(fallback)) return fallback;
  return available[0] ?? "moje";
}

/** Zapisz zakładkę w adresie bez nawigacji; domyślna nie zostawia `?sub=`. */
export function writeNotificationsSubTabToUrl(
  sub: NotificationsSubTab,
  defaultTab: NotificationsSubTab,
): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if (sub === defaultTab) params.delete(NOTIFICATIONS_SUBTAB_PARAM);
  else params.set(NOTIFICATIONS_SUBTAB_PARAM, sub);
  const query = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
}

export function useNotificationsSubTab(
  requestedSub: string | null,
  available: readonly NotificationsSubTab[],
  defaultTab: NotificationsSubTab,
  onSelectSub: (
    sub: NotificationsSubTab,
    defaultTab: NotificationsSubTab,
  ) => void = writeNotificationsSubTabToUrl,
): readonly [NotificationsSubTab, (sub: NotificationsSubTab) => void] {
  // Stan trzyma ŻYCZENIE (także nieznane albo niedostępne); o tym, co widać,
  // rozstrzyga `resolveNotificationsSubTab` przy każdym renderze — uprawnienia
  // konta dochodzą po hydratacji store'u.
  const [wanted, setWanted] = useState<string | null>(requestedSub);
  // Brak parametru to też wartość — link bez `?sub=` wraca do domyślnej.
  useEffect(() => {
    setWanted(requestedSub);
  }, [requestedSub]);
  const selectSub = useCallback(
    (sub: NotificationsSubTab) => {
      setWanted(sub);
      onSelectSub(sub, defaultTab);
    },
    [defaultTab, onSelectSub],
  );
  return [
    resolveNotificationsSubTab(wanted, available, defaultTab),
    selectSub,
  ] as const;
}
