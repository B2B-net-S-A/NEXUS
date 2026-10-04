import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { RecommendationCard } from "@/lib/api/recommendationCards";

const showSuccess = vi.fn();
const showError = vi.fn();
const mutate = vi.fn();

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showInfo: vi.fn() }),
}));

const CARD: RecommendationCard = {
  candidate_id: 1,
  job_id: 2,
  exists: true,
  fields: { rate: { raw: "120", value: 120, source: "manual" } },
  previous: {},
  suggestions: {},
  questions: [],
  completeness: { status: "partial", filled: 1, total: 10, missing: [] },
  labels: { rate: "Stawka" },
  editable_fields: ["rate"],
  legacy_text: "Stawka: 120",
};

vi.mock("@/lib/api/recommendationCards", () => ({
  useRecommendationCard: () => ({ data: CARD, isLoading: false, isError: false }),
  useSaveRecommendationCard: () => ({ mutate, isPending: false }),
}));

import { RecommendationCardDialog } from "../RecommendationCardDialog";

function renderDialog(onOpenChange = vi.fn()) {
  render(
    <RecommendationCardDialog
      open
      onOpenChange={onOpenChange}
      candidateId={1}
      jobId={2}
      candidateName="Tomasz Wzorcowy"
    />,
  );
  fireEvent.change(screen.getByLabelText("Stawka"), { target: { value: "130" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz kartę" }));
  return onOpenChange;
}

describe("RecommendationCardDialog — zapis", () => {
  beforeEach(() => {
    showSuccess.mockReset();
    showError.mockReset();
    mutate.mockReset();
  });

  it("po zapisie potwierdza i zamyka okno", () => {
    mutate.mockImplementation((_fields, opts) => opts.onSuccess());
    const onOpenChange = renderDialog();

    expect(mutate).toHaveBeenCalledWith({ rate: "130" }, expect.anything());
    expect(showSuccess).toHaveBeenCalledWith("Karta rekomendacji zapisana.");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("po błędzie zostawia okno otwarte z wpisanymi danymi", () => {
    mutate.mockImplementation((_fields, opts) => opts.onError(new Error("x")));
    const onOpenChange = renderDialog();

    expect(showError).toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Stawka")).toHaveValue("130");
  });
});
