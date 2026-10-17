/**
 * `/preview/hr-care` (makieta 9 „Ludzi w NEXUSIE” i makieta 7 etapu 2):
 * prawdziwa zakładka „Opieka” kontraktu i ekran `/care` („Ten tydzień”
 * z osią konsultanta i „Przekaż do front office”, „Wszystkie kontrakty”,
 * „Do przepięcia”) na danych fikcyjnych, ZERO prób żądania — także po
 * otwarciu okien „Zapisz rozmowę”, „Zapisz opinię” i „Karta technologiczna”,
 * pytań z mapy technologii i po przełączeniu zakresu list.
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
  it("zakładka „Opieka”: dzień 45, plan 7/30/90, sygnały i oś z kartą technologiczną", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care");
    render(<HrCarePreviewPage />);

    expect(await screen.findByRole("heading", { name: "Oś opieki" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Michał Konsultantowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("talent_community_manager");
    expect(screen.getByText("Dzień współpracy").nextSibling).toHaveTextContent("45");
    expect(screen.getByText(/^Dzień 7 ·/)).toBeInTheDocument();
    expect(screen.getByText(/^Dzień 30 ·/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Dzień 90 ·/).length).toBeGreaterThan(0);
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
    const table = screen.getByRole("table", { name: "Rozmowy z konsultantami" });
    const karolina = within(table).getByRole("row", { name: /Karolina Przykładowa/ });
    expect(within(karolina).getByText(/^zaległy 3 dni · dzień 30$/)).toBeInTheDocument();
    expect(within(karolina).getByText(/menedżer: Katarzyna Kierownicza/)).toBeInTheDocument();
    const michal = within(table).getByRole("row", { name: /Michał Konsultantowy/ });
    expect(within(michal).getByText(/umówiony kontakt z/)).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "Wszyscy w moim zakresie" }));
    expect(await screen.findByText("Anna Kontraktorska")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Wszystkie kontrakty”, zakres „Wszyscy” i kolejka przepięć bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=contracts");
    const { unmount } = render(<HrCarePreviewPage />);

    expect(await screen.findByRole("link", { name: "Michał Konsultantowy" })).toBeInTheDocument();
    expect(screen.queryByText("Anna Kontraktorska")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Wszyscy w moim zakresie" }));
    expect(await screen.findByRole("link", { name: "Anna Kontraktorska" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
    unmount();

    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=redeploy");
    render(<HrCarePreviewPage />);
    expect(await screen.findByRole("link", { name: "Bartosz Testowy" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paweł Makietowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zamknięte" }));
    expect(await screen.findByText("Brak zamkniętych wpisów")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
