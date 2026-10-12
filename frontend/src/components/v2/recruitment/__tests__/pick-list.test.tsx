import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EmploymentMarker } from "@/lib/employment-marker";
import { PickList, type PickRow } from "../pick-list";

const WORKING: EmploymentMarker = {
  phase: "working",
  source: "contract",
  elsewhere: true,
  clients: [
    {
      client_id: 4,
      client_name: "Bank Przykładowy",
      contract_id: 40,
      phase: "working",
      order_end_date: "2026-12-31",
    },
  ],
};

function row(overrides: Partial<PickRow> = {}): PickRow {
  return {
    candidateId: 1,
    fullName: "Anna Przykładowa",
    fitScore: 80,
    rateLabel: null,
    availabilityLabel: null,
    note: null,
    facts: "Java Developer · 8 lat dośw. · Warszawa",
    sourceLabel: null,
    warnings: [],
    ...overrides,
  };
}

describe("PickList — znacznik „Pracuje u nas”", () => {
  it("pigułka stoi obok, nie w nazwie przycisku ani w linii faktów", () => {
    render(
      <PickList
        rows={[row({ employment: WORKING }), row({ candidateId: 2, fullName: "Jan Testowy" })]}
        selected={new Set()}
        onToggle={vi.fn()}
        readOnly={false}
        emptyText="Brak"
        label="Osoby"
        onPreview={vi.fn()}
      />,
    );

    const [employed, other] = screen.getAllByRole("listitem");
    expect(
      within(employed).getByText("Pracuje u nas · Bank Przykładowy · do 31.12.2026"),
    ).toBeInTheDocument();
    // Nazwa dostępna przycisku to samo nazwisko — po niej szukają testy i czytnik.
    expect(within(employed).getByRole("button", { name: "Anna Przykładowa" })).toBeInTheDocument();
    expect(within(employed).getByText("Java Developer · 8 lat dośw. · Warszawa")).toBeInTheDocument();
    // Znacznik niczego nie blokuje: osobę da się zaznaczyć.
    expect(within(employed).getByRole("checkbox", { name: "Zaznacz Anna Przykładowa" })).toBeEnabled();
    expect(within(other).queryByText(/Pracuje u nas/)).toBeNull();
  });
});
