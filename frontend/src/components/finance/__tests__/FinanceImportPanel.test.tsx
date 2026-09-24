import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/finance", () => ({ financeApi: { importWorkbook: vi.fn() } }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

import {
  FinanceImportPanel,
  defaultImportPeriod,
} from "@/components/finance/FinanceImportPanel";

describe("defaultImportPeriod", () => {
  it("wyniki dotyczą miesiąca zakończonego — domyślnie poprzedni", () => {
    expect(defaultImportPeriod(new Date(2026, 8, 24))).toEqual({ year: 2026, month: 8 });
    // Styczeń → grudzień poprzedniego roku.
    expect(defaultImportPeriod(new Date(2027, 0, 5))).toEqual({ year: 2026, month: 12 });
  });

  it("liczy w czasie lokalnym, nie w UTC (1. dnia tuż po północy)", () => {
    // 1 października 00:30 czasu lokalnego — `toISOString` w strefie na
    // wschód od UTC dałby jeszcze 30 września, czyli sierpień jako „poprzedni”.
    expect(defaultImportPeriod(new Date(2026, 9, 1, 0, 30))).toEqual({
      year: 2026,
      month: 9,
    });
  });
});

describe("FinanceImportPanel", () => {
  it("przycisk wysyłki mówi, że importuje, i domyślnie wybiera poprzedni miesiąc", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <FinanceImportPanel onImported={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Importuj plik" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Wybierz plik" })).toBeNull();

    const expected = defaultImportPeriod(new Date());
    expect(screen.getByLabelText("Miesiąc, którego dotyczą dane")).toHaveValue(
      `${expected.year}-${expected.month}`,
    );
  });
});
