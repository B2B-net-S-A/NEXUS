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
 * Kolejność = kolejność w pasku. Rekord klienta w ośmiu grupach zamiast
 * dziewięciu zakładek i sześciu pod „Więcej”: wszystko o umowie (umowa ramowa,
 * stawki, raporty, których umowa wymaga) w „Umowach”, pieniądze
 * w „Rozliczeniach”, ludzie klienta w „Ludziach”.
 */
export const CLIENT_TAB_GROUPS: readonly ClientTabGroup[] = [
  { key: "przeglad", label: "Przegląd", tabs: ["profil"] },
  // 18.11.2026: kto u klienta pracuje — umowa i bieżące zamówienie w jednym
  // wierszu; zamówienia jako dokumenty i budżety MD obok (klucz `zamowienia`
  // bez zmian, linki z powiadomień trafiają do tej samej grupy).
  { key: "konsultanci", label: "Konsultanci", tabs: ["konsultanci", "zamowienia", "importy-md"] },
  { key: "umowy", label: "Umowy", tabs: ["umowy-ramowe", "stawki-ramowe", "raporty"] },
  { key: "rozliczenia", label: "Rozliczenia", tabs: ["faktury", "analityka"] },
  { key: "wspolpraca", label: "Współpraca", tabs: ["zasady", "wejscie", "zespol"] },
  { key: "ludzie", label: "Ludzie", tabs: ["kontakty", "ludzie"] },
  { key: "rekrutacje", label: "Rekrutacje", tabs: ["projekty", "materialy", "konflikty"] },
  { key: "sprzedaz", label: "Sprzedaż", tabs: ["sprzedaz"] },
];

/** Nazwa podzakładki — krótsza niż dawna etykieta, bo grupa mówi resztę. */
export const CLIENT_SUBTAB_LABELS: Readonly<Record<ClientTab, string>> = {
  profil: "Przegląd",
  zamowienia: "Zamówienia",
  "importy-md": "Importy MD",
  "umowy-ramowe": "Umowy i aneksy",
  "stawki-ramowe": "Stawki i cennik",
  raporty: "Raporty dla klienta",
  faktury: "Faktury i rozliczenie",
  analityka: "Analityka",
  zasady: "Zasady współpracy",
  wejscie: "Wejście u klienta",
  zespol: "Delivery Lead",
  kontakty: "Kontakty i relacje",
  ludzie: "Ludzie i technologie",
  projekty: "Projekty",
  materialy: "Materiały dla rekruterów",
  konflikty: "Konflikty z kandydatami",
  sprzedaz: "Sprzedaż",
  konsultanci: "Konsultanci",
};

/** Grupy z pozycjami, które ta osoba widzi (puste grupy odpadają). */
export function clientSectionGroups(visibleTabs: readonly ClientTab[]): SectionNavGroup[] {
  const visible = new Set(visibleTabs);
  return CLIENT_TAB_GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    items: group.tabs
      .filter((tab) => visible.has(tab))
      .map((tab) => ({ key: tab, label: CLIENT_SUBTAB_LABELS[tab] })),
  })).filter((group) => group.items.length > 0);
}
