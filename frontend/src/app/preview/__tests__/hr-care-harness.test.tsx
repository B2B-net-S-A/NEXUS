/**
 * `/preview/hr-care` (makieta 9 „Ludzi w NEXUSIE”, makieta 7 etapu 2
 * i makiety M1–M3 etapu 3): prawdziwa zakładka „Opieka” kontraktu z rytmem
 * i ekran `/care` („Ten tydzień” z osią konsultanta i „Przekaż do front
 * office”, „Konsultanci” z rytmem, „Przydział”, „Do przepięcia”) na danych
 * fikcyjnych, ZERO prób żądania — także po otwarciu okien „Zapisz rozmowę”,
 * „Zapisz opinię”, „Karta technologiczna”, „Pomiń kontakt” i „Rytm
 * kontaktu”, pytań z mapy technologii i po przełączeniu zakresu list.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-care",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrCarePreviewPage from "../hr-care/page";

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

describe("/preview/hr-care", () => {
  it("zakładka „Opieka”: dzień 45, rytm, plan z rytmu, sygnały i oś z kartą technologiczną", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care");
    render(<HrCarePreviewPage />);

    expect(await screen.findByRole("heading", { name: "Oś opieki" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Michał Konsultantowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("talent_community_manager");
    expect(screen.getByText("Dzień współpracy").nextSibling).toHaveTextContent("45");
    expect(screen.getByText(/^Dzień 7 ·/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Rozmowa według rytmu ·/).length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText("pominięty · niedawno rozmawialiśmy")).toBeInTheDocument();
    expect(screen.getByText("Rytm kontaktu").nextSibling).toHaveTextContent("co 2 tygodnie");
    expect(screen.getByText("pierwsze 90 dni")).toBeInTheDocument();
    expect(screen.getByText("Klient zatrudnia").nextSibling).toHaveTextContent("Java, QA");
    expect(screen.getByText("Koniec projektu")).toBeInTheDocument();
    expect(screen.getByText(/^Karta technologiczna · Natalia Opiekuńcza · Rozmowa odbyta/)).toBeInTheDocument();
    const tech = screen.getByRole("list", { name: "Technologie" });
    expect(within(tech).getByText("Kafka")).toBeInTheDocument();
    expect(screen.getByText(/Trzy dni bez dostępu do VPN/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Karta technologiczna" }));
    expect(
      await screen.findByRole("dialog", { name: "Nowa karta technologiczna" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    await user.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    await user.click(screen.getAllByRole("button", { name: "Pomiń" })[0]);
    expect(await screen.findByRole("dialog", { name: "Pomiń kontakt" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    await user.click(screen.getByRole("button", { name: "Zmień" }));
    const rhythm = await screen.findByRole("dialog", { name: /Rytm kontaktu · Michał Konsultantowy/ });
    expect(within(rhythm).getByText(/Start · co 2 tygodnie \(pierwsze 90 dni\)/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan techcard: otwarte okno karty z technologiami ze słownika i obszarem", async () => {
    window.history.replaceState({}, "", "/preview/hr-care?state=techcard");
    render(<HrCarePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Karta technologiczna" });
    const picked = within(dialog).getByRole("list", { name: "Wybrane: Technologie" });
    expect(within(picked).getByText("Java 17")).toBeInTheDocument();
    expect(within(picked).getByText("PostgreSQL")).toBeInTheDocument();
    expect(within(dialog).getByRole("combobox", { name: "Obszar u klienta" })).toHaveTextContent(
      "Płatności",
    );
    expect(within(dialog).getByDisplayValue("migracja Oracle → PostgreSQL")).toBeInTheDocument();
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Ten tydzień” — prośby o opinię, rozmowy z powodem, oś i front office", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care?state=list");
    render(<HrCarePreviewPage />);

    const tab = await screen.findByRole("tab", { name: /Ten tydzień/ });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(tab).toHaveTextContent("3");
    expect(screen.getByText("Katarzyna Kierownicza")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Zapisz opinię" })).toHaveLength(2);
    const board = screen.getByRole("group", { name: "Rozmowy z konsultantami w tym tygodniu" });
    const late = within(board).getByRole("region", { name: "Zaległe" });
    const karolina = within(late).getByText("Karolina Przykładowa").closest("li") as HTMLElement;
    expect(within(karolina).getByText(/^3 dni po · dzień 30$/)).toBeInTheDocument();
    expect(within(karolina).getByText(/menedżer: Katarzyna Kierownicza/)).toBeInTheDocument();
    expect(within(karolina).getByRole("img", { name: "ocena 5 z 5" })).toBeInTheDocument();
    const michal = within(board).getByText("Michał Konsultantowy").closest("li") as HTMLElement;
    expect(within(michal).getByText(/umówiony kontakt z/)).toBeInTheDocument();
    expect(within(michal).getByText("„Zapytać o certyfikat Azure.”")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Zapisane rozmowy: 2 z 5" })).toBeInTheDocument();
    expect(screen.queryByText("Anna Kontraktorska")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Oś konsultanta: Paweł Makietowy" }));
    const panel = await screen.findByTestId("care-consultant-panel");
    const axis = within(panel).getByRole("list", { name: "Oś konsultanta" });
    expect(within(axis).getByRole("link", { name: "Rekrutacja „Java Developer”" })).toBeInTheDocument();
    expect(within(axis).getByText("Opinia: Michał Rogalski-Przykładowy")).toBeInTheDocument();
    const jobs = within(panel).getByRole("list", { name: "Pasujące otwarte rekrutacje" });
    expect(within(jobs).getAllByRole("listitem")).toHaveLength(2);
    expect(within(panel).getByRole("button", { name: "Przekaż do front office" })).toBeInTheDocument();

    await user.click(within(karolina).getByRole("button", { name: "Zapisz rozmowę" }));
    const dialog = await screen.findByRole("dialog", { name: "Zapisz rozmowę" });
    expect(within(dialog).getByText(/Zamyka punkt planu: Dzień 30/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Do dopytania u klienta/ }));
    const questions = within(dialog).getByRole("list", { name: "Pytania z mapy technologii" });
    expect(within(questions).getByText("Komu podlega Katarzyna Kierownicza (QA)?")).toBeInTheDocument();
    expect(within(questions).getByText("Czy Playwright jest naprawdę używany w dziale QA?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await user.click(screen.getAllByRole("button", { name: "Zapisz opinię" })[0]);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("stan list z `&contract=`: oś otwarta z linku, zakres „Wszyscy” w tygodniu", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care?state=list&contract=4504");
    render(<HrCarePreviewPage />);

    const panel = await screen.findByTestId("care-consultant-panel");
    expect(within(panel).getByRole("heading", { name: "Paweł Makietowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Wszyscy w moim zakresie" }));
    expect(await screen.findByText("Anna Kontraktorska")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Konsultanci” (dawne „Wszystkie kontrakty”), zakres „Wszyscy” i kolejka przepięć bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=contracts");
    const { unmount } = render(<HrCarePreviewPage />);

    const table = await screen.findByRole("table", { name: "Konsultanci i rytm kontaktu" });
    expect(screen.getByRole("tab", { name: "Konsultanci" })).toHaveAttribute("aria-selected", "true");
    const bartosz = within(table).getByRole("row", { name: /Bartosz Testowy/ });
    expect(within(bartosz).getByText("opinia 2,7 / 5")).toBeInTheDocument();
    expect(within(bartosz).getByText("podnieść rytm?")).toBeInTheDocument();
    const olga = within(table).getByRole("row", { name: /Olga Wzorcowa/ });
    expect(within(olga).getByText("wstrzymany")).toBeInTheDocument();
    expect(screen.queryByText("Anna Kontraktorska")).toBeNull();
    await user.click(screen.getByRole("radio", { name: /^Wszyscy w moim zakresie/ }));
    expect(await screen.findByText("Anna Kontraktorska")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
    unmount();

    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=redeploy");
    render(<HrCarePreviewPage />);
    expect(await screen.findByRole("link", { name: "Bartosz Testowy" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paweł Makietowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Zamknięte" }));
    expect(await screen.findByText("Brak zamkniętych wpisów")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan cadence: okno „Rytm kontaktu” Bartosza z podglądem „co 2 tygodnie”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care?state=cadence&tab=consultants");
    render(<HrCarePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: /Rytm kontaktu · Bartosz Testowy/ });
    expect(within(dialog).getByText(/podpowiedź: co 2 tygodnie/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("radio", { name: "Co 2 tygodnie" }));
    expect(await within(dialog).findByText("11 rozmów zamiast 9")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Przydział” z obciążeniem, progiem i osobami bez opiekuna", async () => {
    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=assignment");
    render(<HrCarePreviewPage />);

    const loads = await screen.findByRole("region", { name: "Opiekunowie i obciążenie" });
    expect(within(loads).getByText("powyżej progu 20 rozmów")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Kontrakty do przydziału" });
    expect(within(table).getByText("Marek Nowoprzyjęty")).toBeInTheDocument();
    expect(within(table).getAllByRole("checkbox").length).toBeGreaterThan(1);
    expect(screen.getByLabelText(/Próg obciążenia/)).toHaveValue(20);
    expect(attempted()).toEqual([]);
  });
});
