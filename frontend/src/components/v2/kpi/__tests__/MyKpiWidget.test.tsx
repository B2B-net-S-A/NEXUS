import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MyKpiWidget } from "@/components/v2/kpi/MyKpiWidget";

vi.mock("@/hooks/useMyKpis", () => ({
  useMyKpis: () => ({
    isLoading: false,
    error: null,
    data: [
      {
        kpi_id: "calls",
        period: "day",
        title_pl: "Rozmowy",
        description_pl: "Wykonane rozmowy",
        target: 15,
        current: 4,
        progress_pct: 27,
        state: "behind",
        deadline_hours_left: 5,
      },
    ],
  }),
}));

// Szczegóły KPI były dostępne wyłącznie po najechaniu myszą.
describe("MyKpiWidget (compact) — szczegóły bez myszy", () => {
  it("otwiera szczegóły fokusem klawiatury i zamyka Escape", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    expect(screen.queryByRole("tooltip")).toBeNull();

    await user.tab();
    expect(screen.getByRole("button", { name: "Moje KPI" })).toHaveFocus();
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("kliknięcie (dotyk) otwiera szczegóły i nie zamyka ich od razu", async () => {
    const user = userEvent.setup();
    render(<MyKpiWidget />);
    await user.click(screen.getByRole("button", { name: "Moje KPI" }));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });
});
