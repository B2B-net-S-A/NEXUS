/**
 * `/preview/hr-approvals` (makieta 5 „Ludzi w NEXUSIE”): prawdziwe „Akceptacje”
 * na danych fikcyjnych, ZERO prób żądania — także po otwarciu podglądu
 * timesheetu i okna odrzucenia.
 */
import { render, screen, within } from "@testing-library/react";
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

describe("/preview/hr-approvals", () => {
  it("przełożona: wnioski z zastępcą, pracą i nieobecnymi, okno odrzucenia", async () => {
    const user = userEvent.setup();
    open("");

    const leave = await screen.findByRole("region", { name: "Wnioski do decyzji (umowa o pracę)" });
    const kamil = within(leave).getByRole("row", { name: /Kamil Testowy/ });
    expect(kamil).toHaveTextContent("zastępca Ola Przykładowa");
    expect(kamil).toHaveTextContent("Rozmowa u klienta: 2");
    expect(kamil).toHaveTextContent("w tym czasie nieobecni też: Adam Wzorcowy");
    expect(within(leave).getByRole("row", { name: /Julia Próbna/ })).toBeInTheDocument();

    await user.click(within(kamil).getByRole("button", { name: "Odrzuć" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("heading", { name: "Historia" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("link z powiadomienia: timesheety poprzedniego miesiąca na górze, podgląd osoby", async () => {
    const user = userEvent.setup();
    const previous = shiftMonth(currentYearMonth(), -1);
    open(`?kind=timesheet&year=${previous.year}&month=${previous.month}`);

    expect(await screen.findByText(monthTitlePl(previous))).toBeInTheDocument();
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
    open("?state=covering");
    expect(await screen.findByTestId("approvals-covering")).toHaveTextContent(
      "W zastępstwie za Kamil Testowy",
    );
    expect(screen.getByText("do wiadomości — decydują Kadry")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("B2B i zlecenie: zgłoszenia do wiadomości z „Zgłoś kolizję”, bez akceptacji (D5)", async () => {
    const user = userEvent.setup();
    open("");
    const reported = await screen.findByRole("region", {
      name: "Zgłoszone przerwy i nieobecności (B2B, zlecenie) — do wiadomości",
    });
    const ola = within(reported).getByRole("row", { name: /Ola Przykładowa/ });
    expect(ola).toHaveTextContent("Przerwa w świadczeniu usług");
    expect(within(ola).queryByRole("button", { name: "Akceptuj" })).toBeNull();
    expect(within(ola).queryByRole("button", { name: "Odrzuć" })).toBeNull();
    expect(within(reported).getByRole("row", { name: /Tomasz/ })).toHaveTextContent(
      "kolizja zgłoszona",
    );

    await user.click(within(ola).getByRole("button", { name: "Zgłoś kolizję" }));
    const dialog = await screen.findByRole("dialog", { name: "Zgłoś kolizję z terminem" });
    expect(within(dialog).getByLabelText(/Z czym koliduje termin/)).toBeInTheDocument();
    await user.keyboard("{Escape}");

    // Historia: zgłoszenie „Zgłoszone”, bez „Anuluj” u przełożonej.
    // „Zgłoszone” ma tylko tabela historii (lista do wiadomości nie ma kolumny statusu).
    const reportRow = screen
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("Zgłoszone"));
    expect(reportRow).toBeDefined();
    expect(within(reportRow!).queryByRole("button", { name: "Anuluj" })).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Kadry: zakres wszyscy i przełożony przy wniosku", async () => {
    open("?state=hr");
    const leave = await screen.findByRole("region", { name: "Wnioski do decyzji (umowa o pracę)" });
    expect(within(leave).getByRole("row", { name: /Kamil Testowy/ })).toHaveTextContent(
      "przełożony: Marta Fikcyjna",
    );
    expect(screen.getByText("wszyscy")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
