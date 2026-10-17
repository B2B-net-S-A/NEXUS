/**
 * `/preview/hr-calendar` (makieta 3 „Ludzi w NEXUSIE”): prawdziwy kalendarz
 * zespołu na danych fikcyjnych, ZERO prób żądania — także po kliknięciu
 * nieobecności i przełączeniu filtrów (każdy klucz jest zasiany).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-calendar",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrCalendarPreviewPage from "../hr-calendar/page";

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

describe("/preview/hr-calendar", () => {
  it("rekruterka: osoby i nieobecności bez rodzaju, bez filtra „Mój zespół”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-calendar");
    render(<HrCalendarPreviewPage />);

    expect(await screen.findByRole("rowheader", { name: /Kamil Testowy/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mój zespół" })).toBeNull();
    const bars = screen.getAllByRole("button", { name: /^Ewa Makietowa: Nieobecność/ });
    await user.click(bars[0]);
    expect(
      screen.getByText("Rodzaj nieobecności widzą tylko ta osoba, jej przełożony i Kadry."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Następny miesiąc" }));
    expect(await screen.findByRole("rowheader", { name: /Kamil Testowy/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("przełożona: rodzaj nieobecności swoich ludzi i filtr „Mój zespół”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-calendar?as=manager");
    render(<HrCalendarPreviewPage />);

    const sick = await screen.findAllByRole("button", {
      name: /^Ewa Makietowa: Zwolnienie lekarskie/,
    });
    expect(sick.length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Mój zespół" }));
    const table = screen.getByRole("table");
    expect(within(table).queryByRole("rowheader", { name: /Kamil Testowy/ })).toBeNull();
    expect(within(table).getByRole("rowheader", { name: /Tomasz Podglądowy/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delivery" }));
    expect(within(screen.getByRole("table")).getByRole("rowheader", { name: /Adam Wzorcowy/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
