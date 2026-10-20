/**
 * `/preview/hr-agreements` (umowy z ludźmi, etap 5, E5): prawdziwe komponenty
 * na danych fikcyjnych, ZERO prób żądania — także z otwartym oknem nowej umowy.
 */
import { render, screen, within } from "@testing-library/react";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-agreements",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrAgreementsPreviewPage from "../hr-agreements/page";

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

describe("/preview/hr-agreements", () => {
  it("Kadry: umowa i aneksy osoby z kanałem podpisu", async () => {
    window.history.replaceState({}, "", "/preview/hr-agreements");
    render(<HrAgreementsPreviewPage />);
    expect(await screen.findByRole("button", { name: /Nowa umowa albo aneks/ })).toBeInTheDocument();
    expect(screen.getByText("wysłana do podpisu")).toBeInTheDocument();
    expect(screen.getByText(/ręcznie, ze skanem/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("okno nowej umowy: wzory i co NEXUS zrobi po podpisie", async () => {
    window.history.replaceState({}, "", "/preview/hr-agreements?state=new");
    render(<HrAgreementsPreviewPage />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Po podpisaniu NEXUS sam:")).toBeInTheDocument();
    expect(
      within(dialog).getByText("przekaże dane do Symfonii przy najbliższym eksporcie"),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("do wyjaśnienia: nieudana wysyłka i umowa poza kartoteką", async () => {
    window.history.replaceState({}, "", "/preview/hr-agreements?state=issues");
    render(<HrAgreementsPreviewPage />);
    expect(await screen.findByText(/Autenti nie przyjęło umowy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przepisz ponownie" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Płace: podgląd bez akcji", async () => {
    window.history.replaceState({}, "", "/preview/hr-agreements?state=payroll");
    render(<HrAgreementsPreviewPage />);
    expect(await screen.findByText("wysłana do podpisu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nowa umowa albo aneks/ })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("wzory umów z wersjami i przełącznikiem modułu", async () => {
    window.history.replaceState({}, "", "/preview/hr-agreements?state=templates");
    render(<HrAgreementsPreviewPage />);
    expect(await screen.findByRole("heading", { name: "Wzory umów z pracownikami" })).toBeInTheDocument();
    expect(screen.getByText("wersja 3")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Umowy z ludźmi włączone" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
