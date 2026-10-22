/**
 * `/preview/hr-calendar` (makieta 3 „Ludzi w NEXUSIE”, układ z 19.10.2026):
 * prawdziwy kalendarz zespołu na danych fikcyjnych, ZERO prób żądania — także
 * po kliknięciu nieobecności, przełączeniu filtrów, szukaniu i widoku
 * 2 tygodni (każdy klucz jest zasiany).
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
  it("rekruterka: osoby i nieobecności bez rodzaju, bez chipa „Mój zespół”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-calendar");
    render(<HrCalendarPreviewPage />);

    expect(await screen.findByRole("rowheader", { name: /Kamil Testowy/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Mój zespół/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^Wszyscy/ })).toHaveAttribute("aria-pressed", "true");
    const bars = screen.getAllByRole("button", { name: /^Ewa Makietowa: Nieobecność/ });
    // Ciągły pasek: jedna nieobecność = jeden przycisk, nie kafelek na dzień.
    expect(bars).toHaveLength(1);
    await user.click(bars[0]);
    expect(
      screen.getByText(
        "Rodzaj nieobecności widzą tylko ta osoba, jej przełożony albo koordynator i Kadry.",
      ),
    ).toBeInTheDocument();
    // Wiersz „Nieobecnych” i panel tygodnia.
    expect(screen.getByRole("rowheader", { name: "Nieobecnych" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Podsumowanie" })).toHaveTextContent(
      /W (tym )?tygodniu nie ma/,
    );

    await user.click(screen.getByRole("button", { name: "Następny miesiąc" }));
    expect(await screen.findByRole("rowheader", { name: /Kamil Testowy/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("„Znajdź osobę” i widok 2 tygodni bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-calendar");
    render(<HrCalendarPreviewPage />);

    const table = await screen.findByRole("table", { name: "Nieobecności zespołu" });
    await user.type(screen.getByRole("searchbox", { name: "Znajdź osobę w kalendarzu" }), "kamil");
    const rows = within(table).getAllByRole("rowheader");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAccessibleName(/Kamil Testowy/);
    expect(rows[1]).toHaveAccessibleName("Nieobecnych");
    await user.clear(screen.getByRole("searchbox", { name: "Znajdź osobę w kalendarzu" }));

    await user.click(screen.getByRole("button", { name: "2 tygodnie" }));
    expect(screen.getByRole("button", { name: "2 tygodnie" })).toHaveAttribute("aria-pressed", "true");
    const twoWeeks = screen.getByRole("table", { name: "Nieobecności zespołu" });
    // Kolumna „Osoba” + 14 dni.
    expect(within(twoWeeks).getAllByRole("columnheader")).toHaveLength(15);
    await user.click(screen.getByRole("button", { name: "Następne dwa tygodnie" }));
    expect(await screen.findByRole("rowheader", { name: /Kamil Testowy/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("przełożona: domyślnie „Mój zespół”, rodzaj nieobecności swoich ludzi", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-calendar?as=manager");
    render(<HrCalendarPreviewPage />);

    const sick = await screen.findAllByRole("button", {
      name: /^Ewa Makietowa: Zwolnienie lekarskie/,
    });
    expect(sick.length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^Mój zespół/ })).toHaveAttribute("aria-pressed", "true");
    const table = screen.getByRole("table");
    expect(within(table).queryByRole("rowheader", { name: /Kamil Testowy/ })).toBeNull();
    expect(within(table).getByRole("rowheader", { name: /Tomasz Podglądowy/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Wszyscy/ }));
    expect(
      within(screen.getByRole("table")).getByRole("rowheader", { name: /Kamil Testowy/ }),
    ).toBeInTheDocument();
    // Filtr dopisuje się do adresu obok `?as=` harnessu.
    expect(window.location.search).toBe("?as=manager&scope=all");
    await user.click(screen.getByRole("button", { name: /^Delivery/ }));
    expect(within(screen.getByRole("table")).getByRole("rowheader", { name: /Adam Wzorcowy/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Dziś nieobecni|^Nieobecni w okresie/ }));
    expect(attempted()).toEqual([]);
  });
});
