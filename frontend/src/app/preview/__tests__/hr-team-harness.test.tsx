/**
 * `/preview/hr-team` (etap 2, „Ludzie → Mój zespół”, układ z makiety
 * 19.10.2026, wiersze decyzji 22.10.2026): prawdziwy ekran przełożonego na
 * danych fikcyjnych, ZERO prób żądania — także po otwarciu okna odrzucenia.
 * Pasek „Dziś” z rodzajem dla przełożonej (D6), wiersze decyzji, mini-tydzień,
 * premie z kwotą bez stawek, Kadry bez Płac — bez kolumny i wierszy premii.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-team",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { warsawToday } from "@/lib/warsaw-date";
import { useAuthStore } from "@/store/auth";
import { harnessWorkDays } from "../hr-fixtures";
import HrTeamPreviewPage from "../hr-team/page";

/** Delegacja Tomasza i przerwa Ewy w mini-tygodniu są „dziś” — w weekend i święto ich nie ma. */
const TODAY_IS_WORKDAY = harnessWorkDays(warsawToday().slice(0, 7)).includes(warsawToday());

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
  it("przełożona: pasek „Dziś”, sprawy do decyzji, mini-tydzień, miesiąc i premie", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-team");
    render(<HrTeamPreviewPage />);

    // Pasek „Dziś”: rodzaj nieobecności dla przełożonej (D6), zastępstwo, delegacja.
    const today = await screen.findByRole("region", { name: "Dziś" });
    expect(today).toHaveTextContent("przerwa w świadczeniu usług do");
    expect(today).toHaveTextContent("zastępuje: Ewa");
    if (TODAY_IS_WORKDAY) expect(today).toHaveTextContent("wyjazd");

    // „Do Twojej decyzji”: wniosek Julii i timesheet Tomasza z akcjami, premia Oli do wiadomości.
    const decisions = screen.getByRole("region", { name: "Do Twojej decyzji" });
    expect(within(decisions).getByRole("link", { name: "Wszystkie w Akceptacjach →" })).toHaveAttribute(
      "href",
      "/people/approvals",
    );
    const leave = within(decisions).getByText("Julia Próbna").closest("li")!;
    expect(leave).toHaveTextContent("nieobecność");
    expect(leave).toHaveTextContent("czeka 5 dni");
    const timesheet = within(decisions).getByText("Tomasz Podglądowy").closest("li")!;
    expect(timesheet).toHaveTextContent("raport godzin");
    expect(timesheet).toHaveTextContent("czeka 2 dni");
    const bonusRow = within(decisions).getByText("Ola Przykładowa").closest("li")!;
    expect(bonusRow).toHaveTextContent("wynagrodzenie dodatkowe · 1 propozycja — decydują Płace");
    // Kwota premii jest w kolumnie „Premie w drodze”, nie w wierszu decyzji.
    expect(bonusRow).not.toHaveTextContent(/zł|PLN/);
    await user.click(within(leave as HTMLElement).getByRole("button", { name: "Odrzuć" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Julia Próbna");
    await user.keyboard("{Escape}");

    const ola = screen.getByRole("row", { name: /^Ola Przykładowa/ });
    // Imię otwiera profil na zakładce nieobecności i godzin.
    expect(within(ola).getByRole("link", { name: "Ola Przykładowa" }).getAttribute("href")).toMatch(
      /^\/people\/\d+#czas$/,
    );
    expect(ola).toHaveTextContent("zaplanowane 8 dni");
    // Wiersz puli z zerem na B2B: liczy się płatna pula, nie sam wiersz.
    expect(ola).not.toHaveTextContent(/zostało/);
    expect(ola).toHaveTextContent("1 propozycja — decydują Płace");
    expect(within(ola).getByRole("progressbar")).toBeInTheDocument();
    const ewa = screen.getByRole("row", { name: /^Ewa Makietowa/ });
    const ewaWeek = within(ewa).getByRole("img", { name: /^pn: / });
    if (TODAY_IS_WORKDAY) expect(ewaWeek).toHaveAccessibleName(/nieobecność/);
    const julia = screen.getByRole("row", { name: /^Julia Próbna/ });
    expect(julia).toHaveTextContent("zostało 14 dni urlopu");
    expect(julia).toHaveTextContent("UoP");
    // Student na zleceniu (D8): sam znacznik — daty zwolnienia widzą Kadry i Płace.
    const adam = screen.getByRole("row", { name: /^Adam Wzorcowy/ });
    expect(adam).toHaveTextContent("Zlecenie · student");
    expect(adam).toHaveTextContent("bez timesheetu");
    expect(adam).not.toHaveTextContent(/składki od/);
    expect(screen.getByRole("columnheader", { name: "Ten tydzień" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Nieobecności" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Premie w drodze" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Mój zespół" })).toHaveAttribute("aria-selected", "true");
    expect(attempted()).toEqual([]);
  });

  it("Kadry bez Płac: zespół Marty bez kolumny i kart premii", async () => {
    window.history.replaceState({}, "", "/preview/hr-team?as=hr");
    render(<HrTeamPreviewPage />);

    expect(await screen.findByRole("row", { name: /^Tomasz Podglądowy/ })).toHaveTextContent(
      "odchodzi",
    );
    expect(screen.queryByRole("columnheader", { name: "Premie w drodze" })).toBeNull();
    expect(screen.queryByText(/wynagrodzenie dodatkowe/)).toBeNull();
    expect(screen.getByRole("combobox", { name: "Zespół koordynatora" })).toHaveTextContent(
      "Marta Fikcyjna",
    );
    expect(attempted()).toEqual([]);
  });
});
