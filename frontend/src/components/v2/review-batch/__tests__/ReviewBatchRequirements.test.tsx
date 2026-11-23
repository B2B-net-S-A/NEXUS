/**
 * Schodki po wymaganiach na karcie porcji (decyzja Artura 23.11.2026, wariant B,
 * makiety https://claude.ai/artifact/5SJB7AYPZWbFkVKf77jhnN): „Musi mieć 7 z 10”
 * z brakami, mile widziane i powód miejsca w linii „Kolejność”.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { orderLine, ReviewBatchCard } from "@/components/v2/review-batch/ReviewBatchCard";
import type { ReviewBatchItem, ReviewBatchRequirements } from "@/lib/api/reviewBatch";

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: vi.fn(), dialogs: null }),
}));
vi.mock("@/hooks/useJobPipelineTemplate", () => ({
  useJobPipelineTemplate: () => ({ rejectionReasons: [] }),
}));

const requirements: ReviewBatchRequirements = {
  critical_missing: 0,
  must_met: 7,
  must_total: 10,
  nice_met: 2,
  nice_total: 7,
  must: [
    { label: "Apache Spark", state: "experience" },
    { label: "Spark SQL", state: "none" },
    { label: "DataFrames", state: "none" },
    { label: "Apache Iceberg", state: "none" },
    { label: "MongoDB", state: "mention" },
    { label: "Python", state: "experience" },
    { label: "Jenkins", state: "experience" },
    { label: "Prometheus", state: "experience" },
    { label: "Grafana", state: "experience" },
    { label: "Scrum", state: "mention" },
  ],
  nice: [
    { label: "Jira", state: "experience" },
    { label: "Kanban", state: "mention" },
    { label: "Delta Lake", state: "none" },
  ],
};

const item: ReviewBatchItem = {
  process_id: 1,
  stage_id: 10,
  job_id: 101,
  job_title: "Data Engineer (Spark)",
  candidate_id: 77,
  name: "Ola",
  city: "Kraków",
  years: 9,
  position: "Data Engineer",
  score: 68.76,
  matched_must: ["apache spark"],
  missing_must: ["apache spark sql"],
  rate_from_hourly: null,
  rate_currency: null,
  availability_status: "unknown",
  cautions: [],
  budget_hourly: null,
  requirements,
};

describe("orderLine ze schodkami", () => {
  it("mówi, ile musi mieć osoba spełnia, przed wynikiem", () => {
    expect(orderLine(item)).toBe("Kolejność: 7 z 10 musi mieć · 69%");
    expect(orderLine({ ...item, order_active: true })).toBe("Kolejność: 7 z 10 musi mieć · 69% + aktywnie szuka");
  });

  it("bez listy musi mieć zostaje jak dotąd", () => {
    expect(orderLine({ ...item, requirements: { ...requirements, must_met: 0, must_total: 0, must: [] } })).toBeNull();
    expect(orderLine({ ...item, requirements: null })).toBeNull();
  });
});

describe("karta ze schodkami", () => {
  it("pokazuje licznik, braki i mile widziane zamiast „?” silnika", async () => {
    const onPick = vi.fn();
    render(<ReviewBatchCard item={item} onDecided={vi.fn()} onPickRequirement={onPick} />);
    const block = screen.getByTestId("review-requirements");
    expect(block).toHaveTextContent("Musi mieć 7 z 10");
    expect(block).toHaveTextContent("brak: Spark SQL, DataFrames, Apache Iceberg");
    expect(block).toHaveTextContent("Mile widziane 2 z 7");
    expect(screen.queryByText("? apache spark sql")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Spark SQL/ }));
    expect(onPick).toHaveBeenCalledWith("Spark SQL");
  });

  it("bez schodków zostają chipy z migawki", () => {
    render(<ReviewBatchCard item={{ ...item, requirements: null }} onDecided={vi.fn()} />);
    expect(screen.queryByTestId("review-requirements")).not.toBeInTheDocument();
    expect(screen.getByText("? apache spark sql")).toBeInTheDocument();
  });
});
