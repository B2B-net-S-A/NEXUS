// Grupy zakładek profilu klienta (makieta 18.11.2026). Klucze `?tab=` się nie
// zmieniają — linki z powiadomień (`?tab=zamowienia`, `?tab=umowy-ramowe`)
// dalej otwierają tę samą treść, tylko w swojej grupie.
import type { ClientTab } from "@/lib/client-tab";
import type { SectionNavGroup } from "@/components/ds/SectionNav";

export interface ClientTabGroup {
  key: string;
  label: string;
  tabs: readonly ClientTab[];
}

/**
 * Kolejność = kolejność w pasku. Od 19.11.2026 (makieta „Klienci: nowe
 * ekrany”, wariant A, decyzja Artura) pięć sekcji nazwanych pytaniami zamiast
 * ośmiu grup: „Współpraca” była zbiorem zasad rekrutacji, startu konsultanta
 * i Delivery Leada, „Ludzie” mieszali się z „Konsultantami”, a zasady
 * rekrutacji nie stały w „Rekrutacjach”. Klucze `?tab=` bez zmian.
 */
export const CLIENT_TAB_GROUPS: readonly ClientTabGroup[] = [
  { key: "przeglad", label: "Przegląd", tabs: ["profil"] },
  // Kto od nas pracuje u klienta, na jakim zamówieniu, jak zaczyna i kto go
  // prowadzi po naszej stronie (Delivery Lead — także chip w nagłówku).
  {
    key: "nasi-ludzie",
    label: "Nasi ludzie",
    tabs: ["konsultanci", "zamowienia", "wejscie", "zespol"],
  },
  // Czego klient szuka i jak u niego rekrutujemy.
  { key: "rekrutacje", label: "Rekrutacje", tabs: ["projekty", "zasady", "materialy", "konflikty"] },
  // Z kim po stronie klienta rozmawiamy: kontakty, działy, sprzedaż.
  { key: "ludzie-klienta", label: "Ludzie klienta", tabs: ["kontakty", "ludzie", "sprzedaz"] },
  // Na jakich warunkach i ile to daje.
  {
    key: "umowa",
    label: "Umowa i pieniądze",
    tabs: ["umowy-ramowe", "stawki-ramowe", "raporty", "faktury", "analityka", "importy-md"],
  },
];

/** Nazwa podzakładki — krótsza niż dawna etykieta, bo grupa mówi resztę. */
export const CLIENT_SUBTAB_LABELS: Readonly<Record<ClientTab, string>> = {
  profil: "Przegląd",
  zamowienia: "Zamówienia",
  "importy-md": "Importy MD",
  // Od 19.11.2026 „Umowa” to jedna strona: umowy, stawki i raporty
  // (`stawki-ramowe` i `raporty` widać jako osobne pozycje tylko bez
  // podglądu umów — wtedy zostają same raporty).
  "umowy-ramowe": "Umowa",
  "stawki-ramowe": "Stawki i cennik",
  raporty: "Raporty dla klienta",
  faktury: "Faktury i rozliczenie",
  analityka: "Analityka",
  zasady: "Zasady rekrutacji",
  wejscie: "Start u klienta",
  zespol: "Delivery Lead",
  kontakty: "Kontakty",
  ludzie: "Działy i technologie",
  projekty: "Projekty",
  materialy: "Materiały dla rekruterów",
  konflikty: "Konflikty z kandydatami",
  sprzedaz: "Sprzedaż",
  konsultanci: "Konsultanci",
};

// Kotwice nowości (`data-tour`) prowadzące przeklikanie z listy klientów do
// zakładki: grupa „Ludzie klienta” otwiera od razu kontakty, w „Umowie
// i pieniądzach” trzeba jeszcze wybrać „Stawki i cennik”. Id kotwic zostały
// z ośmiu grup, bo prowadzą po nich wpisy nowości.
const GROUP_TOUR: Readonly<Record<string, string>> = {
  "ludzie-klienta": "client.sections.people", // data-tour="client.sections.people"
  umowa: "client.sections.contracts", // data-tour="client.sections.contracts"
};
// „Stawki i cennik” to od 19.11.2026 część strony „Umowa” — kotwica
// `client.sections.framework-rates` stoi na nagłówku tej części (`page.tsx`).
const TAB_TOUR: Readonly<Partial<Record<ClientTab, string>>> = {};

/**
 * Grupy z pozycjami, które ta osoba widzi (puste grupy odpadają). `meta` to
 * cicha liczba przy nazwie grupy, np. `{ "nasi-ludzie": "32" }`.
 */
export function clientSectionGroups(
  visibleTabs: readonly ClientTab[],
  meta: Readonly<Partial<Record<string, string>>> = {},
): SectionNavGroup[] {
  const visible = new Set(visibleTabs);
  return CLIENT_TAB_GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    meta: meta[group.key],
    tourId: GROUP_TOUR[group.key],
    items: group.tabs
      .filter((tab) => visible.has(tab))
      .map((tab) => ({ key: tab, label: CLIENT_SUBTAB_LABELS[tab], tourId: TAB_TOUR[tab] })),
  })).filter((group) => group.items.length > 0);
}
