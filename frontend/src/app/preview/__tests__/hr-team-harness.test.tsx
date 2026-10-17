/**
 * `/preview/hr-team` (etap 2, „Ludzie → Mój zespół”): prawdziwy ekran
 * przełożonego na danych fikcyjnych, ZERO prób żądania. Premie z kwotą bez
 * stawek, kolumna „Nieobecności” (pula tylko u osoby z pulą), rodzaj
 * nieobecności dla przełożonej (D6), Kadry bez Płac — bez kolumny premii.
 */
import { render, screen, within } from "@testing-library/react";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-team",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrTeamPreviewPage from "../hr-team/page";

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

describe("/preview/hr-team", () => {
  it("przełożona: dziś, nieobecności, miesiąc, premie i sprawy do decyzji", async () => {
    window.history.replaceState({}, "", "/preview/hr-team");
    render(<HrTeamPreviewPage />);

    const ewa = await screen.findByRole("row", { name: /^Ewa Makietowa/ });
    expect(ewa).toHaveTextContent("Przerwa w świadczeniu usług do");
    const ola = screen.getByRole("row", { name: /^Ola Przykładowa/ });
    expect(ola).toHaveTextContent("zastępuje: Ewa Makietowa");
    expect(ola).toHaveTextContent("zaplanowane 8 dni");
    // Wiersz puli z zerem na B2B: liczy się płatna pula, nie sam wiersz.
    expect(ola).not.toHaveTextContent(/zostało/);
    expect(ola).toHaveTextContent("1 propozycja — decydują Płace");
    // B2B (D5): bez wniosków do decyzji.
    expect(within(ola).queryByRole("link", { name: /^wniosek / })).toBeNull();
    const julia = screen.getByRole("row", { name: /^Julia Próbna/ });
    expect(julia).toHaveTextContent("zostało 14 dni urlopu");
    expect(julia).toHaveTextContent("UoP");
    expect(within(julia).getByRole("link", { name: /^wniosek / })).toHaveAttribute(
      "href",
      "/people/approvals",
    );
    // Student na zleceniu (D8): sam znacznik — daty zwolnienia widzą Kadry i Płace.
    const adam = screen.getByRole("row", { name: /^Adam Wzorcowy/ });
    expect(adam).toHaveTextContent("Zlecenie · student");
    expect(adam).not.toHaveTextContent(/składki od/);
    expect(screen.getByRole("columnheader", { name: "Nieobecności" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Premie w drodze" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Mój zespół" })).toHaveAttribute("aria-selected", "true");
    expect(attempted()).toEqual([]);
  });

  it("Kadry bez Płac: zespół Marty bez kolumny premii", async () => {
    window.history.replaceState({}, "", "/preview/hr-team?as=hr");
    render(<HrTeamPreviewPage />);

    expect(await screen.findByRole("row", { name: /^Tomasz Podglądowy/ })).toHaveTextContent(
      "odchodzi",
    );
    expect(screen.queryByRole("columnheader", { name: "Premie w drodze" })).toBeNull();
    expect(screen.getByRole("combobox", { name: "Zespół przełożonego" })).toHaveTextContent(
      "Marta Fikcyjna",
    );
    expect(attempted()).toEqual([]);
  });
});
