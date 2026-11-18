import { describe, expect, it } from "vitest";

import { CLIENT_TAB_KEYS } from "@/lib/client-tab";
import { CLIENT_SUBTAB_LABELS, CLIENT_TAB_GROUPS, clientSectionGroups } from "@/lib/client-tab-groups";

describe("grupy sekcji profilu klienta (18.11.2026)", () => {
  it("każdy klucz `?tab=` należy do dokładnie jednej grupy — linki z powiadomień mają dokąd trafić", () => {
    const grouped = CLIENT_TAB_GROUPS.flatMap((group) => group.tabs);
    expect([...grouped].sort()).toEqual([...CLIENT_TAB_KEYS].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it("kolejność grup: Przegląd · Konsultanci · Umowy · Rozliczenia · Współpraca · Ludzie · Rekrutacje · Sprzedaż", () => {
    expect(CLIENT_TAB_GROUPS.map((group) => group.label)).toEqual([
      "Przegląd",
      "Konsultanci",
      "Umowy",
      "Rozliczenia",
      "Współpraca",
      "Ludzie",
      "Rekrutacje",
      "Sprzedaż",
    ]);
    // Raporty wynikają z umowy — stoją przy niej, nie pod „Więcej”.
    expect(CLIENT_TAB_GROUPS.find((group) => group.key === "umowy")?.tabs).toContain("raporty");
  });

  it("Konsultanci (18.11.2026): lista osób, a obok zamówienia i importy MD pod dawnymi kluczami", () => {
    expect(CLIENT_TAB_GROUPS.find((group) => group.key === "konsultanci")?.tabs).toEqual([
      "konsultanci",
      "zamowienia",
      "importy-md",
    ]);
  });

  it("każda podzakładka ma nazwę", () => {
    for (const key of CLIENT_TAB_KEYS) expect(CLIENT_SUBTAB_LABELS[key]).toBeTruthy();
  });

  it("puste grupy odpadają, a pozycje idą w kolejności grupy", () => {
    const groups = clientSectionGroups(["raporty", "profil", "kontakty"]);
    expect(groups.map((group) => [group.label, group.items.map((item) => item.key)])).toEqual([
      ["Przegląd", ["profil"]],
      ["Umowy", ["raporty"]],
      ["Ludzie", ["kontakty"]],
    ]);
  });
});
