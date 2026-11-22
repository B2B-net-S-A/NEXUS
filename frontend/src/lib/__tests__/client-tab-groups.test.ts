import { describe, expect, it } from "vitest";

import { CLIENT_TAB_KEYS } from "@/lib/client-tab";
import { CLIENT_SUBTAB_LABELS, CLIENT_TAB_GROUPS, clientSectionGroups } from "@/lib/client-tab-groups";

describe("sekcje profilu klienta (19.11.2026)", () => {
  it("każdy klucz `?tab=` należy do dokładnie jednej grupy — linki z powiadomień mają dokąd trafić", () => {
    const grouped = CLIENT_TAB_GROUPS.flatMap((group) => group.tabs);
    expect([...grouped].sort()).toEqual([...CLIENT_TAB_KEYS].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it("pięć sekcji (19.11.2026): Przegląd · Nasi ludzie · Rekrutacje · Ludzie klienta · Umowa i pieniądze", () => {
    expect(CLIENT_TAB_GROUPS.map((group) => group.label)).toEqual([
      "Przegląd",
      "Nasi ludzie",
      "Rekrutacje",
      "Ludzie klienta",
      "Umowa i pieniądze",
    ]);
    // Raporty wynikają z umowy — stoją przy niej.
    expect(CLIENT_TAB_GROUPS.find((group) => group.key === "umowa")?.tabs).toContain("raporty");
  });

  it("dawna „Współpraca” rozdzielona według czytelnika", () => {
    const groupOf = (tab: string) =>
      CLIENT_TAB_GROUPS.find((group) => (group.tabs as readonly string[]).includes(tab))?.label;
    // Zasady rekrutacji czyta rekruter, start konsultanta i DL — opiekun naszych ludzi.
    expect(groupOf("zasady")).toBe("Rekrutacje");
    expect(groupOf("wejscie")).toBe("Nasi ludzie");
    expect(groupOf("zespol")).toBe("Nasi ludzie");
    expect(groupOf("sprzedaz")).toBe("Ludzie klienta");
    expect(groupOf("importy-md")).toBe("Umowa i pieniądze");
  });

  it("Nasi ludzie: lista osób, zamówienia, start u klienta i Delivery Lead pod dawnymi kluczami", () => {
    expect(CLIENT_TAB_GROUPS.find((group) => group.key === "nasi-ludzie")?.tabs).toEqual([
      "konsultanci",
      "zamowienia",
      "wejscie",
      "zespol",
    ]);
  });

  it("każda podzakładka ma nazwę", () => {
    for (const key of CLIENT_TAB_KEYS) expect(CLIENT_SUBTAB_LABELS[key]).toBeTruthy();
  });

  it("puste grupy odpadają, a pozycje idą w kolejności grupy", () => {
    const groups = clientSectionGroups(["raporty", "profil", "kontakty"]);
    expect(groups.map((group) => [group.label, group.items.map((item) => item.key)])).toEqual([
      ["Przegląd", ["profil"]],
      ["Ludzie klienta", ["kontakty"]],
      ["Umowa i pieniądze", ["raporty"]],
    ]);
  });

  it("cicha liczba przy grupie (ile tam jest) trafia tylko do wskazanych grup", () => {
    const groups = clientSectionGroups(["profil", "konsultanci", "kontakty"], { "nasi-ludzie": "32" });
    expect(groups.map((group) => [group.key, group.meta])).toEqual([
      ["przeglad", undefined],
      ["nasi-ludzie", "32"],
      ["ludzie-klienta", undefined],
    ]);
  });

  it("dopisek z dymkiem: tekst stoi przy nazwie grupy, dymek mówi, co liczy", () => {
    const groups = clientSectionGroups(["konsultanci", "kontakty", "umowy-ramowe"], {
      "nasi-ludzie": { text: "6", title: "Nasi ludzie: 6 aktywnych kontraktów" },
      "ludzie-klienta": "4",
      umowa: { text: "do 31.12.2026", title: "Umowa ramowa: Umowa o usługi IT" },
    });
    expect(groups.map((group) => [group.key, group.meta, group.metaTitle])).toEqual([
      ["nasi-ludzie", "6", "Nasi ludzie: 6 aktywnych kontraktów"],
      ["ludzie-klienta", "4", undefined],
      ["umowa", "do 31.12.2026", "Umowa ramowa: Umowa o usługi IT"],
    ]);
  });
});
