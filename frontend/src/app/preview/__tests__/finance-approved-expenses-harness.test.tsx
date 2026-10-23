/**
 * `/preview/finance-approved-expenses` (Zgody, etap 3 — 0486): prawdziwa
 * zakładka Finansów „Wydatki ze zgodą” na danych fikcyjnych, ZERO prób
 * żądania — w każdym z trzech stanów i po wyborze faktury bez zgody.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/finance-approved-expenses",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import FinanceApprovedExpensesPreviewPage from "../finance-approved-expenses/page";

vi.setConfig({ testTimeout: 20_000 });

const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

function open(search: string) {
  window.history.replaceState({}, "", `/preview/finance-approved-expenses${search}`);
  render(<FinanceApprovedExpensesPreviewPage />);
}

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/finance-approved-expenses", () => {
  it("do rozliczenia: kafle, faktura w progu i faktura +18% z dopłatą w drodze", async () => {
    open("");
    expect(await screen.findByText("Czeka na fakturę")).toBeInTheDocument();
    expect(screen.getByText("Faktury kosztowe bez zgody")).toBeInTheDocument();
    expect(screen.getByText("mieści się")).toBeInTheDocument();
    expect(screen.getByText("+18% vs zgoda")).toBeInTheDocument();
    expect(screen.getByText(/dopłata 162 zł: czeka/)).toBeInTheDocument();
    const settle = screen.getAllByRole("button", { name: "Rozliczone" });
    // Faktura ponad próg z dopłatą w drodze — „Rozliczone” wyłączone.
    expect(settle.some((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(screen.getByText(/Premie poza umową tylko sumą/)).toBeInTheDocument();
    // Zgoda „raz” bez dokumentu nie wygasa (decyzja Artura 22.10.2026).
    expect(screen.getByText("Kosz upominkowy dla klienta")).toBeInTheDocument();
    expect(screen.queryAllByText(/^wygasa/)).toEqual([]);
    expect(attempted()).toEqual([]);
  });

  it("subskrypcje: odnowienie roczne za 9 dni i pytanie wysłane", async () => {
    open("?state=subscriptions&expTab=subscriptions");
    expect(await screen.findByText(/za 9 dni · rocznie · pytanie wysłane/)).toBeInTheDocument();
    expect(screen.getByText("Baza kontaktów — abonament")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("faktury bez zgody: podpowiedź zgody, stały koszt i przypinanie bez zapytań", async () => {
    const user = userEvent.setup();
    open("?state=invoices&expTab=invoices");
    expect(await screen.findByText("Pasuje kwotą")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stały koszt — bez zgody" })).toBeInTheDocument();
    expect(screen.getByText(/Stałe koszty bez zgody · 1/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Biuro Rachunkowe Przykładowe/ }));
    await user.click(screen.getByRole("button", { name: "Przypnij do zgody" }));
    const search = screen.getByRole("textbox", { name: "Szukaj zgody po tytule" });
    expect(within(search.parentElement as HTMLElement).getByText("Monitor do pracy zdalnej")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
