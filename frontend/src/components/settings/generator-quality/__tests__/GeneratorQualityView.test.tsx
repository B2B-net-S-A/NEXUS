import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GeneratorQualityView } from "../GeneratorQualityView";
import type { GeneratorFeedbackSummary } from "@/lib/cv-generator-feedback";

const SUMMARY: GeneratorFeedbackSummary = {
  days: 30,
  total: 2,
  people: 1,
  generations_ready: 40,
  reasons: [
    { code: "layout", count: 2 },
    { code: "years", count: 1 },
  ],
  clients: [{ client_id: 8, client_name: "Klient X", count: 2 }],
  entries: [
    {
      id: 1,
      created_at: "2026-11-02T10:00:00Z",
      author_name: "Osoba A",
      candidate_id: 5,
      candidate_name: "Kandydat B",
      job_id: 9,
      job_title: "Tester",
      client_name: "Klient X",
      generation_status: "ready",
      reasons: ["layout", "years"],
      detail: "Zły układ tabeli",
    },
  ],
};

const noop = () => {};

describe("GeneratorQualityView", () => {
  it("pokazuje powody, klientów i wpis z opisem", () => {
    render(
      <GeneratorQualityView load={{ status: "success", summary: SUMMARY }} days={30} onDaysChange={noop} onRetry={noop} />,
    );
    expect(screen.getByText("Układ, format, Złe lata albo daty")).toBeInTheDocument();
    expect(screen.getByText("Zły układ tabeli")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kandydat B" })).toHaveAttribute("href", "/candidates/5");
    expect(screen.getAllByText("Klient X").length).toBeGreaterThan(0);
  });

  it("awaria zapytania nie wygląda jak pusta lista", () => {
    const onRetry = vi.fn();
    render(
      <GeneratorQualityView
        load={{ status: "error", forbidden: false, message: "Nie udało się wczytać zgłoszeń." }}
        days={30}
        onDaysChange={noop}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText("Nie udało się wczytać zgłoszeń.")).toBeInTheDocument();
    expect(screen.queryByText("Jeszcze nikt nie zgłosił uwag")).toBeNull();
  });

  it("pusty stan tylko przy udanym odczycie", () => {
    render(
      <GeneratorQualityView
        load={{ status: "success", summary: { ...SUMMARY, total: 0, reasons: [], clients: [], entries: [] } }}
        days={30}
        onDaysChange={noop}
        onRetry={noop}
      />,
    );
    expect(screen.getByText("Jeszcze nikt nie zgłosił uwag")).toBeInTheDocument();
  });

  it("przełącza okres", () => {
    const onDaysChange = vi.fn();
    render(
      <GeneratorQualityView load={{ status: "loading" }} days={30} onDaysChange={onDaysChange} onRetry={noop} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "90 dni" }));
    expect(onDaysChange).toHaveBeenCalledWith(90);
  });
});
