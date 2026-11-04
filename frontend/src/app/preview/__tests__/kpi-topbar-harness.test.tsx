/**
 * `/preview/kpi-topbar` montuje licznik celów dla trzech ról i nie wysyła
 * ani jednego żądania — rysuje wyłącznie z danych fikcyjnych w propsach.
 */
import { render as rtlRender, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import KpiTopbarPreviewPage from "../kpi-topbar/page";

// „Wygląd” w pasku czyta preferencje Jarvisa przez React Query; w aplikacji
// provider daje główny layout, a bez tokenu zapytanie i tak nie wychodzi.
function render(ui: ReactElement) {
  return rtlRender(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

const adapter = vi.fn();
let previousAdapter: typeof api.defaults.adapter;

beforeEach(() => {
  adapter.mockReset();
  previousAdapter = api.defaults.adapter;
  api.defaults.adapter = adapter;
});

afterEach(() => {
  api.defaults.adapter = previousAdapter;
});

describe("/preview/kpi-topbar", () => {
  it("pokazuje licznik rekrutera, Heada i Delivery Leada bez zapytań", () => {
    render(<KpiTopbarPreviewPage />);
    const [recruiter, head, , deliveryLead] = screen.getAllByTestId("shell-strip");

    expect(
      within(recruiter).getByRole("button", {
        name: "Twoje cele: Weryfikacje 1 z 4 dziś, poniżej tempa; Rekomendacje 6 z 15 tydzień; Placementy 0 z 1 miesiąc",
      }),
    ).toBeInTheDocument();
    expect(
      within(head).getByRole("button", { name: /^Cele zespołu: Weryfikacje 31 z 48 dziś; Rekomendacje 41 z 180 tydzień, poniżej tempa/ }),
    ).toBeInTheDocument();
    expect(
      within(deliveryLead).getByRole("button", {
        name: "Cel portfela: Placementy 2 z 3, poniżej tempa; Hit ratio 20% z 30%; Zamknięte rekrutacje 10 w Q4",
      }),
    ).toBeInTheDocument();
    expect(adapter).not.toHaveBeenCalled();
  });

  it("licznik w pasku to ten sam komponent co w aplikacji: klik otwiera panel", async () => {
    const user = userEvent.setup();
    render(<KpiTopbarPreviewPage />);
    const [, , , deliveryLead] = screen.getAllByTestId("shell-strip");

    await user.click(within(deliveryLead).getByRole("button", { name: /^Cel portfela/ }));
    // Ramki „Panel po kliknięciu” mają własne nazwy — otwarty panel to „Cel portfela”.
    const panel = await screen.findByRole("dialog", { name: "Cel portfela" });
    expect(within(panel).getByText("Brakuje 1 placementu.")).toBeInTheDocument();
    expect(adapter).not.toHaveBeenCalled();
  });

  it("Delivery Lead bez zamkniętych rekrutacji ma notatkę zamiast celu", () => {
    render(<KpiTopbarPreviewPage />);
    const frame = screen.getByRole("dialog", { name: "Delivery Lead bez zamkniętych rekrutacji" });
    expect(
      within(frame).getByText("Cel pojawi się po zamknięciu pierwszej rekrutacji w kwartale."),
    ).toBeInTheDocument();
    expect(within(frame).queryByRole("progressbar")).toBeNull();
  });
});
