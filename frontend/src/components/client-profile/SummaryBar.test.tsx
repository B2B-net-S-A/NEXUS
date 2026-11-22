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

describe("SummaryBar — marża / mc (dawniej „Aktywne MRR”)", () => {
  it("pełna suma: zwykły tytuł", () => {
    render(<SummaryBar summary={base} />);
    expect(screen.getByText("Marża / mc")).toBeInTheDocument();
  });

  it("część kontraktów bez stawki: kafel mówi, że suma jest niepełna", () => {
    render(<SummaryBar summary={{ ...base, active_mrr_unpriced_contracts: 2 }} />);
    const title = screen.getByText("Marża / mc (niepełna)");
    expect(title.closest("[title]")?.getAttribute("title")).toContain(
      "pominięto 2 aktywne kontrakty bez stawki",
    );
  });

  // Audyt 24.09.2026 (N3): do tej daty ten stan renderował „—”, czyli tak
  // samo jak brak uprawnień — a to dwa różne zdania o kliencie.
  it("brak kwoty (żaden kontrakt nie wyceniony) = „Brak stawek”, nie „—”", () => {
    render(
      <SummaryBar summary={{ ...base, active_mrr: null, active_mrr_unpriced_contracts: 3 }} />,
    );
    expect(screen.getByText("Marża / mc")).toBeInTheDocument();
    expect(screen.getByText("Brak stawek")).toBeInTheDocument();
    expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
  });

  it("brak uprawnień (redakcja: null i licznik 0) = „—”", () => {
    render(
      <SummaryBar summary={{ ...base, active_mrr: null, active_mrr_unpriced_contracts: 0 }} />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("Brak stawek")).not.toBeInTheDocument();
  });

  // Runda 10 (R10-N9-4): brak kursu NBP nie może udawać braku stawek.
  it("brak kursu na wycenionym kontrakcie = „Brak kursu”, nie „Brak stawek”", () => {
    render(
      <SummaryBar
        summary={{
          ...base,
          active_mrr: null,
          active_mrr_unpriced_contracts: 1,
          active_mrr_fx_missing_contracts: 1,
        }}
      />,
    );
    expect(screen.getByText("Brak kursu")).toBeInTheDocument();
    expect(screen.queryByText("Brak stawek")).not.toBeInTheDocument();
    expect(
      screen.getByText("Marża / mc").closest("[title]")?.getAttribute("title"),
    ).toContain("brak kursu NBP dla 1 aktywny kontrakt");
  });

  it("podpis kafla odmienia „kontrakt” (N4)", () => {
    render(<SummaryBar summary={{ ...base, active_contracts: 1 }} />);
    expect(
      screen.getByText("Nasi ludzie").closest("[title]")?.getAttribute("title"),
    ).toContain("1 aktywny kontrakt");
  });
});

describe("SummaryBar — liczby nagłówka klienta (19.11.2026)", () => {
  it("pokazuje otwarte rekrutacje i kto zaczyna", () => {
    render(<SummaryBar summary={{ ...base, open_jobs: 40 }} planned={3} />);
    expect(screen.getByText("Otwarte rekrutacje").closest("div")).toHaveTextContent("40");
    expect(
      screen.getByText("Nasi ludzie").closest("[title]")?.getAttribute("title"),
    ).toContain("+3 zaczyna");
  });

  it("licznik „Wymaga uwagi” tylko, gdy coś czeka", () => {
    const { rerender } = render(<SummaryBar summary={base} attention={0} />);
    expect(screen.queryByText("Wymaga uwagi")).not.toBeInTheDocument();
    rerender(<SummaryBar summary={base} attention={5} />);
    expect(screen.getByText("Wymaga uwagi").closest("div")).toHaveTextContent("5");
  });
});
