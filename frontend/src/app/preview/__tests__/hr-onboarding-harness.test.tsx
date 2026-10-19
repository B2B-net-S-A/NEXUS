/**
 * `/preview/hr-onboarding` (makieta 14 „Ludzi w NEXUSIE”): prawdziwy kreator
 * wejścia i sprawa wejścia na danych fikcyjnych, ZERO prób żądania — także po
 * przejściu kreatora do kroku „Zadania” z datą startu ze sceny.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-onboarding",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { HR_CAST } from "../hr-fixtures";
import { useAuthStore } from "@/store/auth";
import { onboardingScene } from "../hr-onboarding/fixtures";
import HrOnboardingPreviewPage from "../hr-onboarding/page";

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
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

const { kacper } = HR_CAST;

describe("/preview/hr-onboarding", () => {
  it("kreator: osoba, zatrudnienie i podgląd zadań bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-onboarding");
    render(<HrOnboardingPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Nowa osoba" })).toBeInTheDocument();
    expect(screen.getByText("Osoba i konto").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("kto wchodzi i jaką ścieżką")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Ma konto w NEXUSIE" })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Dobierz do formy i działu/ })).toBeChecked();

    // Wyszukiwanie konta: najpierw konta bez kartoteki, osoby z kartoteką wyszarzone.
    await user.type(screen.getByRole("searchbox", { name: /Szukaj konta/ }), "kacper");
    const option = screen.getByRole("option", { name: /Kacper Nowicjusz/ });
    expect(option).toHaveTextContent("bez kartoteki");
    await user.click(option);
    expect(option).toHaveAttribute("aria-selected", "true");

    // „Co powstanie” od pierwszego kroku: kartoteka i zadania wg wykonawcy.
    const what = screen.getByRole("region", { name: "Co powstanie" });
    expect(within(what).getByText("start nieustalony")).toBeInTheDocument();
    expect(within(what).getByText("Kartoteka")).toBeInTheDocument();
    expect(within(what).getByText("Recepcja")).toBeInTheDocument();
    expect(within(what).getByText(/Listę zadań bierzemy ze ścieżki/)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Nowa osoba bez konta" }));
    await user.type(screen.getByLabelText(/Imię i nazwisko/), kacper.name);
    await user.type(screen.getByLabelText(/E-mail służbowy/), kacper.email);
    await user.click(screen.getByRole("button", { name: "Dalej: zatrudnienie" }));

    await user.type(screen.getByLabelText(/Stanowisko/), "Rekruter");
    fireEvent.change(screen.getByLabelText(/Start pracy/), {
      target: { value: onboardingScene().start },
    });
    await user.click(screen.getByRole("button", { name: "Dalej: zadania" }));

    expect((await screen.findAllByText(/Wydaj zestaw biura z ewidencji/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Check-in z przełożoną — dzień 30").length).toBeGreaterThan(0);
    expect(
      within(screen.getByRole("region", { name: "Co powstanie" })).queryByText("start nieustalony"),
    ).toBeNull();
    expect(
      screen.getByRole("heading", { name: /Kacper Nowicjusz · Rekruter · start/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("sprawa w toku: zatrudnienie i zadania recepcji, IT i przełożonej", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-onboarding?state=case");
    render(<HrOnboardingPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: /Kacper Nowicjusz · Rekruter · start/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Zadania · 1/8" })).toBeInTheDocument();
    expect(screen.getByText("Konto Microsoft 365 i licencja")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zakończ wejście" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Anuluj wejście" }));
    expect(await screen.findByRole("dialog", { name: "Anulować wejście?" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("szkic bez konta: informacja o koncie i „Rozpocznij”", async () => {
    window.history.replaceState({}, "", "/preview/hr-onboarding?state=draft");
    render(<HrOnboardingPreviewPage />);

    expect(
      await screen.findByText(new RegExp(`Konta z adresem ${kacper.email.replace(/\./g, "\\.")}`)),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rozpocznij" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("wejście konsultanta (M6): lista ze ścieżki, pakietu i formy bez zapytań", async () => {
    window.history.replaceState({}, "", "/preview/hr-onboarding?state=contract");
    render(<HrOnboardingPreviewPage />);

    expect(await screen.findByText("Przygotuj zestaw sprzętu")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Kroki wejścia" })).toBeInTheDocument();
    expect(screen.getByText("Z czego to powstało")).toBeInTheDocument();
    expect(screen.getByText(/Odhacza recepcja w Sprzęcie/)).toBeInTheDocument();
    expect(screen.getAllByText("Bank Fikcyjny", { selector: "td" }).length).toBeGreaterThan(0);
    expect(attempted()).toEqual([]);
  });

  it("ścieżki (M4): head back office zmienia ścieżkę konsultanta, zespołu nie", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-onboarding?state=paths");
    render(<HrOnboardingPreviewPage />);

    await user.click((await screen.findAllByRole("button", { name: /^Konsultant u klienta/ }))[0]);
    expect(screen.getByRole("button", { name: "Zapisz jako wersję 5" })).toBeInTheDocument();
    expect(screen.getByText(/3 trwające wejścia są na starszej wersji/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Zespół wewnętrzny/ }));
    expect(screen.getByText(/tylko do odczytu/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
