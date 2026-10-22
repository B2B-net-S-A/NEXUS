/**
 * `/preview/hr-approvals` (makieta 5 „Ludzi w NEXUSIE”, skrzynka z 19.10.2026):
 * prawdziwe „Akceptacje” na danych fikcyjnych, ZERO prób żądania — także po
 * wyborze sprawy, otwarciu podglądu timesheetu, okna odrzucenia i historii.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-approvals",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { currentYearMonth } from "@/components/hr/time/time-format";
import { useAuthStore } from "@/store/auth";
import { monthTitlePl, shiftMonth } from "@/lib/date-pl";
import HrApprovalsPreviewPage from "../hr-approvals/page";

// Cała strona z prawdziwymi ekranami — na obciążonej maszynie 5 s nie wystarcza.
vi.setConfig({ testTimeout: 20_000 });

const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

function open(search: string) {
  window.history.replaceState({}, "", `/preview/hr-approvals${search}`);
  render(<HrApprovalsPreviewPage />);
}

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

const DECIDE = "Wnioski do decyzji (umowa o pracę)";
const INFO = "Zgłoszone przerwy i nieobecności (B2B, zlecenie) — do wiadomości";

describe("/preview/hr-approvals", () => {
  it("przełożona: skrzynka z kolizją, szczegół z zastępcą, pracą i mini-kalendarzem, okno odrzucenia", async () => {
    const user = userEvent.setup();
    open("");

    const decide = await screen.findByRole("list", { name: DECIDE });
    const kamilItem = within(decide).getByRole("button", { name: /^Kamil Testowy/ });
    expect(kamilItem).toHaveTextContent("kolizja: Adam");
    expect(within(decide).getByRole("button", { name: /^Julia Próbna/ })).toBeInTheDocument();

    // Pierwsza sprawa otwarta od razu.
    const detail = screen.getByRole("region", { name: "Szczegóły: Kamil Testowy" });
    expect(detail).toHaveTextContent("Ola Przykładowa");
    expect(detail).toHaveTextContent("Rozmowa u klienta: 2");
    expect(detail).toHaveTextContent("Adam Wzorcowy");
    const term = within(detail).getByRole("table", { name: "Zespół w tym terminie" });
    expect(within(term).getByRole("rowheader", { name: "Adam Wzorcowy" })).toBeInTheDocument();
    expect(within(term).getAllByRole("cell", { name: /^Kamil Testowy: wniosek czeka/ }).length).toBeGreaterThanOrEqual(5);

    await user.click(within(detail).getByRole("button", { name: "Odrzuć" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    // Historia jest pod „Zdecydowane” (jedna lista, 22.10.2026).
    expect(screen.queryByRole("heading", { name: "Nieobecności" })).toBeNull();
    await user.click(screen.getByRole("radio", { name: "Zdecydowane" }));
    expect(screen.getByRole("heading", { name: "Nieobecności" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("link z powiadomienia: chip „Raporty godzin”, poprzedni miesiąc, podsumowanie i podgląd osoby", async () => {
    const user = userEvent.setup();
    const previous = shiftMonth(currentYearMonth(), -1);
    open(`?kind=timesheet&year=${previous.year}&month=${previous.month}`);

    expect(await screen.findByText(monthTitlePl(previous))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Raporty godzin/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("list", { name: DECIDE })).toBeNull();
    expect(screen.getByTestId("timesheet-summary")).toHaveTextContent(
      "1 nie założony · 2 do akceptacji · 6 zaakceptowany",
    );
    const ewa = screen.getByTestId("queue-103");
    expect(ewa).toHaveTextContent("Do akceptacji");
    expect(screen.getByTestId("queue-107")).toHaveTextContent("Nie założony");
    expect(screen.getByTestId("queue-106")).toHaveTextContent("2");

    await user.click(within(ewa).getByRole("button", { name: "Podgląd" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Akceptuj" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Kadry i zastępca przełożonego", async () => {
    const user = userEvent.setup();
    open("?state=covering");
    expect(await screen.findByTestId("approvals-covering")).toHaveTextContent(
      "W zastępstwie za Kamil Testowy",
    );
    const decide = screen.getByRole("list", { name: DECIDE });
    const ewa = within(decide).getByRole("button", { name: /^Ewa Makietowa/ });
    expect(ewa).toHaveTextContent("do wiadomości");
    await user.click(ewa);
    expect(screen.getByRole("region", { name: "Szczegóły: Ewa Makietowa" })).toHaveTextContent(
      "do wiadomości — decydują Kadry",
    );
    expect(attempted()).toEqual([]);
  });

  it("B2B i zlecenie: zgłoszenia do wiadomości z „Zgłoś kolizję”, bez akceptacji (D5)", async () => {
    const user = userEvent.setup();
    open("");
    const info = await screen.findByRole("list", { name: INFO });
    expect(within(info).getByRole("button", { name: /^Tomasz/ })).toHaveTextContent(
      "kolizja zgłoszona",
    );
    await user.click(within(info).getByRole("button", { name: /^Ola Przykładowa/ }));
    const ola = screen.getByRole("region", { name: "Szczegóły: Ola Przykładowa" });
    expect(ola).toHaveTextContent("Przerwa w świadczeniu usług");
    expect(within(ola).queryByRole("button", { name: "Akceptuj" })).toBeNull();
    expect(within(ola).queryByRole("button", { name: "Odrzuć" })).toBeNull();

    await user.click(within(ola).getByRole("button", { name: "Zgłoś kolizję" }));
    const dialog = await screen.findByRole("dialog", { name: "Zgłoś kolizję z terminem" });
    expect(within(dialog).getByLabelText(/Z czym koliduje termin/)).toBeInTheDocument();
    await user.keyboard("{Escape}");

    // „Zdecydowane”: zgłoszenie „Zgłoszone”, bez „Anuluj” u przełożonej.
    await user.click(screen.getByRole("radio", { name: "Zdecydowane" }));
    const reportRow = screen
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("Zgłoszone"));
    expect(reportRow).toBeDefined();
    expect(within(reportRow!).queryByRole("button", { name: "Anuluj" })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Kadry: zakres wszyscy i przełożony przy wniosku", async () => {
    open("?state=hr");
    expect(await screen.findByRole("region", { name: "Szczegóły: Kamil Testowy" })).toHaveTextContent(
      "koordynator: Marta Fikcyjna",
    );
    expect(screen.getByText("wszyscy")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("załącznik Julii: przełożona widzi tylko „Załącznik ✓”, Kadry nazwę pliku (D6)", async () => {
    const user = userEvent.setup();
    open("");
    const decide = await screen.findByRole("list", { name: DECIDE });
    const juliaItem = within(decide).getByRole("button", { name: /^Julia Próbna/ });
    expect(juliaItem).toHaveTextContent("załącznik ✓");
    await user.click(juliaItem);
    const julia = screen.getByRole("region", { name: "Szczegóły: Julia Próbna" });
    expect(within(julia).getByText("Załącznik ✓")).toBeInTheDocument();
    expect(within(julia).queryByText(/akt-slubu/)).toBeNull();
    cleanup();

    open("?state=hr");
    const hrDecide = await screen.findByRole("list", { name: DECIDE });
    await user.click(within(hrDecide).getByRole("button", { name: /^Julia Próbna/ }));
    const hrJulia = screen.getByRole("region", { name: "Szczegóły: Julia Próbna" });
    expect(within(hrJulia).getByRole("button", { name: "akt-slubu.pdf" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
