/**
 * `/preview/hr-care` (przebudowa opieki 22.10.2026): karta konsultanta
 * w zakładce kontraktu i w panelu `/care`, okno „Rozmowa”, zakładki „Do
 * zrobienia”, „Konsultanci”, „Klienci”, „Zespół opiekunów” i przycisk
 * „Komunikaty” — na danych fikcyjnych, ZERO prób żądania, także po otwarciu
 * okien i przełączeniu filtrów.
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
vi.setConfig({ testTimeout: 30_000 });

// Lista wyboru Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

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
  it("zakładka „Opieka” = karta konsultanta: zdrowie, liczby, wiedza, sprawy, historia, okna bez zapytań", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care");
    render(<HrCarePreviewPage />);

    const card = await screen.findByTestId("consultant-card");
    expect(useAuthStore.getState().user?.role).toBe("talent_community_manager");
    expect(within(card).getByRole("heading", { name: "Michał Konsultantowy" })).toBeInTheDocument();
    expect(within(card).getByText("Dobrze")).toBeInTheDocument();
    expect(within(card).getByRole("region", { name: "Najważniejsze liczby" })).toHaveTextContent("4/5");
    expect(within(card).getByRole("list", { name: "Technologie w projekcie" })).toHaveTextContent("Kafka");
    expect(within(card).getByText("Sprawy · 2 otwarte")).toBeInTheDocument();
    expect(within(card).getByText("Rozmowa o przedłużeniu")).toBeInTheDocument();
    expect(within(card).queryByRole("link", { name: "Rozmowa o przedłużeniu" })).toBeNull();
    expect(within(card).getByRole("list", { name: "Historia konsultanta" })).toHaveTextContent("Dostęp do VPN klienta");
    expect(screen.queryByRole("button", { name: "Karta technologiczna" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(within(card).getByRole("button", { name: "Sprawy 4" }));
    expect(within(card).getByRole("list", { name: "Historia konsultanta" })).not.toHaveTextContent("Telefon");
    await user.click(within(card).getByRole("button", { name: "Rozmowy 3" }));
    await user.click(within(card).getByRole("button", { name: "Edytuj" }));
    expect(await screen.findByRole("dialog", { name: "Karta technologiczna" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    await user.click(within(card).getAllByRole("button", { name: "Zapisz rozmowę" })[0]);
    const talk = await screen.findByRole("dialog", { name: "Rozmowa · Michał Konsultantowy" });
    await user.click(within(talk).getByRole("button", { name: "Anuluj" }));
    await user.click(within(card).getByRole("button", { name: /Plan kontaktów/ }));
    await user.click(within(card).getAllByRole("button", { name: "Pomiń" })[0]);
    expect(await screen.findByRole("dialog", { name: "Pomiń kontakt" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(attempted()).toEqual([]);
  });

  it("stan techcard: stara karta z technologiami ze słownika i obszarem", async () => {
    window.history.replaceState({}, "", "/preview/hr-care?state=techcard");
    render(<HrCarePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Karta technologiczna" });
    const picked = within(dialog).getByRole("list", { name: "Wybrane: Technologie" });
    expect(within(picked).getByText("Java 17")).toBeInTheDocument();
    expect(within(dialog).getByRole("combobox", { name: "Obszar u klienta" })).toHaveTextContent("Płatności");
    expect(attempted()).toEqual([]);
  });

  it("stan conversation: dwie kolumny, „Co u klienta” z ostatnim stanem, pytania z mapy, sprawy i stopka", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=conversation");
    render(<HrCarePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Rozmowa · Michał Konsultantowy" });
    expect(within(dialog).getByText(/Zamyka punkt planu: Rozmowa według rytmu/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Bez danych o zdrowiu i bez stawek/)).toBeInTheDocument();
    const state = within(dialog).getByRole("region", { name: "Co u klienta" });
    expect(within(state).getByText("Data")).toBeInTheDocument();
    expect(within(dialog).getByText("Zapiszemy: rozmowę.")).toBeInTheDocument();

    await user.click(within(state).getByRole("button", { name: "Wszystko bez zmian" }));
    await user.click(within(state).getByRole("button", { name: "Koniec projektu: zmień" }));
    expect(within(state).getByLabelText("Koniec projektu (miesiąc)")).toBeInTheDocument();

    const questions = within(dialog).getByRole("region", { name: "Pytania z mapy klienta" });
    expect(within(questions).getByText("Komu podlega Piotr Menedżerski?")).toBeInTheDocument();
    await user.type(within(questions).getByLabelText("Notatka: Czy Kafka jest naprawdę używany?"), "tak, od 2025");

    const cases = within(dialog).getByRole("region", { name: "Coś do załatwienia?" });
    await user.click(within(cases).getByRole("button", { name: "Dodaj sprawę" }));
    await user.type(within(cases).getByLabelText("Sprawa 1: tytuł"), "Nowy laptop");
    await user.click(within(dialog).getByRole("switch", { name: /Klient zatrudnia/ }));
    expect(within(dialog).getByText(/Zapiszemy: rozmowę · stan u klienta \(1 zmiana\) · 1 odpowiedź do mapy klienta · 1 sprawę · sygnał popytu/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Podpowiedź:/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Do zrobienia” i „Komunikaty” w nagłówku, bez dawnych zakładek", async () => {
    window.history.replaceState({}, "", "/preview/hr-care?state=list");
    render(<HrCarePreviewPage />);

    expect(await screen.findByRole("tab", { name: "Do zrobienia" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Konsultanci" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Klienci" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Zespół opiekunów" })).toBeNull();
    expect(screen.queryByRole("tab", { name: /Ten tydzień|Do przepięcia|Technologie|Przydział/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Komunikaty/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan list z `&contract=`: karta w panelu, „Przekaż do front office” z pasującymi rekrutacjami", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=list&contract=4504");
    render(<HrCarePreviewPage />);

    const panel = await screen.findByTestId("care-consultant-card-panel");
    expect(await within(panel).findByRole("heading", { name: "Paweł Makietowy" })).toBeInTheDocument();
    expect(within(panel).getByText("Ryzyko")).toBeInTheDocument();
    const step = within(panel).getByRole("region", { name: "Następny krok" });
    expect(within(step).getByRole("list", { name: "Pasujące rekrutacje" })).toBeInTheDocument();
    await user.click(within(step).getByRole("button", { name: "Przekaż do front office" }));
    expect(await within(step).findByRole("list", { name: "Pasujące otwarte rekrutacje" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("„Konsultanci”: kolumna „Zdrowie”, filtr „Do przepięcia” (też z dawnego `tab=redeploy`), zakres „Mój zakres”", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=redeploy");
    const { unmount } = render(<HrCarePreviewPage />);

    expect(await screen.findByRole("tab", { name: "Konsultanci" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /^Do przepięcia/ })).toHaveAttribute("aria-pressed", "true");
    const table = screen.getByRole("table", { name: "Konsultanci i rytm kontaktu" });
    const pawel = within(table).getByRole("row", { name: /Paweł Makietowy/ });
    expect(within(pawel).getByText("Ryzyko")).toBeInTheDocument();
    expect(within(table).queryByRole("row", { name: /Bartosz Testowy/ })).toBeNull();
    unmount();

    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=consultants");
    render(<HrCarePreviewPage />);
    const all = await screen.findByRole("table", { name: "Konsultanci i rytm kontaktu" });
    expect(within(all).getByRole("row", { name: /Bartosz Testowy/ })).toHaveTextContent("ostatnia opinia menedżera 2,7 / 5");
    expect(screen.queryByText("Anna Kontraktorska")).toBeNull();
    await user.click(screen.getByRole("radio", { name: "Mój zakres" }));
    expect(await screen.findByText("Anna Kontraktorska")).toBeInTheDocument();
    await user.click(within(all).getByRole("button", { name: "Karta konsultanta: Bartosz Testowy" }));
    const panel = await screen.findByTestId("care-consultant-card-panel");
    expect(await within(panel).findByText("Podnieś rytm do „co 2 tygodnie”")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("„Klienci”: wiedza, zdrowie paskiem, popyt i kończący; filtr „Z ryzykiem”", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=clients");
    render(<HrCarePreviewPage />);

    const table = await screen.findByRole("table", { name: "Klienci i wiedza o nich" });
    const bank = within(table).getByRole("row", { name: /Bank Przykładowy/ });
    expect(within(bank).getByText("2 ryzyko")).toBeInTheDocument();
    expect(within(bank).getByText("4 z 5")).toBeInTheDocument();
    expect(within(bank).getByText("3 luki")).toBeInTheDocument();
    expect(within(bank).getByText("sygnał z rozmowy")).toBeInTheDocument();
    expect(within(bank).getByRole("button", { name: "Karta konsultanta: Paweł Makietowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Z ryzykiem 1" }));
    expect(within(table).queryByRole("row", { name: /Telekom Wzorcowy/ })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("stan team: „Zespół opiekunów” z zaległymi, ustawienia przydziału zwinięte, komunikat do zatwierdzenia", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=team&tab=team");
    render(<HrCarePreviewPage />);

    expect(await screen.findByRole("tab", { name: "Zespół opiekunów" })).toHaveAttribute("aria-selected", "true");
    const team = await screen.findByRole("table", { name: "Opiekunowie, zaległe i portfel" });
    expect(within(team).getByRole("row", { name: /Natalia Opiekuńcza/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Pula opiekunów" })).toBeNull();
    expect(screen.getByRole("table", { name: "Kontrakty do przydziału" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Ustawienia przydziału/ }));
    expect(screen.getByLabelText(/do zatwierdzenia/)).toBeInTheDocument();
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
});
