/**
 * Panel „P0 — ultrapilne teraz” (27.10.2026): stały na pulpicie u każdego,
 * znika bez P0 i przy błędzie, pokazuje 3 wiersze i resztę licznikiem.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { P0NowPanel } from "@/components/v2/jobs/p0/P0NowPanel";

const state = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));

vi.mock("@/lib/api/jobP0", () => ({ useP0Jobs: () => state.value }));

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000 + 60_000).toISOString();

function item(job_id: number, hours: number) {
  return {
    job_id,
    title: `Rekrutacja testowa ${job_id}`,
    client_name: "Klient Fikcyjny",
    p0_until: inHours(hours),
    p0_reason: "Klient czeka na CV",
    p0_set_at: null,
    p0_set_by_name: "Anna Testowa",
    delivery_lead_name: "Ewa Przykładowa",
    recruiters: ["Jan Próbny"],
  };
}

describe("P0NowPanel", () => {
  beforeEach(() => {
    state.value = {};
  });

  it("bez P0 nic nie renderuje", () => {
    state.value = { isSuccess: true, data: { items: [], can_set: false } };
    const { container } = render(<P0NowPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("błąd zapytania nie udaje pustki — panel się chowa, P0 jest też na liście", () => {
    state.value = { isSuccess: false, isError: true };
    const { container } = render(<P0NowPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("pokazuje powód, ludzi i link do tablicy; wygasłe P0 pomija", () => {
    state.value = {
      isSuccess: true,
      data: { items: [item(1, 23), { ...item(2, 1), p0_until: inHours(-2) }], can_set: false },
    };
    render(<P0NowPanel />);
    expect(screen.getByRole("heading")).toHaveTextContent("P0 — ultrapilne teraz · 1");
    const rows = screen.getAllByTestId("p0-now-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("„Klient czeka na CV”");
    expect(screen.getByRole("link", { name: "Otwórz tablicę" })).toHaveAttribute("href", "/jobs/1");
  });

  it("pokazuje 3 wiersze, resztę liczy", () => {
    state.value = {
      isSuccess: true,
      data: { items: [1, 2, 3, 4, 5].map((id) => item(id, 10 + id)), can_set: true },
    };
    render(<P0NowPanel />);
    expect(screen.getAllByTestId("p0-now-row")).toHaveLength(3);
    expect(screen.getByText(/I jeszcze 2/)).toBeInTheDocument();
  });
});
