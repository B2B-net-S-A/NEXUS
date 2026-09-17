// Zakładka strony /settings wybierana adresem (`?tab=`) — UAT M11-B01.
//
// Do 09.2026 zakładka żyła wyłącznie w `useState("integracje")`: kliknięcie
// nie zmieniało adresu, F5 i link `/settings?tab=administracja` zawsze
// otwierały Integracje. Wzorzec jak w `client-tab.ts` (tamten plik zostaje
// osobny — zna klucze profilu klienta).
import { useCallback, useEffect, useState } from "react";

export type SettingsTab =
  | "integracje"
  | "szablony"
  | "coaching"
  | "procesy"
  | "administracja"
  | "historia"
  | "konflikty"
  | "zaawansowane"
  | "pomoc";

export const SETTINGS_TAB_KEYS: readonly SettingsTab[] = [
  "integracje",
  "szablony",
  "coaching",
  "procesy",
  "administracja",
  "historia",
  "konflikty",
  "zaawansowane",
  "pomoc",
] as const;

export const DEFAULT_SETTINGS_TAB: SettingsTab = "integracje";

export function isSettingsTab(value: string | null): value is SettingsTab {
  return (
    value !== null && (SETTINGS_TAB_KEYS as readonly string[]).includes(value)
  );
}

/** Zapisz zakładkę w adresie bez nawigacji (History API, jak w /finance).
 *  Zakładka domyślna nie zostawia `?tab=` w adresie. */
export function writeSettingsTabToUrl(tab: SettingsTab): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if (tab === DEFAULT_SETTINGS_TAB) params.delete("tab");
  else params.set("tab", tab);
  // Podzakładka Administracji (`?sub=`, B42) należy tylko do tej zakładki —
  // przeniesiona na inną zostawiałaby w adresie stan, którego nikt nie czyta.
  if (tab !== "administracja") params.delete("sub");
  const query = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
}

/**
 * Sam inicjalizator `useState` NIE wystarcza — odpala się raz na cykl życia
 * komponentu, a link do `/settings?tab=…` kliknięty na `/settings` to MIĘKKA
 * nawigacja: adres się zmienia, komponent zostaje. Efekt zależy od WARTOŚCI
 * parametru, więc ręczny wybór zakładki nie jest cofany przy renderze.
 */
export function useSettingsTab(
  requestedTab: string | null,
  onSelectTab: (tab: SettingsTab) => void = writeSettingsTabToUrl,
): readonly [SettingsTab, (tab: SettingsTab) => void] {
  const [activeTab, setActiveTab] = useState<SettingsTab>(() =>
    isSettingsTab(requestedTab) ? requestedTab : DEFAULT_SETTINGS_TAB,
  );
  // Brak parametru to też wartość: zakładka domyślna nie trafia do adresu,
  // więc link „/settings” kliknięty na innej zakładce musi do niej wrócić.
  useEffect(() => {
    setActiveTab(isSettingsTab(requestedTab) ? requestedTab : DEFAULT_SETTINGS_TAB);
  }, [requestedTab]);
  const selectTab = useCallback(
    (tab: SettingsTab) => {
      setActiveTab(tab);
      onSelectTab(tab);
    },
    [onSelectTab],
  );
  return [activeTab, selectTab] as const;
}
