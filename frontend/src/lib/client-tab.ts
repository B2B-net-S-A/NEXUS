// Zakładka profilu klienta wybierana adresem — wyniesiona z komponentu strony,
// żeby dała się przetestować bez montowania całego ciężkiego profilu.
//
// `?tab=` jest LOAD-BEARING: trzy źródła powiadomień linkują wprost do
// zakładki, w której jest sprawa do załatwienia — `dl_alerts_scanner.py`,
// `dl_portal_expiry_scanner.py` i `pipeline.py`, wszystkie
// `/clients/{id}?tab=zamowienia`.
import { useEffect, useState } from "react";

export type ClientTab =
  | "profil"
  // Karta klienta („Zasady współpracy") — cel linku „Edytuj kartę" ze strony
  // rekrutacji i z Pomocy → Klienci (`/clients/{id}?tab=zasady`).
  | "zasady"
  | "projekty"
  | "kontakty"
  | "umowy-ramowe"
  | "zamowienia"
  | "analityka"
  | "zespol";

export const CLIENT_TAB_KEYS: readonly ClientTab[] = [
  "profil",
  "zasady",
  "projekty",
  "kontakty",
  "umowy-ramowe",
  "zamowienia",
  "analityka",
  "zespol",
] as const;

export function isClientTab(value: string | null): value is ClientTab {
  return value !== null && (CLIENT_TAB_KEYS as readonly string[]).includes(value);
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
): readonly [ClientTab, (tab: ClientTab) => void] {
  const [activeTab, setActiveTab] = useState<ClientTab>(() =>
    isClientTab(requestedTab) ? requestedTab : "profil",
  );
  useEffect(() => {
    if (isClientTab(requestedTab)) setActiveTab(requestedTab);
  }, [requestedTab]);
  return [activeTab, setActiveTab] as const;
}
