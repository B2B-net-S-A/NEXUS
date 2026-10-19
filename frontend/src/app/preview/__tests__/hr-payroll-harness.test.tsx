/**
 * `/preview/hr-payroll` (makieta 7 „Ludzi w NEXUSIE”): prawdziwy miesiąc płac
 * i lista miesięcy na danych fikcyjnych, ZERO prób żądania — także po
 * otwarciu okna „Nowa premia”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-payroll",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import { monthTitlePl } from "@/lib/date-pl";
import { payrollScene } from "../hr-payroll/fixtures";
import HrPayrollPreviewPage from "../hr-payroll/page";

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

const closingLabel = () => monthTitlePl(payrollScene());

describe("/preview/hr-payroll", () => {
  it("Płace: poprzedni miesiąc ze stawkami, ostrzeżeniem i premiami z placementów i Ligi", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-payroll");
    render(<HrPayrollPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: `Płace · ${closingLabel()}` }),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Stawka /h" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kamil Testowy" })).toBeInTheDocument();
    expect(screen.getByText(/23\s652,80 zł/)).toBeInTheDocument();
    // Stepper: premie z miesiąca czekają na decyzję, więc „Zamknij miesiąc” jeszcze nieaktywne.
    const steps = screen.getByRole("list", { name: "Kroki zamknięcia miesiąca" });
    expect(within(steps).getByText(/^Premie/).closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.getAllByText(/2 os\. bez zatwierdzonego timesheetu/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Zamknij miesiąc/ })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Premie do decyzji" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Razem do wypłaty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zatwierdź zaznaczone" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^(Przypomnij|Ponagl)/ }).length).toBeGreaterThan(0);
    // Pięć premii do decyzji: każda z polem do zaznaczenia (zbiorczo) i menu „⋯”.
    const decisions = screen.getByRole("region", { name: "Premie do decyzji" });
    expect(within(decisions).getAllByRole("checkbox", { name: /^Zaznacz: / })).toHaveLength(5);
    expect(within(decisions).getAllByRole("button", { name: /^Decyzja: / })).toHaveLength(5);
    expect(screen.getAllByText(/Liga Mistrzów rekruterów/)).toHaveLength(3);
    // Placementy w drodze jako paski dni.
    const placements = screen.getByRole("region", { name: "Placementy w drodze" });
    expect(within(placements).getAllByRole("progressbar")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /Nowa premia/ }));
    expect(await screen.findByRole("dialog", { name: "Nowa premia" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("przełożona (D2): godziny i premie zespołu bez stawek, eksportu i zamknięcia", async () => {
    window.history.replaceState({}, "", "/preview/hr-payroll?state=team");
    render(<HrPayrollPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: `Płace · ${closingLabel()}` }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ola Przykładowa" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Kamil Testowy" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Stawka /h" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Eksport do księgowości/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Zamknij miesiąc/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Zatwierdź" })).toHaveLength(4);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("lista miesięcy: 13 miesięcy, poprzedni do zamknięcia", async () => {
    window.history.replaceState({}, "", "/preview/hr-payroll?state=months");
    render(<HrPayrollPreviewPage />);

    expect(await screen.findByRole("link", { name: closingLabel() })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(14);
    expect(screen.getByText("do zamknięcia")).toBeInTheDocument();
    expect(screen.getAllByText("zamknięty")).toHaveLength(11);
    expect(attempted()).toEqual([]);
  });
});
