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
    expect(within(card).getByRole("region", { name: "Najważniejsze liczby" })).toHaveTextContent("4 / 5");
    expect(within(card).getByRole("region", { name: "Najważniejsze liczby" })).toHaveTextContent("było 5 / 5");
    expect(within(card).getByRole("list", { name: "Technologie w projekcie" })).toHaveTextContent("Kafka");
    expect(within(card).getByText("Sprawy · 2 otwarte")).toBeInTheDocument();
    expect(within(card).getByText("Rozmowa o przedłużeniu")).toBeInTheDocument();
    expect(within(card).getByRole("list", { name: "Historia konsultanta" })).toHaveTextContent("Dostęp do VPN klienta");
    // Makieta S3: sprawy z obszarem, źródłem i terminem; zamknięte jedną linią.
    const caseRows = within(card).getByRole("list", { name: "Sprawy konsultanta" });
    expect(caseRows).toHaveTextContent("Negocjacje · ręcznie · prowadzi Natalia Opiekuńcza · treść tylko w Sprawach");
    expect(caseRows).toHaveTextContent(/odezwać się \d\d\.\d\d/);
    expect(within(caseRows).getByRole("link", { name: /Dostęp do VPN klienta/ })).toHaveAttribute("href", "/people/cases/951");
    // Negocjacje bez treści — wiersz bez linku.
    expect(within(caseRows).queryByRole("link", { name: /Rozmowa o przedłużeniu/ })).toBeNull();
    expect(within(card).getByText(/^Zamknięte: Wejście konsultanta · \d\d\.\d\d · 4\/4$/)).toBeInTheDocument();
    // Makieta P2: plan na górze historii z „za N dni”.
    expect(within(card).getByRole("list", { name: "Historia konsultanta" })).toHaveTextContent(/Plan: rozmowa według rytmu · za \d+ dni/);
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
    // Makieta P3: klient · dział · dzień współpracy, potem punkt planu z datą.
    expect(within(dialog).getByText(/Bank Przykładowy · Data · dzień 45/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Zamyka punkt planu: rozmowa według rytmu \d\d\.\d\d\. Bez danych o zdrowiu i bez stawek\./)).toBeInTheDocument();
    const state = within(dialog).getByRole("region", { name: "Co u klienta" });
    expect(within(state).getByText(/potwierdź albo zmień/)).toBeInTheDocument();
    expect(within(state).getByText("Data")).toBeInTheDocument();
    // Nieruszone wiersze = „bez zmian” i potwierdzenie stanu przy zapisie.
    expect(within(state).getAllByText("bez zmian").length).toBeGreaterThan(3);
    expect(within(dialog).getByText("Zapisze: rozmowę i stan „co u klienta” bez zmian.")).toBeInTheDocument();
    // Następny kontakt wpisany z rytmu.
    expect(within(dialog).getByText("wg rytmu „co 2 tygodnie”")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Następny kontakt")).not.toHaveValue("");

    await user.click(within(state).getByRole("button", { name: "Koniec projektu: zmień" }));
    expect(within(state).getByLabelText("Koniec projektu (miesiąc)")).toBeInTheDocument();
    expect(within(state).getByText("zmieniono")).toBeInTheDocument();
    await user.click(within(state).getByRole("button", { name: "Koniec projektu: cofnij" }));

    const questions = within(dialog).getByRole("region", { name: "Pytania z mapy klienta" });
    expect(within(questions).getByText("Pytania z mapy klienta · 2")).toBeInTheDocument();
    expect(within(questions).getByText("Komu podlega Piotr Menedżerski (Head of Data)?")).toBeInTheDocument();
    expect(within(questions).getByText("CI/CD i chmura")).toBeInTheDocument();
    await user.type(within(questions).getByLabelText("Notatka: CI/CD i chmura"), "GitLab CI i Azure");

    const cases = within(dialog).getByRole("region", { name: "Coś do załatwienia?" });
    await user.click(within(cases).getByRole("button", { name: "Dodaj sprawę" }));
    await user.type(within(cases).getByLabelText("Sprawa 1: tytuł"), "Nowy laptop");
    expect(within(cases).getByText(/Sprawa dostanie kontrakt, opis z notatki i link do tej rozmowy\./)).toBeInTheDocument();
    expect(within(cases).getByRole("button", { name: /dodaj kolejną/ })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("switch", { name: /Klient zatrudnia/ }));
    expect(within(dialog).getByRole("switch", { name: /Kończy projekt/ })).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Zapisze: rozmowę, stan „co u klienta” bez zmian, 1 odpowiedź do mapy klienta, 1 sprawę i sygnał popytu.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Zapisz rozmowę i 1 sprawę" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Do zrobienia” i „Komunikaty” w nagłówku, bez dawnych zakładek", async () => {
    window.history.replaceState({}, "", "/preview/hr-care?state=list");
    render(<HrCarePreviewPage />);

    // Makieta P1: zakładki z licznikami („Do zrobienia 8 · Konsultanci 7 · Klienci 2”).
    expect(await screen.findByRole("tab", { name: /^Do zrobienia\s*8$/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /^Konsultanci\s*\d+$/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Klienci\s*\d+$/ })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /^Zespół opiekunów/ })).toBeNull();
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
    // Makieta P2: „Dlaczego „Ryzyko”: … i …”, liczby z podpisami, podtytuł z opiekunem.
    expect(within(panel).getByText(/Dlaczego „Ryzyko”:/)).toBeInTheDocument();
    expect(within(panel).getByText(/chce zmiany projektu \(\d\d\.\d\d\) i zamówienie kończy się za 34 dni\./)).toBeInTheDocument();
    expect(within(panel).getByText(/Java Developer · Bank Przykładowy · B2B od .* · opiekun Natalia Opiekuńcza/)).toBeInTheDocument();
    expect(within(panel).getByRole("region", { name: "Najważniejsze liczby" })).toHaveTextContent("przedłużenie: tak");
    expect(within(panel).getByText(/Dostawca A, Dostawca B/)).toHaveTextContent(
      "zespół 9 osób (4 z zewnątrz: Dostawca A, Dostawca B)",
    );
    const step = within(panel).getByRole("region", { name: "Następny krok" });
    const matches = within(step).getByRole("list", { name: "Pasujące rekrutacje" });
    expect(within(matches).getByRole("link", { name: /Java Developer \(Kredyty\)\s*84/ })).toHaveAttribute("href", "/jobs/6201");
    expect(within(step).getByRole("button", { name: "Przekaż" })).toBeInTheDocument();
    await user.click(within(step).getByRole("button", { name: "Więcej szczegółów" }));
    expect(await within(step).findByRole("list", { name: "Pasujące otwarte rekrutacje" })).toBeInTheDocument();
    // „Przekaż” pyta o potwierdzenie (useConfirmV2), zanim cokolwiek wyśle.
    await user.click(within(step).getByRole("button", { name: "Przekaż" }));
    const confirm = await screen.findByRole("dialog", { name: /Przekazać .* do front office\?/ });
    expect(confirm).toHaveTextContent("Java Developer (Kredyty), ZAP-112 Backend");
    await user.click(within(confirm).getByRole("button", { name: "Anuluj" }));
    expect(attempted()).toEqual([]);
  });

  it("„Konsultanci”: kolumna „Zdrowie”, filtr „Do przepięcia” (też z dawnego `tab=redeploy`), zakres „Mój zakres”", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=redeploy");
    const { unmount } = render(<HrCarePreviewPage />);

    expect(await screen.findByRole("tab", { name: /^Konsultanci/ })).toHaveAttribute("aria-selected", "true");
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
    // Makieta P4: zdrowie słowami, kompletność menedżerów, świeżość mapy, kończący skrótem.
    expect(bank).toHaveTextContent("6 · 4 dobrze · 1 uwaga · 1 ryzyko");
    expect(bank).toHaveTextContent("6 z 6");
    expect(bank).toHaveTextContent("3 menedżerów · drzewo pełne");
    expect(bank).toHaveTextContent("1 prośba czeka od 19.10");
    expect(bank).toHaveTextContent("2 luki do dopytania");
    expect(bank).toHaveTextContent("DL Kamil T. · opiekun domyślny Natalia O.");
    const telekom = within(table).getByRole("row", { name: /Telekom Wzorcowy/ });
    expect(telekom).toHaveTextContent("stara · 14 mies.");
    expect(telekom).toHaveTextContent("2 pewne propozycje do zatwierdzenia");
    expect(within(bank).getByRole("button", { name: "Karta konsultanta: Paweł Makietowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Z ryzykiem 1" }));
    expect(within(table).queryByRole("row", { name: /Telekom Wzorcowy/ })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("stan team: „Zespół opiekunów” z zaległymi, ustawienia przydziału zwinięte, komunikat do zatwierdzenia", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    window.history.replaceState({}, "", "/preview/hr-care?state=team&tab=team");
    render(<HrCarePreviewPage />);

    expect(await screen.findByRole("tab", { name: /^Zespół opiekunów/ })).toHaveAttribute("aria-selected", "true");
    const team = await screen.findByRole("table", { name: "Opiekunowie, zaległe i portfel" });
    expect(within(team).getByRole("row", { name: /Natalia Opiekuńcza/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Pula opiekunów" })).toBeNull();
    // Makieta P6: pasek „bez opiekuna” z „Przypisz wg obłożenia”, bez dawnej tabeli przydziału.
    expect(screen.queryByRole("table", { name: "Kontrakty do przydziału" })).toBeNull();
    expect(screen.getByText(/2 konsultantów bez opiekuna/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przypisz wg obłożenia (2)" })).toBeInTheDocument();
    expect(within(team).getByRole("row", { name: /Igor Testowy/ })).toHaveTextContent("w puli · bez podopiecznych");
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
