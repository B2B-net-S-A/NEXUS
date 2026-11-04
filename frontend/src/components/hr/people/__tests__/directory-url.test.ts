import { describe, expect, it } from "vitest";

import { directoryHref, readDirectoryParams, structureRedirectHref } from "../directory-url";

describe("filtry katalogu w adresie", () => {
  it("czyta znane wartości, nieznane pomija", () => {
    expect(
      readDirectoryParams(
        new URLSearchParams("q=Ola&department=Delivery&form=uop&status=away&view=schemat"),
      ),
    ).toEqual({ q: "Ola", department: "Delivery", form: "uop", status: "away", view: "schemat" });
    expect(readDirectoryParams(new URLSearchParams("form=etat&status=x&view=tabela&department=%20"))).toEqual({
      q: "",
      department: null,
      form: null,
      status: null,
      view: "lista",
    });
    expect(readDirectoryParams(null, "schemat").view).toBe("schemat");
  });

  it("zapis zostawia obce parametry i nie zapisuje wartości domyślnych", () => {
    const filters = { q: "  ", department: null, form: null, status: null, view: "lista" as const };
    expect(directoryHref("/people", "?as=hr&q=stare", filters)).toBe("/people?as=hr");
    expect(
      directoryHref("/people", "", { ...filters, q: "Ola K", department: "Bez działu", view: "schemat" }),
    ).toBe("/people?q=Ola+K&department=Bez+dzia%C5%82u&view=schemat");
    // Harness Struktury: domyślny widok to schemat — w adresie zostaje „lista”.
    expect(directoryHref("/preview/hr-structure", "", filters, "schemat")).toBe(
      "/preview/hr-structure?view=lista",
    );
  });

  it("stary adres Struktury → schemat katalogu", () => {
    expect(structureRedirectHref("")).toBe("/people?view=schemat");
    expect(structureRedirectHref("q=Ola")).toBe("/people?q=Ola&view=schemat");
  });
});
