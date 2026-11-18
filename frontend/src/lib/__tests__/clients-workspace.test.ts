import { describe, expect, it } from "vitest";
import {
  clientsMineToggleAvailable,
  legacyRedirectTarget,
  resolveClientsMine,
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

  it("DL z zakresem „assigned” nie ma „Moi / Wszyscy” — serwer i tak pokazuje tylko jego klientów", () => {
    expect(clientsMineToggleAvailable(true, "assigned")).toBe(false);
    expect(clientsMineToggleAvailable(true, "all")).toBe(true);
    // Stary cache bez pola: przełącznik zostaje, lista i tak idzie z serwera.
    expect(clientsMineToggleAvailable(true, undefined)).toBe(true);
    expect(clientsMineToggleAvailable(false, "all")).toBe(false);
  });

  it("tryby Kontraktów: nieznana wartość = widok domyślny (Klienci od 18.11.2026 nie mają trybów)", () => {
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
