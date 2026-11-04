/**
 * `/preview/client-invoicing` (faktury do klientów, E8 cz. 1): prawdziwe
 * komponenty na danych fikcyjnych, ZERO prób żądania w każdym stanie.
 */
import { render, screen, within } from "@testing-library/react";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/client-invoicing",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import ClientInvoicingPreviewPage from "../client-invoicing/page";

vi.setConfig({ testTimeout: 20_000 });

const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/client-invoicing", () => {
  it("DL: do faktury obok faktur z KSeF, bez zapytań", async () => {
    window.history.replaceState({}, "", "/preview/client-invoicing");
    render(<ClientInvoicingPreviewPage />);
    const row = await screen.findByTestId("billing-row-g13");
    expect(within(row).getByText(/różnica do sprawdzenia/)).toBeInTheDocument();
    expect(screen.getByTestId("billing-row-g14")).toHaveTextContent("jeszcze nie wystawiona");
    expect(attempted()).toEqual([]);
  });

  it.each(["finance", "to-invoice", "credits"])("Finanse (%s): bez zapytań", async (state) => {
    window.history.replaceState({}, "", `/preview/client-invoicing?state=${state}`);
    render(<ClientInvoicingPreviewPage />);
    expect(await screen.findByText(/spółka jako sprzedawca/)).toBeInTheDocument();
    if (state === "finance") {
      expect(await screen.findByTestId("sales-invoice-4")).toBeInTheDocument();
    } else if (state === "to-invoice") {
      expect(await screen.findByText("Ubezpieczenia Przykładowe S.A.")).toBeInTheDocument();
    } else {
      expect(await screen.findByText("Zapłata za usługi")).toBeInTheDocument();
    }
    expect(attempted()).toEqual([]);
  });
});
