import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", () => ({
  interviewFeedbackApi: { list: (...a: unknown[]) => mocks.list(...a) },
}));

import {
  InterviewFeedbackSummary,
  latestFeedbackBySource,
} from "@/components/feedback/InterviewFeedbackSummary";
import type { InterviewFeedbackRow } from "@/lib/api";

function row(overrides: Partial<InterviewFeedbackRow>): InterviewFeedbackRow {
  return {
    id: 1,
    calendar_event_id: 10,
    candidate_id: 5,
    job_id: 9,
    author_id: 1,
    feedback_source: "client_side",
    overall_impression: null,
    interest_level: null,
    candidate_questions: null,
    concerns: null,
    next_step_preference: null,
    technical_fit: 4,
    soft_fit: null,
    overall_fit: null,
    decision: "advance",
    client_questions: null,
    feedback_summary: "Idziemy dalej.",
    ...overrides,
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  mocks.list.mockReset();
});

describe("InterviewFeedbackSummary", () => {
  it("najnowszy wpis każdej strony po zawężeniu do rekrutacji", () => {
    const rows = [
      row({ id: 3, job_id: 8 }),
      row({ id: 2 }),
      row({ id: 1, feedback_source: "candidate_side" }),
      row({ id: 0 }),
    ];
    const latest = latestFeedbackBySource(rows, { jobId: 9 });
    expect(latest.client_side?.id).toBe(2);
    expect(latest.candidate_side?.id).toBe(1);
  });

  it("pobiera feedback kandydata i pokazuje obie karty tylko do odczytu", async () => {
    mocks.list.mockResolvedValue({ data: [row({})] });
    wrap(<InterviewFeedbackSummary candidateId={5} readOnly />);
    expect(await screen.findByText("Idziemy dalej")).toBeInTheDocument();
    expect(screen.getByText("Brak zapisanego feedbacku.")).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith({ candidate_id: 5 });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("„Edytuj” i „Uzupełnij” przekazują stronę, wydarzenie i wpis", () => {
    const onEdit = vi.fn();
    wrap(
      <InterviewFeedbackSummary
        candidateId={5}
        calendarEventId={10}
        rows={[row({ id: 44 })]}
        onEdit={onEdit}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(onEdit).toHaveBeenCalledWith({ source: "client_side", calendarEventId: 10, feedbackId: 44 });
    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij" }));
    expect(onEdit).toHaveBeenCalledWith({ source: "candidate_side", calendarEventId: 10, feedbackId: null });
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it("awaria pobrania nie udaje braku feedbacku", async () => {
    mocks.list.mockImplementation(() =>
      Promise.reject(Object.assign(new Error("HTTP 500"), { response: { status: 500 } })),
    );
    wrap(<InterviewFeedbackSummary candidateId={5} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/nieudane pobranie/);
  });
});
