import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SummaryBar } from "./SummaryBar";
import type { ClientProfileSummary } from "@/types/client-profile";

const base: ClientProfileSummary = {
  open_jobs: 0,
  active_consultants: 3,
  active_contracts: 3,
  total_placements: 3,
  active_mrr: 1000,
  active_mrr_unpriced_contracts: 0,
  ltv: null,
  avg_time_to_fill_days: null,
};

describe("SummaryBar — Aktywne MRR", () => {
  it("pełna suma: zwykły tytuł", () => {
    render(<SummaryBar summary={base} />);
    expect(screen.getByText("Aktywne MRR")).toBeInTheDocument();
  });

  it("część kontraktów bez stawki: kafel mówi, że suma jest niepełna", () => {
    render(<SummaryBar summary={{ ...base, active_mrr_unpriced_contracts: 2 }} />);
    const title = screen.getByText("Aktywne MRR (niepełne)");
    expect(title.closest("[title]")?.getAttribute("title")).toContain(
      "pominięto 2 aktywne kontrakty bez stawki",
    );
  });

  it("brak kwoty (żaden kontrakt nie wyceniony) = „—”, bez dopisku o niepełnej sumie", () => {
    render(
      <SummaryBar summary={{ ...base, active_mrr: null, active_mrr_unpriced_contracts: 3 }} />,
    );
    expect(screen.getByText("Aktywne MRR")).toBeInTheDocument();
    expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
  });
});
