/**
 * `/preview/sales` — tablica i lista szans na fikcyjnych danych, ZERO prób żądania.
 */
import { render, screen } from "@testing-library/react";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/sales",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import SalesPreviewPage from "../sales/page";

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

describe("/preview/sales", () => {
  it("tablica: kolumny etapów bez przegranych, liczby lejka, ostrzeżenie o zaniedbanej szansie", async () => {
    window.history.replaceState({}, "", "/preview/sales");
    render(<SalesPreviewPage />);

    expect(await screen.findByRole("button", { name: /Bank Przykładowy · Zespół QA/ })).toBeInTheDocument();
    expect(screen.getByText("Spotkanie kwalifikujące")).toBeInTheDocument();
    expect(screen.queryByText("Przegrana")).toBeNull();
    expect(screen.getByText("otwartych szans")).toBeInTheDocument();
    expect(screen.getByText(/bez kontaktu 21 dni/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("lista: wiersz z firmą i etapem", async () => {
    window.history.replaceState({}, "", "/preview/sales?view=list");
    render(<SalesPreviewPage />);

    expect(await screen.findByRole("link", { name: "Data engineering" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Wartość (zł)" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
