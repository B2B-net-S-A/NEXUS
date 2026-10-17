/**
 * `/preview/hr-onboarding` (makieta 14 „Ludzi w NEXUSIE”): prawdziwy kreator
 * wejścia i sprawa wejścia na danych fikcyjnych, ZERO prób żądania — także po
 * przejściu kreatora do kroku „Zadania” z datą startu ze sceny.
 */
import { fireEvent, render, screen } from "@testing-library/react";
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
    expect(screen.getByText("1 · Osoba i konto")).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("radio", { name: "Ma konto w NEXUSIE" })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: "Nowa osoba bez konta" }));
    await user.type(screen.getByLabelText(/Imię i nazwisko/), kacper.name);
    await user.type(screen.getByLabelText(/E-mail służbowy/), kacper.email);
    await user.click(screen.getByRole("button", { name: "Dalej: zatrudnienie" }));

    await user.type(screen.getByLabelText(/Stanowisko/), "Rekruter");
    fireEvent.change(screen.getByLabelText(/Start pracy/), {
      target: { value: onboardingScene().start },
    });
    await user.click(screen.getByRole("button", { name: "Dalej: zadania" }));

    expect(await screen.findByText(/Wydaj zestaw biura z ewidencji/)).toBeInTheDocument();
    expect(screen.getByText("Check-in z przełożoną — dzień 30")).toBeInTheDocument();
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
});
