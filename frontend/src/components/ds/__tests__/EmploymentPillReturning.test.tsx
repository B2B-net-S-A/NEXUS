/**
 * „Wraca na rynek DD.MM” obok znacznika „Pracuje u nas” (22.10.2026): druga
 * plakietka pojawia się wyłącznie przy przekazaniu z opieki, pierwsza zostaje
 * bez zmian. Dane fikcyjne.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmploymentPill } from "@/components/ds/EmploymentMarker";
import type { EmploymentMarker } from "@/lib/employment-marker";

const base: EmploymentMarker = {
  phase: "working",
  source: "contract",
  elsewhere: null,
  clients: [
    { client_id: 1, client_name: "Bank Przykładowy", contract_id: 10, phase: "working", order_end_date: "2026-11-30" },
  ],
};

describe("EmploymentPill · Wraca na rynek", () => {
  it("bez przekazania jedna plakietka", () => {
    const { container } = render(<EmploymentPill marker={base} />);
    expect(screen.getByText("Pracuje u nas · Bank Przykładowy · do 30.11.2026")).toBeInTheDocument();
    expect(container.querySelector("[data-returns-to-market]")).toBeNull();
  });

  it("z przekazaniem druga plakietka z datą końca", () => {
    render(
      <EmploymentPill marker={{ ...base, returns_to_market: true, returns_to_market_on: "2026-11-30" }} />,
    );
    expect(screen.getByText("Wraca na rynek 30.11")).toBeInTheDocument();
    expect(screen.getByText("Pracuje u nas · Bank Przykładowy · do 30.11.2026")).toBeInTheDocument();
  });
});
