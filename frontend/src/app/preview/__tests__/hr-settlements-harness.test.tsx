/**
 * `/preview/hr-settlements` (rozliczenia zespołu, etap 4, M1–M4 i M7):
 * prawdziwe komponenty na danych fikcyjnych, ZERO prób żądania — także po
 * otwarciu porównania rozbieżności.
 */
import { render, screen, within } from "@testing-library/react";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-settlements",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrSettlementsPreviewPage from "../hr-settlements/page";

vi.setConfig({ testTimeout: 20_000 });

/** Każda PRÓBA żądania, także odrzucona przez interceptor harnessu. */
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

describe("/preview/hr-settlements", () => {
  it("B2B: kroki, „Do faktury” z kopiowaniem i faktura z KSeF", async () => {
    window.history.replaceState({}, "", "/preview/hr-settlements");
    render(<HrSettlementsPreviewPage />);
    expect(await screen.findByRole("list", { name: "Kroki rozliczenia" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Kopiuj pozycje/ })).toBeInTheDocument();
    expect(screen.getByText("FV 10/2026")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("zlecenie: brutto i PDF rozliczenia", async () => {
    window.history.replaceState({}, "", "/preview/hr-settlements?state=mandate");
    render(<HrSettlementsPreviewPage />);
    expect(await screen.findByText("Wynagrodzenie brutto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz PDF/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Płace: kolejka i porównanie rozbieżności", async () => {
    window.history.replaceState({}, "", "/preview/hr-settlements?state=mismatch&settlement=5003");
    render(<HrSettlementsPreviewPage />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Co się nie zgadza")).toBeInTheDocument();
    // Kolejka pod oknem (tło okna jest ukryte dla czytników ekranu).
    expect(screen.getByRole("button", { name: /Zatwierdź zgodne/, hidden: true })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Kadry: dane do rozliczeń z białą listą, rachunek tylko 4 cyframi", async () => {
    window.history.replaceState({}, "", "/preview/hr-settlements?state=billing");
    render(<HrSettlementsPreviewPage />);
    expect(await screen.findByText("Dane do rozliczeń")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz z białej listy/ })).toBeInTheDocument();
    expect(screen.getByText("•• 4521 · z białej listy VAT")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
