/**
 * „Kluczowe w tej rekrutacji” na karcie porcji (12.11.2026, makieta M1):
 * krytyczne z dowodem i polski zamiast listy „?”, klik przewija CV.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReviewBatchCard } from "@/components/v2/review-batch/ReviewBatchCard";
import type { ReviewBatchItem } from "@/lib/api/reviewBatch";

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: vi.fn(), dialogs: null }),
}));
vi.mock("@/hooks/useJobPipelineTemplate", () => ({
  useJobPipelineTemplate: () => ({ rejectionReasons: [] }),
}));

const base: ReviewBatchItem = {
  process_id: 9,
  stage_id: 90,
  job_id: 789186,
  job_title: "Data Engineer",
  candidate_id: 663914,
  name: "Marta",
  city: null,
  years: 10,
  position: "Big Data Developer",
  score: 70.38,
  matched_must: ["etl", "batch", "apache kafka"],
  missing_must: ["sql", "bigquery"],
  rate_from_hourly: null,
  rate_currency: null,
  availability_status: "unknown",
  cautions: [],
  budget_hourly: 135,
  key_facts: {
    critical: [
      { label: "ETL", state: "experience", detail: "3 lata 6 mies. w stanowiskach" },
      { label: "SQL", state: "mention", detail: "w CV albo umiejętnościach, bez dat" },
      { label: "BigQuery", state: "none", detail: "brak w CV i profilu" },
    ],
    polish: { state: "native", detail: "ojczysty: polskie imię i nazwisko" },
  },
};

describe("Kluczowe w tej rekrutacji", () => {
  it("pokazuje krytyczne z dowodem i polski zamiast listy „?”", () => {
    render(<ReviewBatchCard item={base} onDecided={() => {}} />);
    expect(screen.getByTestId("review-key-facts")).toBeInTheDocument();
    expect(screen.getByText("3 lata 6 mies. w stanowiskach")).toBeInTheDocument();
    expect(screen.getByLabelText("tylko wzmianka")).toHaveTextContent("~");
    expect(screen.getByLabelText("brak")).toHaveTextContent("✗");
    expect(screen.getByTestId("review-key-polish")).toHaveTextContent("ojczysty: polskie imię i nazwisko");
    expect(screen.getByText(/Z listy wymagań: 3 z 5/)).toBeInTheDocument();
    expect(screen.queryByText("? bigquery")).not.toBeInTheDocument();
  });

  it("klik w pozycję zleca wyszukanie w CV", async () => {
    const onPick = vi.fn();
    render(<ReviewBatchCard item={base} onDecided={() => {}} onPickRequirement={onPick} />);
    await userEvent.setup().click(screen.getByRole("button", { name: /BigQuery/ }));
    expect(onPick).toHaveBeenCalledWith("BigQuery");
  });

  it("rekrutacja bez krytycznych zostaje przy dzisiejszych chipach", () => {
    render(
      <ReviewBatchCard
        item={{ ...base, key_facts: { critical: [], polish: { state: "unknown", detail: "brak danych — sprawdź" } } }}
        onDecided={() => {}}
      />,
    );
    expect(screen.queryByTestId("review-key-facts")).not.toBeInTheDocument();
    expect(screen.getByText("? bigquery")).toBeInTheDocument();
  });
});
