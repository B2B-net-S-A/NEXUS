import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: (...a: unknown[]) => post(...a), get: vi.fn(), put: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess: vi.fn(), showInfo: vi.fn(), showToast: vi.fn() }),
}));

import {
  RecommendationCardQuestions,
  RecommendationCardView,
} from "@/components/v2/screening/RecommendationCardView";
import { recommendationCardQueryKey, type RecommendationCard } from "@/lib/api/recommendationCards";

const CARD: RecommendationCard = {
  candidate_id: 1,
  job_id: 2,
  exists: true,
  fields: {},
  previous: {},
  suggestions: {},
  questions: [
    {
      number: 1,
      question: "Java 17+?",
      answer: "Tylko Java 8.",
      source: "sheet",
      question_id: "q1",
      deal_breaker: "nie pracował z Javą 17+",
      deal_breaker_hit: false,
    },
    { number: 2, question: "Chmura?", answer: "AWS", source: "sheet", question_id: "q2", deal_breaker: null },
  ],
  completeness: { status: "partial", filled: 0, total: 10, missing: [] },
  labels: {},
  editable_fields: [],
  legacy_text: "",
};

function renderWithClient(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
  return qc;
}

describe("RecommendationCardQuestions — „Odpada, gdy…”", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje warunek pod pytaniem; bez edycji nie ma pola wyboru", () => {
    render(<RecommendationCardQuestions card={CARD} />);
    expect(screen.getByText("Odpada, gdy: nie pracował z Javą 17+")).toBeInTheDocument();
    expect(screen.getAllByText(/Odpada, gdy/)).toHaveLength(1);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("trafienie bez edycji pokazuje się jako zdanie", () => {
    const hit = {
      ...CARD,
      questions: [{ ...CARD.questions[0], deal_breaker_hit: true }, CARD.questions[1]],
    };
    render(<RecommendationCardQuestions card={hit} />);
    expect(screen.getByText("Odpowiedź narusza deal-breaker")).toBeInTheDocument();
  });

  it("zaznaczenie zapisuje trafienie i podmienia kartę w pamięci zapytań", async () => {
    const updated = {
      ...CARD,
      questions: [{ ...CARD.questions[0], deal_breaker_hit: true }, CARD.questions[1]],
    };
    post.mockResolvedValue({ data: updated });
    const qc = renderWithClient(<RecommendationCardQuestions card={CARD} editable />);

    const checkbox = screen.getByRole("checkbox", { name: "Odpowiedź narusza deal-breaker" });
    expect(checkbox).not.toBeChecked();
    // Pytanie bez „Odpada, gdy…” nie ma pola.
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.click(checkbox);

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/recommendation-cards/deal-breaker", {
        candidate_id: 1,
        job_id: 2,
        question_id: "q1",
        hit: true,
      }),
    );
    await waitFor(() => expect(qc.getQueryData(recommendationCardQueryKey(1, 2))).toEqual(updated));
  });

  it("błąd zapisu idzie do toasta, bez surowego `detail`", async () => {
    post.mockRejectedValue({ response: { status: 409, data: { detail: { code: "x" } } } });
    renderWithClient(<RecommendationCardQuestions card={CARD} editable />);
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(showError).toHaveBeenCalledTimes(1));
    expect(typeof showError.mock.calls[0][0]).toBe("string");
  });

  it("harness: zmiana bez serwera przez `onDealBreakerHitChange`", () => {
    const onChange = vi.fn();
    render(<RecommendationCardQuestions card={CARD} editable onDealBreakerHitChange={onChange} />);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith("q1", true);
    expect(post).not.toHaveBeenCalled();
  });

  it("zwarta karta ostrzega o trafieniu", () => {
    const hit = {
      ...CARD,
      questions: [{ ...CARD.questions[0], deal_breaker_hit: true }, CARD.questions[1]],
    };
    render(<RecommendationCardView card={hit} />);
    expect(screen.getByText("Odpowiedź na pytanie 1 narusza „Odpada, gdy…”.")).toBeInTheDocument();
  });
});
