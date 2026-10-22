/**
 * `/preview/hr-cases` (makieta 11 „Ludzi w NEXUSIE”): prawdziwa tablica spraw
 * administracja@ i szczegół sprawy na danych fikcyjnych, ZERO prób żądania —
 * także po „Moje”, „Pokaż zamknięte”, kliknięciu karty i oknie „Edytuj”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/preview/hr-cases",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrCasesPreviewPage from "../hr-cases/page";

// Cała strona z prawdziwymi ekranami — na obciążonej maszynie 5 s nie wystarcza.
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
  push.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

const columnCount = (title: string) =>
  screen.getByRole("heading", { name: title, level: 3 }).nextSibling?.textContent;
const tiles = () => screen.getAllByRole("button", { name: /^Sprawa: / });

describe("/preview/hr-cases", () => {
  it("Opieka oglądana przez recepcję ze „Sprawami”: tylko „Do zrobienia” ze sprawami, bez zakładek opieki i Komunikatów", async () => {
    window.history.replaceState({}, "", "/preview/hr-cases?state=care-cases&tab=consultants");
    render(<HrCasesPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Opieka nad konsultantami" })).toBeInTheDocument();
    expect(screen.getByText("Sprawy administracja@ na jednej tablicy.")).toBeInTheDocument();
    // Stary link do „Konsultantów” i tak ląduje w „Do zrobienia”.
    expect(screen.getByRole("tab", { name: "Do zrobienia", selected: true })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Konsultanci" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Klienci" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Komunikaty/ })).toBeNull();
    expect(await screen.findAllByRole("button", { name: /^Sprawa: / })).not.toHaveLength(0);
    // Obsługa skrzynki zaczyna od wszystkich spraw — jak dawniej w „Ludziach”.
    expect(screen.getByRole("radio", { name: "Wszystkie" })).toBeChecked();
    expect(attempted()).toEqual([]);
  });

  it("tablica: Nowa 4 / W toku 2 / Czeka 1 / Zrobione, źródła i priorytety", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-cases");
    render(<HrCasesPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Sprawy administracja@" })).toBeInTheDocument();
    // Sprawy nie są już zakładką „Ludzi” (22.10.2026).
    expect(screen.queryByRole("tab", { name: /Sprawy/ })).toBeNull();
    expect(columnCount("Nowa")).toBe("4");
    expect(columnCount("W toku")).toBe("2");
    expect(columnCount("Czeka na kogoś")).toBe("1");
    // Wąska kolumna „Zrobione”: liczba z miesiąca, jedna sprawa z 30 dni na liście.
    expect(columnCount("Zrobione")).toBe("41");
    expect(screen.getByText(/^41 w tym miesiącu/)).toBeInTheDocument();
    const onboarding = screen.getByRole("listitem", { name: "Onboarding: Anna Kontraktorska" });
    expect(within(onboarding).getByText("z maila")).toBeInTheDocument();
    expect(within(onboarding).getByText("P1")).toBeInTheDocument();
    expect(within(onboarding).getByText(/kontrakt w NEXUSIE/)).toBeInTheDocument();
    expect(within(onboarding).getByRole("progressbar", { name: "Lista kontrolna: 1 z 4" })).toBeInTheDocument();
    expect(within(onboarding).getByText(/^za 2 dni · |^jutro · |^dziś · |^\d{2}\.\d{2}$/)).toBeInTheDocument();
    const offboarding = screen.getByRole("listitem", { name: "Offboarding: Tomasz Podglądowy" });
    expect(within(offboarding).getByText("z odejścia")).toBeInTheDocument();
    expect(within(offboarding).getByRole("button", { name: /^Weź sprawę/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nowa sprawa" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Onboarding 1$/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^Bez osoby/ }));
    expect(tiles().map((tile) => tile.getAttribute("aria-label"))).toEqual([
      "Sprawa: Pytanie o fakturę od działu zakupów",
      "Sprawa: Offboarding: Tomasz Podglądowy",
      "Sprawa: Faktura za szkolenie BHP",
    ]);
    await user.click(screen.getByRole("button", { name: /^Bez osoby/ }));

    await user.click(screen.getByRole("radio", { name: "Moje" }));
    expect(tiles()).toHaveLength(2);
    await user.click(screen.getByRole("radio", { name: "Wszystkie" }));
    await user.click(screen.getByRole("button", { name: "Pokaż zamknięte" }));
    expect(await screen.findByRole("heading", { name: "Zamknięta", level: 3 })).toBeInTheDocument();
    expect(tiles()).toHaveLength(9);

    await user.click(screen.getByRole("button", { name: "Sprawa: Onboarding: Anna Kontraktorska" }));
    // Klik otwiera panel boczny (przebudowa 22.10), pełny ekran sprawy jest pod linkiem.
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByRole("link", { name: /Pełny widok/ })).toHaveAttribute(
      "href",
      "/people/cases/901",
    );
    expect(attempted()).toEqual([]);
  });

  it("stan detail: onboarding spięty z kontraktem, mail, checklista, okno „Edytuj”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-cases?state=detail");
    render(<HrCasesPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: "Onboarding: Anna Kontraktorska" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Wiadomości · 1" })).toBeInTheDocument();
    // Nazwa przycina się na wąskim ekranie, rozmiar stoi obok w osobnym elemencie.
    const attachment = screen.getByText("wniosek-vpn.docx").closest("li");
    expect(attachment).toHaveTextContent("wniosek-vpn.docx · 47 kB");
    expect(screen.getByRole("heading", { name: "Checklista · 1/4" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Otwórz (kontrakt|kartę konsultanta)/ }),
    ).toHaveAttribute("href", expect.stringMatching(/^\/(contracts\/|care\?contract=)4505$/));
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
