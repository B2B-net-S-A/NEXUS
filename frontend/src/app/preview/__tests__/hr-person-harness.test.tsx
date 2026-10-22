/**
 * `/preview/hr-person` (makieta 6 „Ludzi w NEXUSIE”): prawdziwa kartoteka
 * osoby z sekcjami Płac, wejścia/odejścia i sprzętu na danych fikcyjnych,
 * ZERO prób żądania — także po otwarciu okna „Nowa stawka od…” i „Nowa premia”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-person",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrPersonPreviewPage from "../hr-person/page";

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

const heading = () => screen.findByRole("heading", { level: 1, name: /Ola Przykładowa/ });

/** Zakładki kartoteki (makieta 19.10.2026) — Radix reaguje na wskaźnik, stąd userEvent. */
async function openTab(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole("tab", { name: new RegExp(`^${name}`) }));
}

describe("/preview/hr-person", () => {
  it("Kadry i Płace: wizytówka z faktami, zakładki, odejście w menu ⋯ i sprzęt", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-person");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    // B2B: „koordynator”, nie „przełożony” (etap 2, D4).
    expect(screen.getByText(/· koordynator/)).toHaveTextContent("Marta Fikcyjna");
    // Rząd faktów: stawka (Płace), dni przerwy z pierścienia, sprzęt.
    expect(screen.getAllByText("120,00 zł/h").length).toBeGreaterThan(0);
    expect(screen.getByText(/było 110,00/)).toBeInTheDocument();
    expect(screen.getByText("11,5 dnia")).toBeInTheDocument();
    expect(screen.getByText("4 szt.")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Wykorzystane 16,5 z 28 dni.*zostało 11,5/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Płatne dni przerwy \d{4}$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edytuj kartotekę/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Zmień pulę" }).length).toBeGreaterThan(0);
    // Oś „Ostatnio” i puste sekcje jako jedna linia z akcją.
    expect(screen.getByText(/Nowa stawka · 120,00/)).toBeInTheDocument();
    expect(screen.getByText("brak w NEXUSIE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wgraj" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Więcej akcji" }));
    expect(await screen.findByRole("menuitem", { name: "Rozpocznij odejście" })).toHaveAttribute(
      "href",
      "/people/101/offboarding",
    );
    await user.keyboard("{Escape}");

    await openTab(user, "Sprzęt");
    const equipment = screen.getByRole("region", { name: "Sprzęt" });
    expect(within(equipment).getAllByRole("listitem")).toHaveLength(4);
    expect(within(equipment).getByText(/Laptop Dell Latitude 5520 \(153\)/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await openTab(user, "Płace i wynagrodzenie dodatkowe");
    expect(screen.getByText("Aktualna stawka:")).toHaveTextContent(/120,00\szł/);
    expect(screen.getByText("od 01.07.2026", { selector: "td" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Nowa stawka od/ }));
    expect(
      await screen.findByRole("dialog", { name: "Nowa stawka · Ola Przykładowa" }),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("`#place` z dzwonka Płac otwiera „Płace i premie”", async () => {
    window.history.replaceState({}, "", "/preview/hr-person#place");
    render(<HrPersonPreviewPage />);
    expect(await heading()).toBeInTheDocument();
    expect(screen.getByText("Aktualna stawka:")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("zlecenie: student ze składkami od dnia po zwolnieniu, bez puli płatnych dni (D6, D8)", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-person?as=hr&form=zlecenie");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(screen.getByText("Zlecenie · student")).toBeInTheDocument();
    await openTab(user, "Nieobecności i godziny");
    expect(screen.getByText("bez składek do 30.06.2027")).toBeInTheDocument();
    expect(screen.getByText("Składki od")).toBeInTheDocument();
    expect(
      screen.getByText("Na umowie zlecenie nie ma puli płatnych dni — nieobecność jest bez wynagrodzenia."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień pulę" })).toBeNull();

    await user.click(screen.getByRole("button", { name: /Edytuj kartotekę/ }));
    const dialog = await screen.findByRole("dialog", { name: /Kartoteka · Ola Przykładowa/ });
    expect(within(dialog).getByRole("switch", { name: "Uczeń lub student do 26 lat" })).toBeChecked();
    expect(within(dialog).getByLabelText("Zwolnienie ze składek do")).toHaveValue("2027-06-30");
    expect(within(dialog).getByText(/31\.05\.2027 Płace dostaną przypomnienie/)).toBeInTheDocument();
    expect(within(dialog).getByText("Koordynator")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("UoP: staż do urlopu i podpowiedź wymiaru 26 dni przy puli (D9)", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-person?as=hr&form=uop");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    await openTab(user, "Nieobecności i godziny");
    expect(screen.getByText("12 lat")).toBeInTheDocument();
    expect(screen.getByText(/Wymiar według stażu \(12 lat\): 26 dni/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zmień pulę" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Wymiar według stażu w kartotece: 26 dni/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("przełożona: premie bez stawek (D2), bez sprzętu i bez zakładania odejścia", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-person?as=manager");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(screen.queryByText("Stawka")).toBeNull();
    expect(screen.queryByText(/zł\/h/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Edytuj kartotekę/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Więcej akcji" })).toBeNull();
    expect(screen.queryByRole("tab", { name: /^Sprzęt/ })).toBeNull();
    expect(screen.getByText("bez sprawy")).toBeInTheDocument();

    await openTab(user, "Płace i wynagrodzenie dodatkowe");
    expect(screen.getByRole("heading", { name: "Płace" })).toBeInTheDocument();
    expect(screen.queryByText("Aktualna stawka:")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Nowa premia/ }));
    expect(await screen.findByRole("dialog", { name: "Nowa premia" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("„Nieobecności i godziny” (`#czas`): nieobecności roku ze stanem i raporty godzin z PDF", async () => {
    window.history.replaceState({}, "", "/preview/hr-person#czas");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Nieobecności i godziny/, selected: true })).toBeInTheDocument();
    const absences = screen.getByRole("list", { name: /^Nieobecności \d{4}$/ });
    const rows = within(absences).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringMatching(/Przerwa w świadczeniu usług · 3 dni.*zaplanowana/),
      expect.stringMatching(/czeka$/),
      expect.stringMatching(/10 dni.*wykorzystana/),
      expect.stringMatching(/odrzucona$/),
    ]);
    expect(screen.getByText(/^Pula 28 dni · wykorzystane 16,5/)).toBeInTheDocument();
    const reports = screen.getByRole("list", { name: "Raport godzin" });
    expect(within(reports).getAllByRole("listitem")).toHaveLength(6);
    expect(within(reports).getByText("nie założony")).toBeInTheDocument();
    expect(within(reports).getAllByRole("button", { name: "PDF" })).toHaveLength(3);
    expect(attempted()).toEqual([]);
  });

  it("Finanse spoza kręgu D6: tylko zatwierdzone, „nieobecność” bez rodzaju", async () => {
    window.history.replaceState({}, "", "/preview/hr-person?as=finance#czas");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    const absences = screen.getByRole("list", { name: /^Nieobecności \d{4}$/ });
    const rows = within(absences).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    for (const row of rows) expect(row).toHaveTextContent(/^[\d.–]+Nieobecność/);
    expect(within(absences).queryByText("czeka")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("kolega z zespołu: wizytówka, sekcje modułów schowane po odmowie serwera", async () => {
    window.history.replaceState({}, "", "/preview/hr-person?as=colleague");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(
      screen.getByText("Pełną kartotekę widzą ta osoba, jej przełożony, Kadry i Finanse."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Płace/ })).toBeNull();
    expect(screen.queryByText("Wejście i odejście")).toBeNull();
    expect(screen.queryByText(/Nie udało się|nie udało się/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
