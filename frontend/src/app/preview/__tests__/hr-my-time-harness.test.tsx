/**
 * `/preview/hr-my-time` (makiety 2 i 4 „Ludzi w NEXUSIE”): prawdziwy „Mój czas”
 * na danych fikcyjnych, ZERO prób żądania — także po otwarciu dnia, zmianie
 * miesiąca i przełączeniu zakładek.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-my-time",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { warsawToday } from "@/components/hr/leave/leave-format";
import { currentYearMonth, monthTitle, shiftMonth } from "@/components/hr/time/time-format";
import { useAuthStore } from "@/store/auth";
import HrMyTimePreviewPage from "../hr-my-time/page";

// Cała strona z prawdziwymi ekranami — na obciążonej maszynie 5 s nie wystarcza.
vi.setConfig({ testTimeout: 20_000 });

const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

function open(search: string) {
  window.history.replaceState({}, "", `/preview/hr-my-time${search}`);
  render(<HrMyTimePreviewPage />);
}

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/hr-my-time", () => {
  it("Urlopy: saldo i wnioski Oli, przełączenie zakładek bez zapytań", async () => {
    const user = userEvent.setup();
    open("");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Ewa Makietowa")).toBeInTheDocument();
    expect(within(table).getByText("przekierowanie poczty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Złóż wniosek" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Premie" }));
    expect(await screen.findByText("Liga Mistrzów")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Kartoteka" }));
    expect(await screen.findByText("Przełożony: Marta Fikcyjna")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("wniosek Kamila: okno z podglądem, akceptującą i zastępcą do wyboru", async () => {
    open("?state=request&tab=leave");

    const dialog = await screen.findByRole("dialog", { name: "Wniosek o nieobecność" });
    expect(within(dialog).getByText("Co wypada w tym czasie")).toBeInTheDocument();
    expect(within(dialog).getByText("Akceptuje: Marta Fikcyjna")).toBeInTheDocument();
    expect(within(dialog).getByText("Z działu też nieobecni")).toBeInTheDocument();
    expect(within(dialog).queryByText(/Nie udało się policzyć dni/)).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Mój miesiąc: dziś z podpowiedzią opisu, poprzedni miesiąc zaakceptowany", async () => {
    const user = userEvent.setup();
    const today = warsawToday();
    const current = currentYearMonth();
    open("?tab=month");

    expect(await screen.findByRole("heading", { name: monthTitle(current) })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij do akceptacji" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `Dodaj wpis ${today}` }));
    const entry = await screen.findByRole("dialog");
    expect(within(entry).getByRole("button", { name: "Wstaw opis z pracy w NEXUSIE" })).toBeEnabled();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }));
    expect(
      await screen.findByRole("heading", { name: monthTitle(shiftMonth(current, -1)) }),
    ).toBeInTheDocument();
    expect(screen.getByText("zaakceptowany")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij do akceptacji" })).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
