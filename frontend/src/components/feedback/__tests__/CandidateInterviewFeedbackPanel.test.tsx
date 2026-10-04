import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", () => ({
  interviewFeedbackApi: { list: (...a: unknown[]) => mocks.list(...a) },
}));

import {
  CandidateInterviewFeedbackPanel,
  groupFeedbackByJob,
} from "@/components/feedback/CandidateInterviewFeedbackPanel";
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
    feedback_summary: "Klient chce iść dalej.",
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

describe("CandidateInterviewFeedbackPanel", () => {
  it("grupuje feedback po rekrutacji, żeby jedna rozmowa nie przykryła drugiej", () => {
    const groups = groupFeedbackByJob([
      row({ id: 1, job_id: 9 }),
      row({ id: 2, job_id: 7, feedback_summary: "Inna rekrutacja" }),
      row({ id: 3, job_id: null }),
    ]);
    expect(groups.map((g) => g.jobId)).toEqual([9, 7, null]);
  });

  it("pokazuje tytuł każdej rekrutacji i treść jej feedbacku, bez przycisków edycji", async () => {
    mocks.list.mockResolvedValue({
      data: [
        row({ id: 1, job_id: 9, feedback_summary: "Klient chce iść dalej." }),
        row({ id: 2, job_id: 7, feedback_summary: "Klient odrzuca.", decision: "reject" }),
      ],
    });
    wrap(
      <CandidateInterviewFeedbackPanel
        candidateId={5}
        jobTitles={new Map([[9, "Java Dev"], [7, "QA Lead"]])}
      />,
    );
    expect(await screen.findByText("Java Dev")).toBeInTheDocument();
    expect(screen.getByText("QA Lead")).toBeInTheDocument();
    expect(screen.getByText("Klient chce iść dalej.")).toBeInTheDocument();
    expect(screen.getByText("Klient odrzuca.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edytuj|Uzupełnij/ })).toBeNull();
    expect(mocks.list).toHaveBeenCalledWith({ candidate_id: 5 });
  });

  it("brak feedbacku to podpowiedź, a nie pusta ramka", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    wrap(<CandidateInterviewFeedbackPanel candidateId={5} jobTitles={new Map()} />);
    expect(await screen.findByText(/Brak zapisanego feedbacku/)).toBeInTheDocument();
  });

  it("nieudane pobranie mówi o błędzie, nie udaje pustki", async () => {
    mocks.list.mockRejectedValue(
      Object.assign(new Error("x"), { response: { status: 403, data: { detail: "Brak dostępu" } } }),
    );
    wrap(<CandidateInterviewFeedbackPanel candidateId={5} jobTitles={new Map()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Brak dostępu");
  });
});

describe("CandidateInterviewFeedbackPanel — debrief", () => {
  it("każdy debrief ma własną kartę z warunkiem, ofertą i pytaniami klienta", async () => {
    mocks.list.mockResolvedValue({
      data: [
        row({
          id: 2,
          job_id: 9,
          feedback_source: "candidate_side",
          overall_impression: 5,
          offer_acceptance: "likely",
          acceptance_condition: "Chce jednak 125 zł/h",
          concerns: "Projekt mu się podoba",
          client_questions: "Kafka?\nSpring?",
          decision: null,
          technical_fit: null,
          feedback_summary: null,
          author_name: "Sandra Strzelak",
          calendar_event_start: "2026-10-04T13:46:00Z",
        }),
        row({
          id: 1,
          job_id: 9,
          feedback_source: "candidate_side",
          overall_impression: 3,
          offer_acceptance: "yes",
          acceptance_condition: "Runda 1: bez warunków",
          decision: null,
          technical_fit: null,
          feedback_summary: null,
        }),
      ],
    });
    wrap(<CandidateInterviewFeedbackPanel candidateId={5} jobTitles={new Map([[9, "Java Dev"]])} />);
    const cards = await screen.findAllByTestId("debrief-feedback-card");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("Warunek / zastrzeżenie: Chce jednak 125 zł/h");
    expect(cards[0]).toHaveTextContent("Czy przyjmie ofertę: Raczej tak");
    expect(cards[0]).toHaveTextContent("Komentarz kandydata: Projekt mu się podoba");
    expect(cards[0]).toHaveTextContent("Pytania klienta (2)");
    expect(cards[0]).toHaveTextContent("zapisał(a) Sandra Strzelak");
    expect(cards[1]).toHaveTextContent("Runda 1: bez warunków");
    // Bez pustych kart „Brak zapisanego feedbacku” obok debriefów.
    expect(screen.queryByText("Brak zapisanego feedbacku.")).not.toBeInTheDocument();
  });
});
