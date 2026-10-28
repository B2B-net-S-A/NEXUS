import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AiAssessmentBatch, AiAssessmentRow } from "@/lib/ai-assessment";

const mocks = vi.hoisted(() => ({
  assess: vi.fn(),
  latest: vi.fn(),
}));

vi.mock("@/lib/ai-assessment", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/ai-assessment")>();
  return {
    ...actual,
    aiAssessmentApi: {
      assess: (...a: unknown[]) => mocks.assess(...a),
      latest: (...a: unknown[]) => mocks.latest(...a),
    },
  };
});

import { AiAssessmentPanel, AssessWithAiButton } from "../AiAssessmentPanel";

// Fikcyjne osoby.
const EWA = { candidateId: 1, fullName: "Ewa Marczak" };
const PIOTR = { candidateId: 2, fullName: "Piotr Lis" };
const OLA = { candidateId: 3, fullName: "Ola Nowak" };

function row(over: Partial<AiAssessmentRow> & { candidate_id: number }): AiAssessmentRow {
  return {
    full_name: `Osoba ${over.candidate_id}`,
    selection_index: 0,
    verdict: null,
    strength: null,
    must_found: 0,
    must_total: 0,
    reasons: [],
    error_kind: null,
    reused: false,
    ...over,
  };
}

function batch(rows: AiAssessmentRow[]): AiAssessmentBatch {
  return {
    batch_id: "00000000-0000-4000-8000-000000000000",
    created_at: "2026-10-28T15:40:00Z",
    rows,
    daily_limit: 150,
    remaining_today: 147,
  };
}

const RESULT = batch([
  row({
    candidate_id: 2,
    full_name: PIOTR.fullName,
    selection_index: 1,
    verdict: "no_fit",
    strength: 1,
    reasons: [{ text: "Kadry i płace.", quote: "kadr i płac", source: "cv" }],
  }),
  row({
    candidate_id: 1,
    full_name: EWA.fullName,
    selection_index: 0,
    verdict: "call",
    strength: 4,
    reasons: [{ text: "Wdrażała IdentityIQ.", quote: "SailPoint IdentityIQ", source: "cv" }],
  }),
  row({ candidate_id: 3, full_name: OLA.fullName, selection_index: 2, error_kind: "no_cv" }),
]);

afterEach(() => {
  vi.clearAllMocks();
});

function rows(): HTMLElement[] {
  return screen.getAllByTestId("ai-assessment-row");
}

describe("AiAssessmentPanel", () => {
  it("układa osoby w kolejności dzwonienia, z cytatem i bez werdyktu na końcu", async () => {
    mocks.assess.mockResolvedValue(RESULT);
    render(
      <AiAssessmentPanel
        jobId={7}
        people={[EWA, PIOTR, OLA]}
        onAdd={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(rows().map((r) => r.dataset.verdict)).toEqual(["call", "no_fit", "none"]);
    expect(within(rows()[0]).getByText("Ewa Marczak")).toBeInTheDocument();
    expect(within(rows()[0]).getByText("CV: „SailPoint IdentityIQ”")).toBeInTheDocument();
    expect(within(rows()[2]).getByText("AI nie oceniło — brak CV w NEXUSIE")).toBeInTheDocument();
    expect(screen.getByText("Dzwoń · 1")).toBeInTheDocument();
    expect(screen.getByText("Nie pasuje · 1")).toBeInTheDocument();
    expect(screen.getByText("AI nie oceniło · 1")).toBeInTheDocument();
    const [jobId, body] = mocks.assess.mock.calls[0];
    expect(jobId).toBe(7);
    expect(body).toMatchObject({ candidate_ids: [1, 2, 3], first_index: 0, refresh: false });
  });

  it("dzieli zaznaczenie na paczki z jednym batch_id", async () => {
    const people = Array.from({ length: 13 }, (_, i) => ({ candidateId: i + 1, fullName: `P${i}` }));
    mocks.assess.mockImplementation((_job: number, body: { candidate_ids: number[] }) =>
      Promise.resolve(
        batch(body.candidate_ids.map((id) => row({ candidate_id: id, verdict: "maybe" }))),
      ),
    );
    render(<AiAssessmentPanel jobId={7} people={people} onAdd={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(rows()).toHaveLength(13));
    const bodies = mocks.assess.mock.calls.map((c) => c[1]);
    expect(bodies.map((b) => b.candidate_ids.length)).toEqual([6, 6, 1]);
    expect(new Set(bodies.map((b) => b.batch_id)).size).toBe(1);
    expect(bodies.map((b) => b.first_index).sort((a, b) => a - b)).toEqual([0, 6, 12]);
  });

  it("awaria paczki zostawia osoby bez werdyktu i mówi, co się stało", async () => {
    mocks.assess.mockRejectedValue({
      response: { status: 500, data: { detail: "Błąd serwera" } },
    });
    render(<AiAssessmentPanel jobId={7} people={[EWA]} onAdd={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0].dataset.verdict).toBe("none");
    expect(screen.getByText("AI nie oceniło — spróbuj ponownie później")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByTestId("ai-assessment-add-calls")).toBeDisabled();
  });

  it("po dziennym limicie reszta zaznaczenia zostaje na liście bez werdyktu", async () => {
    const people = Array.from({ length: 20 }, (_, i) => ({ candidateId: i + 1, fullName: `P${i}` }));
    let call = 0;
    mocks.assess.mockImplementation((_job: number, body: { candidate_ids: number[] }) => {
      call += 1;
      if (call === 1) {
        return Promise.resolve(
          batch(body.candidate_ids.map((id) => row({ candidate_id: id, verdict: "maybe" }))),
        );
      }
      return Promise.reject({
        response: {
          status: 429,
          data: { detail: { code: "ai_assessment_daily_limit", message: "Dzienny limit oceny AI to 150 osób. Dziś zostało 0." } },
        },
      });
    });
    render(<AiAssessmentPanel jobId={7} people={people} onAdd={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(rows()).toHaveLength(20));
    expect(rows().filter((r) => r.dataset.verdict === "maybe")).toHaveLength(6);
    expect(screen.getAllByText("AI nie oceniło — dzienny limit oceny wyczerpany")).toHaveLength(14);
    expect(screen.queryByTestId("ai-assessment-progress")).not.toBeInTheDocument();
  });

  it("dodaje tylko „Dzwoń” w kolejności i oznacza dodanych", async () => {
    mocks.assess.mockResolvedValue(RESULT);
    const onAdd = vi.fn().mockResolvedValue([1]);
    render(
      <AiAssessmentPanel jobId={7} people={[EWA, PIOTR, OLA]} onAdd={onAdd} onClose={vi.fn()} />,
    );
    const button = await screen.findByText("Dodaj 1 „Dzwoń” do Nowych w tej kolejności");
    await waitFor(() => expect(button.closest("button")).not.toBeDisabled());
    fireEvent.click(button);
    await waitFor(() => expect(onAdd).toHaveBeenCalledWith([1]));
    expect(await within(rows()[0]).findByText("Dodano do Nowych")).toBeInTheDocument();
    expect(screen.getByText("Dodaj 0 „Dzwoń” do Nowych w tej kolejności").closest("button")).toBeDisabled();
  });

  it("bez zaznaczenia pokazuje ostatnią zapisaną ocenę bez wołania modelu", async () => {
    mocks.latest.mockResolvedValue(RESULT);
    render(<AiAssessmentPanel jobId={7} people={null} onAdd={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(mocks.assess).not.toHaveBeenCalled();
    expect(screen.queryByTestId("ai-assessment-rerun")).not.toBeInTheDocument();
  });

  it("tylko podgląd nie ma przycisku dodania", async () => {
    mocks.assess.mockResolvedValue(RESULT);
    render(
      <AiAssessmentPanel jobId={7} people={[EWA]} onAdd={vi.fn()} onClose={vi.fn()} readOnly />,
    );
    // Panel bierze z odpowiedzi tylko osoby z zaznaczenia.
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(screen.queryByTestId("ai-assessment-add-calls")).not.toBeInTheDocument();
  });
});

describe("AssessWithAiButton", () => {
  it("blokuje ponad 30 osób z wyjaśnieniem", () => {
    render(<AssessWithAiButton count={31} onClick={vi.fn()} />);
    const button = screen.getByTestId("assess-with-ai");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Oceniamy najwyżej 30 osób naraz — odznacz część.");
  });
});
