/**
 * `/preview/hr-offboarding` (makieta 8 „Ludzi w NEXUSIE”): prawdziwy ekran
 * odejścia na danych fikcyjnych, ZERO prób żądania — także listy „Przekaż do”
 * i okno „Cofnij odejście”.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-offboarding",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrOffboardingPreviewPage from "../hr-offboarding/page";

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

describe("/preview/hr-offboarding", () => {
  it("odejście w toku: praca do przekazania, harmonogram i zadania 2/6", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-offboarding");
    render(<HrOffboardingPreviewPage />);

    expect(
      await screen.findByRole("heading", { level: 1, name: /Odejście · ostatni dzień/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Co Tomasz Podglądowy ma w NEXUSIE")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", {
        name: "Przekaż do: Rekrutacje, w których pracuje jako rekruter",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Przekaż do: „Moi ludzie”" })).toBeInTheDocument();
    expect(screen.getAllByText("idzie z rekrutacjami")).toHaveLength(4);
    expect(screen.getByText("Kiedy co się stanie")).toBeInTheDocument();
    expect(screen.getByText(/, 18:00$/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Zadania · 2/6" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cofnij odejście" }));
    expect(await screen.findByRole("dialog", { name: "Cofnąć odejście?" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("szkic: zadania czekają na „Rozpocznij”", async () => {
    window.history.replaceState({}, "", "/preview/hr-offboarding?state=draft");
    render(<HrOffboardingPreviewPage />);

    expect(await screen.findByText(/Szkic — zadania, przekazanie pracy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rozpocznij" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Zadania · 0/6" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("bez sprawy: formularz odejścia", async () => {
    window.history.replaceState({}, "", "/preview/hr-offboarding?state=form");
    render(<HrOffboardingPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: "Odejście · Tomasz Podglądowy" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Ostatni dzień pracy/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz szkic" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rozpocznij odejście" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
