/**
 * Siedem zakładek Sprzedaży (decyzja Artura 11.11.2026): Kontakty, Zadania i Podsumowanie
 * mają stare adresy, ale wchodzi się do nich przełącznikiem w zakładce-rodzicu.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
let pathname = "/sales/my-day";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => pathname }));
vi.mock("@/components/RequirePermission", () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../SalesMailboxStatus", () => ({ SalesMailboxStatus: () => null }));

import { activeSection, SalesShell, tabOf } from "../SalesShell";

const shell = () =>
  render(
    <SalesShell title="Sprzedaż">
      <p>treść</p>
    </SalesShell>,
  );

beforeEach(() => {
  push.mockClear();
  pathname = "/sales/my-day";
});

describe("zakładki Sprzedaży", () => {
  it("pasek ma siedem zakładek bez Kontaktów, Zadań i Podsumowania", () => {
    shell();
    const tabs = screen.getByRole("tablist", { name: "Sprzedaż" });
    const labels = Array.from(tabs.querySelectorAll("[role=tab]")).map((tab) => tab.textContent);
    expect(labels).toEqual(["Mój dzień", "Dzwonienie", "Szanse", "Oferty", "Firmy", "Spotkania", "Leady"]);
  });

  it("stare adresy podświetlają zakładkę-rodzica", () => {
    expect(tabOf(activeSection("/sales/contacts"))).toBe("companies");
    expect(tabOf(activeSection("/sales/tasks"))).toBe("my-day");
    expect(tabOf(activeSection("/sales/summary"))).toBe("opportunities");
    expect(tabOf(activeSection("/sales/offers"))).toBe("offers");
  });

  it("w Firmach przełącznik „Firmy | Osoby” prowadzi do Kontaktów", () => {
    pathname = "/sales/contacts";
    shell();
    const views = screen.getByRole("tablist", { name: "Widok" });
    expect(screen.getByRole("tab", { name: "Osoby" })).toHaveAttribute("aria-selected", "true");
    expect(views.textContent).toContain("Firmy");
    fireEvent.click(screen.getByRole("tab", { name: "Firmy", selected: false }));
    expect(push).toHaveBeenCalledWith("/sales/companies");
  });

  it("„Mój dzień” prowadzi do wszystkich zadań, a Szanse do Podsumowania", () => {
    shell();
    fireEvent.click(screen.getByRole("tab", { name: "Wszystkie zadania" }));
    expect(push).toHaveBeenCalledWith("/sales/tasks");
    pathname = "/sales/opportunities";
    shell();
    fireEvent.click(screen.getByRole("tab", { name: "Podsumowanie" }));
    expect(push).toHaveBeenCalledWith("/sales/summary");
  });

  it("Oferty nie mają przełącznika", () => {
    pathname = "/sales/offers";
    shell();
    expect(screen.queryByRole("tablist", { name: "Widok" })).toBeNull();
  });
});
