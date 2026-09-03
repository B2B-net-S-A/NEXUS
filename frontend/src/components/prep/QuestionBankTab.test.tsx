import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QuestionBankTab } from "@/components/prep/QuestionBankTab";

const questionApi = vi.hoisted(() => ({
  listForJob: vi.fn(),
  unpinFromJob: vi.fn(),
  reorder: vi.fn(),
  create: vi.fn(),
  list: vi.fn(),
  pinToJob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ interviewQuestionsApi: questionApi }));

const pinnedQuestion = {
  id: 4,
  is_pinned: true,
  added_by_source: "manual",
  order_index: 0,
  question: {
    id: 9,
    text: "Jak zapewnisz idempotencję endpointu?",
    ideal_answer: "Klucz idempotencji i atomowy zapis.",
    deal_breaker: false,
    competence_category_id: null,
    skill_tags: ["api"],
    seniority: "senior",
    question_type: "technical",
    source: "manual",
    client_id: null,
    created_by: 1,
    up_votes: 2,
    down_votes: 0,
  },
};

describe("QuestionBankTab read-only", () => {
  it("keeps pinned questions visible and hides every mutation", async () => {
    questionApi.listForJob.mockResolvedValue({ data: [pinnedQuestion] });

    render(<QuestionBankTab jobId={12} clientId={3} readOnly />);

    expect(
      await screen.findByText("Jak zapewnisz idempotencję endpointu?"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Klucz idempotencji/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj pytanie/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Z bazy/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Odepnij" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Przesuń w górę" }),
    ).not.toBeInTheDocument();
    expect(questionApi.unpinFromJob).not.toHaveBeenCalled();
    expect(questionApi.reorder).not.toHaveBeenCalled();
  });

  it("retains authoring controls for write access", async () => {
    questionApi.listForJob.mockResolvedValue({ data: [pinnedQuestion] });

    render(<QuestionBankTab jobId={12} clientId={3} />);

    expect(
      await screen.findByRole("button", { name: /Dodaj pytanie/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Odepnij" }),
    ).toBeInTheDocument();
  });
});
