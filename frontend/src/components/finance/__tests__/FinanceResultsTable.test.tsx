import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FinanceResultsTable } from "@/components/finance/FinanceResultsTable";
import type { FinanceResultRow } from "@/lib/api/finance";

/**
 * Nagłówek i wiersz muszą iść w TEJ SAMEJ kolejności. Do 02.10.2026 nagłówek
 * mapował listę kolumn, a wiersz składał się osobno („Klient" wstawiany przed
 * fakturą), więc przestawienie jednej strony dawało kwoty pod cudzym
 * nagłówkiem — bez żadnego błędu.
 */

const row = {
  id: 1,
  row_number: 2,
  consultant_name: "Osoba Testowa",
  client_name: "Klient Fikcyjny",
  cost_rate_md: 111,
  md_count: 22,
  compensation: 333,
  revenue_rate_md: 444,
  invoice_amount: 555,
  margin_pln: 66,
  margin_pct: 0.077,
  margin_percent: 7.7,
  edited_fields: [],
} as unknown as FinanceResultRow;

/** Wartość wiersza, która ma stać pod danym nagłówkiem. */
const EXPECTED_UNDER: Record<string, string> = {
  Kandydat: "Osoba Testowa",
  Klient: "Klient Fikcyjny",
  "Stawka kosztowa": "111,00",
  "Ilość MD": "22",
  Wynagrodzenie: "333,00",
  "Stawka przychodowa": "444,00",
  Faktura: "555,00",
  Marża: "66,00",
  "Marża %": "7,7%",
};

function renderTable(rows: FinanceResultRow[] = [row]) {
  return render(
    <FinanceResultsTable
      rows={rows}
      sort="row_number"
      direction="asc"
      onSort={vi.fn()}
      onEdit={vi.fn()}
      onError={vi.fn()}
      searching={false}
    />,
  );
}

describe("FinanceResultsTable — kolejność kolumn", () => {
  it("„Klient” stoi zaraz po „Kandydacie”, a jednostka jest w nagłówku", () => {
    renderTable();
    const headers = screen
      .getAllByRole("columnheader")
      .map((th) => th.textContent ?? "");
    expect(headers).toEqual([
      "Kandydat",
      "Klient",
      "Stawka kosztowazł/MD",
      "Ilość MD",
      "Wynagrodzeniezł",
      "Stawka przychodowazł/MD",
      "Fakturazł",
      "Marżazł",
      "Marża %",
    ]);
  });

  it("komórki pierwszego wiersza idą w kolejności nagłówków", () => {
    renderTable();
    const headers = screen.getAllByRole("columnheader");
    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells).toHaveLength(headers.length);

    headers.forEach((th, index) => {
      // Nagłówek bez jednostki (jednostka jest osobnym, drobnym napisem).
      const name = Object.keys(EXPECTED_UNDER)
        .filter((key) => (th.textContent ?? "").startsWith(key))
        .sort((a, b) => b.length - a.length)[0];
      expect(name, `nieznany nagłówek „${th.textContent}”`).toBeDefined();
      expect(cells[index]).toHaveTextContent(EXPECTED_UNDER[name]);
    });
  });

  it("brak klienta to przygaszona kreska, a nie pusta komórka", () => {
    renderTable([{ ...row, client_name: null } as FinanceResultRow]);
    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("—");
  });

  it("nazwy sortowania i komórek zostają pełne (z „MD” i „PLN”)", () => {
    renderTable();
    expect(
      screen.getByRole("button", { name: "Sortuj po Stawka kosztowa MD" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sortuj po Marża PLN" }),
    ).toBeInTheDocument();
  });
});
