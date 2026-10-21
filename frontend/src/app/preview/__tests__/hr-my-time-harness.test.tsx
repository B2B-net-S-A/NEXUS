/**
 * `/preview/hr-my-time` (makiety 2 i 4 „Ludzi w NEXUSIE” i „Mój czas · przegląd”
 * etapu 2): prawdziwy „Mój czas” na danych fikcyjnych, ZERO prób żądania —
 * także po otwarciu dnia, zmianie miesiąca, przełączeniu zakładek i formy
 * zatrudnienia (`?form=`).
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-my-time",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { currentYearMonth } from "@/components/hr/time/time-format";
import { useAuthStore } from "@/store/auth";
import { warsawToday } from "@/lib/warsaw-date";
import { monthTitlePl, shiftMonth } from "@/lib/date-pl";
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
  it("Przegląd (domyślnie, B2B z pulą): płatne dni, raport godzin, premie w drodze, zadania", async () => {
    open("");

    expect(await screen.findByRole("tab", { name: "Przegląd", selected: true })).toBeInTheDocument();
    const days = await screen.findByRole("generic", { name: "Płatne dni przerwy (z umowy)" });
    expect(within(days).getByText(/wykorzystane 12 dni/)).toBeInTheDocument();
    expect(within(days).queryByText(/na żądanie/i)).toBeNull();
    expect(screen.getByRole("generic", { name: /^Raport godzin/ })).toBeInTheDocument();
    const bonuses = screen.getByRole("generic", { name: "Wynagrodzenie dodatkowe" });
    expect(within(bonuses).getByText(/umowa podpisana/)).toBeInTheDocument();
    expect(within(bonuses).getByText(/14 z 21 dni/)).toBeInTheDocument();
    const todo = screen.getByRole("generic", { name: "Do zrobienia" });
    expect(within(todo).getByText("Podpisz protokół PZO/TEST/2026/011")).toBeInTheDocument();
    expect(within(todo).getByText("Szkolenie stanowiskowe: praca w NEXUSIE")).toBeInTheDocument();
    expect(screen.getByText("dostępny(a)")).toBeInTheDocument();
    // Słowa według formy (D4): B2B „zgłasza przerwę”, zakładki „Przerwy” i „Raport godzin”.
    expect(screen.getByRole("button", { name: "Zgłoś przerwę" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Przerwy" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Raport godzin" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Urlopy" })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Przegląd dla UoP i zlecenia: urlop z limitami albo nieobecności bez puli", async () => {
    open("?form=uop");
    const leave = await screen.findByRole("generic", { name: /^Urlop \d{4}$/ });
    expect(within(leave).getByText(/Na żądanie 1 z 4/)).toBeInTheDocument();
    expect(screen.getByRole("generic", { name: /^Ewidencja czasu pracy/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Złóż wniosek urlopowy" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Urlop" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Ewidencja czasu pracy" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
    cleanup();

    open("?form=zlecenie");
    const absences = await screen.findByRole("generic", { name: /^Nieobecności \d{4}$/ });
    expect(within(absences).queryByText(/zostało/)).toBeNull();
    expect(screen.getByRole("generic", { name: /^Potwierdzenie godzin/ })).toBeInTheDocument();
    expect(screen.getByText(/art\. 8b ustawy o minimalnym wynagrodzeniu/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Nieobecności" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Potwierdzenie godzin" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zgłoś nieobecność" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Przerwy (B2B): zgłoszenia z kolizją od koordynatorki, przełączenie zakładek bez zapytań", async () => {
    const user = userEvent.setup();
    open("?tab=leave");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Ewa Makietowa")).toBeInTheDocument();
    expect(within(table).getByText("przekierowanie poczty")).toBeInTheDocument();
    expect(within(table).getAllByText("Zgłoszone").length).toBeGreaterThan(0);
    expect(within(table).getByText(/kolizja · Marta Fikcyjna/)).toBeInTheDocument();
    expect(within(table).queryByText("Urlop wypoczynkowy")).toBeNull();
    expect(screen.getByRole("button", { name: "Zgłoś przerwę" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Wynagrodzenie dodatkowe i stawka" }));
    expect(await screen.findByText("Liga Mistrzów — 2. miejsce w kwartale")).toBeInTheDocument();
    expect(screen.getByText("kontrakt zakończony przed 21. dniem roboczym")).toBeInTheDocument();
    expect(screen.getByRole("generic", { name: "Moje rozliczenie" })).toBeInTheDocument();
    // Bez zakładki „Kartoteka” — koordynator i link do kartoteki są w „Ja w firmie” na „Przeglądzie”.
    expect(screen.queryByRole("tab", { name: "Kartoteka" })).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Przegląd" }));
    const me = await screen.findByRole("generic", { name: "Ja w firmie" });
    expect(within(me).getByText("Marta Fikcyjna")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("zgłoszenie przerwy Oli (B2B, D5): bez rodzaju i akceptacji, „Co się stanie po zgłoszeniu”", async () => {
    open("?state=report&tab=leave");

    const dialog = await screen.findByRole("dialog", { name: "Zgłoś przerwę w świadczeniu usług" });
    expect(within(dialog).queryByLabelText("Rodzaj")).toBeNull();
    expect(within(dialog).getByText(/Zgłoszenie, nie wniosek — koordynator/)).toBeInTheDocument();
    const outcome = within(dialog).getByTestId("report-outcome");
    expect(outcome).toHaveTextContent("Termin od razu w kalendarzu");
    expect(outcome).toHaveTextContent("Koordynator dostaje informację");
    expect(outcome).toHaveTextContent("nie zatwierdza i nie odrzuca");
    expect(within(dialog).getByLabelText("Kto przejmie bieżące sprawy")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Zgłoś przerwę" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Wyślij do akceptacji" })).toBeNull();
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

  it("Mój miesiąc: dziś z podpowiedzią opisu, poprzedni miesiąc potwierdzony", async () => {
    const user = userEvent.setup();
    const today = warsawToday();
    const current = currentYearMonth();
    open("?tab=month");

    expect(await screen.findByRole("heading", { name: monthTitlePl(current) })).toBeInTheDocument();
    // B2B: raport godzin idzie do potwierdzenia koordynatorki (D4).
    expect(screen.getByRole("button", { name: "Wyślij do potwierdzenia" })).toBeInTheDocument();
    // B2B: „ponad 8 h”, nigdzie „nadgodzin” ani „nadg.” (decyzja Artura 21.10.2026).
    expect(document.body.textContent).not.toMatch(/nadg/i);
    await user.click(screen.getByRole("button", { name: `Dodaj wpis ${today}` }));
    const entry = await screen.findByRole("dialog");
    expect(within(entry).getByRole("button", { name: "Wstaw opis z pracy w NEXUSIE" })).toBeEnabled();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }));
    expect(
      await screen.findByRole("heading", { name: monthTitlePl(shiftMonth(current, -1)) }),
    ).toBeInTheDocument();
    // Ola jest na B2B: raport się potwierdza, nie akceptuje (D4).
    expect(screen.getByText("potwierdzony")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij do potwierdzenia" })).toBeNull();

    // Archiwum timesheetów rozwija się z zasiewu, bez zapytania.
    await user.click(screen.getByRole("button", { name: /Archiwum timesheetów/ }));
    expect(
      await screen.findByRole("button", {
        name: `Pobierz PDF ${monthTitlePl(shiftMonth(current, -2)).toLowerCase()}`,
      }),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Urlopy (UoP): okolicznościowy z załącznikiem — pobranie, usunięcie, „Dołącz kolejny”", async () => {
    open("?tab=leave&form=uop");
    const row = (await screen.findAllByRole("row")).find((item) =>
      item.textContent?.includes("Urlop okolicznościowy"),
    );
    expect(row).toBeDefined();
    expect(within(row!).getByRole("button", { name: "akt-slubu.pdf" })).toBeInTheDocument();
    expect(within(row!).getByRole("button", { name: "Usuń akt-slubu.pdf" })).toBeInTheDocument();
    expect(within(row!).getByRole("button", { name: "Dołącz kolejny" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Załącznik" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Przerwy (B2B): bez kolumny załącznika — zgłoszenie nie potrzebuje dokumentu", async () => {
    open("?tab=leave");
    await screen.findAllByRole("row");
    expect(screen.queryByRole("columnheader", { name: "Załącznik" })).toBeNull();
  });
});

