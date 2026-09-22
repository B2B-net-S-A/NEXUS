import { describe, expect, it } from "vitest";
import {
  legacyRedirectTarget,
  resolveClientsMine,
  resolveClientsView,
  resolveContractsView,
} from "@/lib/clients-workspace";

describe("clients-workspace", () => {
  it("„Moi klienci” domyślnie dla osób z przypisaniem, jawne mine=0 wygrywa", () => {
    expect(resolveClientsMine(true, null)).toBe(true);
    expect(resolveClientsMine(true, "1")).toBe(true);
    expect(resolveClientsMine(true, "0")).toBe(false);
    expect(resolveClientsMine(false, "1")).toBe(false);
    expect(resolveClientsMine(false, null)).toBe(false);
  });

  it("tryby ekranów: nieznana wartość = widok domyślny", () => {
    expect(resolveClientsView("contacts")).toBe("contacts");
    expect(resolveClientsView("bogus")).toBe("list");
    expect(resolveClientsView(null)).toBe("list");
    expect(resolveContractsView("order-mail")).toBe("order-mail");
    expect(resolveContractsView("operations")).toBe("operations");
    expect(resolveContractsView(null)).toBe("register");
  });

  it("przekierowanie ze starego adresu zachowuje parametry (doc z powiadomień)", () => {
    expect(
      legacyRedirectTarget("/contracts", { view: "order-mail" }, { doc: "5" }),
    ).toBe("/contracts?doc=5&view=order-mail");
    expect(
      legacyRedirectTarget("/clients", { view: "contacts" }, { view: "x", a: ["1", "2"] }),
    ).toBe("/clients?a=1&a=2&view=contacts");
    expect(legacyRedirectTarget("/clients", { mine: "1" }, {})).toBe("/clients?mine=1");
  });
});
