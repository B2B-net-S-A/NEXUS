// Zakładka profilu klienta wybierana adresem — wyniesiona z komponentu strony,
// żeby dała się przetestować bez montowania całego ciężkiego profilu.
//
// `?tab=` jest LOAD-BEARING: trzy źródła powiadomień linkują wprost do
// zakładki, w której jest sprawa do załatwienia — `dl_alerts_scanner.py`,
// `dl_portal_expiry_scanner.py` i `pipeline.py`, wszystkie
// `/clients/{id}?tab=zamowienia`.
import { useCallback, useEffect, useState } from "react";

export type ClientTab =
  | "profil"
  // Karta klienta („Zasady współpracy"). Link „Edytuj kartę" ze strony
  // rekrutacji i z Pomocy prowadzi od rundy 6 audytu do Ustawień
  // (`clientPlaybookEditHref`), bo DL nie widzi profilu cudzego klienta.
  | "zasady"
  // Pakiet klienta „Wejście u klienta”: sprzęt, pierwszy dzień, dokumenty
  // i dostępy dla wejścia konsultanta (etap 3, 17.10.2026).
  | "wejscie"
  | "projekty"
  | "kontakty"
  | "umowy-ramowe"
  | "zamowienia"
  // Importy zużycia MD, które dotknęły zamówień klienta (ticket 7, 09.2026);
  // cel odsyłacza „Otwórz import →" z historii zamówienia.
  | "importy-md"
  // Faktury do klientów z KSeF dopasowane do zamówień (etap 5, E8).
  | "faktury"
  | "analityka"
  // „Ludzie i technologie” (22.10.2026): działy, drzewo osób i mapa
  // technologii w jednej zakładce. Zastępuje „Strukturę u klienta”
  // (`struktura`, 17.10.2026) i „Technologie” (`technologie`, 16.10.2026) —
  // dawne klucze w adresie prowadzą tu (`LEGACY_CLIENT_TABS`).
  | "ludzie"
  | "zespol";

export const CLIENT_TAB_KEYS: readonly ClientTab[] = [
  "profil",
  "zasady",
  "wejscie",
  "projekty",
  "kontakty",
  "umowy-ramowe",
  "zamowienia",
  "importy-md",
  "faktury",
  "analityka",
  "ludzie",
  "zespol",
] as const;

/**
 * Rzadkie zakładki pod „Więcej” w pasku (22.10.2026). Wybrana z menu stoi
 * w pasku, dopóki jest aktywna — inaczej nie byłoby widać, gdzie się jest.
 */
export const CLIENT_MORE_TABS: readonly ClientTab[] = ["importy-md", "faktury", "analityka"];

/**
 * Dawne zakładki → „Ludzie i technologie” z widokiem (linki z powiadomień,
 * historii opinii kontraktu i opieki sprzed 22.10.2026).
 */
export const LEGACY_CLIENT_TABS: Readonly<Record<string, "drzewo" | "mapa">> = {
  struktura: "drzewo",
  technologie: "mapa",
};

export function isClientTab(value: string | null): value is ClientTab {
  return value !== null && (CLIENT_TAB_KEYS as readonly string[]).includes(value);
}

/** Zakładka z adresu z dawnymi kluczami („struktura”, „technologie” → „ludzie”). */
export function clientTabFrom(value: string | null): ClientTab | null {
  if (value !== null && value in LEGACY_CLIENT_TABS) return "ludzie";
  return isClientTab(value) ? value : null;
}

/**
 * Zakładka sterowana adresem, ale nadal przełączalna ręcznie.
 *
 * Sam inicjalizator `useState` NIE wystarcza — odpala się raz na cykl życia
 * komponentu. Użytkownik już na `/clients/1` klikający powiadomienie do
 * `/clients/1?tab=zamowienia` dostaje MIĘKKĄ nawigację App Routera: adres się
 * zmienia, komponent się nie odmontowuje, stan zostaje na „profil" i link
 * prowadzi donikąd. Dla Delivery Leada, który siedzi na profilu klienta
 * i klika jego powiadomienia, to jest scenariusz codzienny, nie brzegowy.
 *
 * Efekt zależy od WARTOŚCI parametru, nie od tożsamości obiektu
 * `searchParams` — więc ręczne kliknięcie w inną zakładkę nie jest cofane
 * przy najbliższym renderze (parametr się nie zmienił, efekt nie wchodzi).
 */
export function useClientTab(
  requestedTab: string | null,
  // Zapis wybranej zakładki do adresu (`router.replace` po stronie strony).
  // Bez tego adres zostawał na zakładce, z której się weszło: F5 wracało na
  // nią, a ponowny link z powiadomienia do tej samej `?tab=` nie zmieniał
  // WARTOŚCI parametru, więc efekt niżej nie wchodził i zakładka stała.
  onSelectTab?: (tab: ClientTab) => void,
): readonly [ClientTab, (tab: ClientTab) => void, (tab: ClientTab) => void] {
  const [activeTab, setActiveTab] = useState<ClientTab>(
    () => clientTabFrom(requestedTab) ?? "profil",
  );
  useEffect(() => {
    const tab = clientTabFrom(requestedTab);
    if (tab) setActiveTab(tab);
  }, [requestedTab]);
  const selectTab = useCallback(
    (tab: ClientTab) => {
      setActiveTab(tab);
      if (tab !== requestedTab) onSelectTab?.(tab);
    },
    [onSelectTab, requestedTab],
  );
  // [zakładka, zmiana stanu bez adresu, wybór użytkownika zapisywany w adresie]
  return [activeTab, setActiveTab, selectTab] as const;
}

/**
 * Zakładka, do której rola nie ma prawa, przełącza się na Profil — ale
 * dopiero po hydracji użytkownika (`ready`). Przy pełnym wczytaniu strony
 * pierwszy render ma `user = null`: „brak prawa” jest wtedy brakiem wiedzy,
 * a przełączenie nie byłoby już cofane (efekt `useClientTab` zależy od
 * wartości parametru, która się nie zmienia). Tak linki `?tab=umowy-ramowe`
 * z alertów i maili lądowały na Profilu (audyt 24.09.2026).
 */
export function useForbiddenTabFallback(
  activeTab: ClientTab,
  setActiveTab: (tab: ClientTab) => void,
  guardedTab: ClientTab,
  allowed: boolean,
  ready: boolean,
): void {
  useEffect(() => {
    if (ready && !allowed && activeTab === guardedTab) setActiveTab("profil");
  }, [activeTab, allowed, guardedTab, ready, setActiveTab]);
}

/**
 * Identyfikator z parametru adresu (`?order=`, `?group=`, `?framework=`)
 * albo `null`. Adres pisze człowiek i linki z powiadomień — „abc", „0",
 * „-3" czy „1.5" nie są celem, tylko brakiem celu.
 */
export function positiveIntParam(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value.trim())) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}
