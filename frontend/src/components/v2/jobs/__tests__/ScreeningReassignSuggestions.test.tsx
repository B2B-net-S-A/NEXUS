/**
 * Przepięcie → podpowiedzi Luny w arkuszu screeningu (Pipeline v4, 23.09.2026).
 *
 * Arkusz jest prawdziwy (`useScreeningForm` + `ScreeningFormFields`), sieć
 * zamockowana na granicy `screeningApi`. Sprawdzamy: baner tylko przy
 * przepięciu, „Przyjmij / Popraw / Odrzuć podpowiedź", awarię Luny jako
 * komunikat oraz ścieżkę „Pomiń brakujące — przepięcie" aż do payloadu zapisu.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getForStage = vi.fn();
const submit = vi.fn();
const reassignContext = vi.fn();
const reassignSuggestions = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  screeningApi: {
    getForStage: (...a: unknown[]) => getForStage(...a),
    submit: (...a: unknown[]) => submit(...a),
    reassignContext: (...a: unknown[]) => reassignContext(...a),
    reassignSuggestions: (...a: unknown[]) => reassignSuggestions(...a),
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { Form } from "@/components/v2/forms";
import {
  DEFAULT_SKIP_NOTE,
  ScreeningFormFields,
  buildScreeningPayload,
  useScreeningForm,
} from "@/components/v2/screening/ScreeningForm";
import { ScreeningReassignSuggestions } from "@/components/v2/jobs/ScreeningReassignSuggestions";

const QUESTIONS = [
  { id: "q1", question: "Doświadczenie z Kafką?", ideal_answer: "", deal_breaker: "" },
  { id: "q2", question: "Od kiedy dostępny?", ideal_answer: "", deal_breaker: "" },
];

function Harness() {
  const screening = useScreeningForm({ stageId: 7 });
  if (!screening.data) return <p>Ładowanie</p>;
  return (
    <Form methods={screening.methods} onSubmit={screening.onSubmit}>
      <ScreeningReassignSuggestions
        stageId={7}
        questions={screening.questions}
        methods={screening.methods}
      />
      <ScreeningFormFields questions={screening.questions} methods={screening.methods} />
      <button type="submit">Zapisz screening</button>
    </Form>
  );
}

function renderHarness() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

const REASSIGNED = {
  data: {
    stage_id: 7,
    available: true,
    source: { job_id: 3, job_title: "Java Developer — Bank A", date: "2026-09-02" },
    previous_answers_count: 2,
  },
};

const SUGGESTION = {
  question_id: "q1",
  text: "Pięć lat z Kafką w bankowości.",
  source_kind: "answer" as const,
  source_quote: "Pięć lat z Kafką",
  confidence: "high" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  getForStage.mockResolvedValue({
    data: {
      stage_id: 7,
      candidate_id: 1,
      job_id: 2,
      champion_profile: { screening_questions: QUESTIONS },
      screening_answers: null,
    },
  });
  submit.mockResolvedValue({
    data: { stage_id: 7, match_percent: 60, screening_answers: {} },
  });
  reassignContext.mockResolvedValue(REASSIGNED);
  reassignSuggestions.mockResolvedValue({
    data: {
      stage_id: 7,
      available: true,
      message: null,
      source: REASSIGNED.data.source,
      suggestions: [SUGGESTION],
    },
  });
});

const answerField = (label: RegExp) => {
  const card = screen.getByText(label).closest("div.rounded-lg") as HTMLElement;
  return within(card).getByRole("textbox") as HTMLTextAreaElement;
};

describe("ScreeningReassignSuggestions", () => {
  it("bez przepięcia nie pokazuje banera ani „Pomiń brakujące”", async () => {
    reassignContext.mockResolvedValue({
      data: { stage_id: 7, available: false, source: null, previous_answers_count: 0 },
    });
    renderHarness();
    await screen.findByText("Doświadczenie z Kafką?");
    await waitFor(() => expect(reassignContext).toHaveBeenCalledWith(7));
    expect(screen.queryByText(/Luna przygotuje odpowiedzi/)).toBeNull();
    expect(screen.queryByLabelText("Pomiń brakujące — przepięcie")).toBeNull();
  });

  it("baner niczego nie płaci — model woła dopiero przycisk", async () => {
    renderHarness();
    expect(await screen.findByText(/Luna przygotuje odpowiedzi/)).toBeTruthy();
    expect(screen.getByText(/Przepięcie z: Java Developer — Bank A/)).toBeTruthy();
    expect(reassignSuggestions).not.toHaveBeenCalled();
  });

  it("„Przyjmij” wpisuje podpowiedź z origin reassign_suggested i zapisuje ją", async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(await screen.findByRole("button", { name: /Podpowiedz odpowiedzi/ }));
    expect(await screen.findByText(SUGGESTION.text)).toBeTruthy();
    expect(screen.getByText(/Z odpowiedzi w poprzednim screeningu/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Przyjmij" }));
    expect(answerField(/^Doświadczenie z Kafką\?$/).value).toBe(SUGGESTION.text);
    expect(screen.getByText("z podpowiedzi Luny")).toBeTruthy();
    // Karta podpowiedzi znika po decyzji.
    expect(screen.queryByRole("button", { name: "Przyjmij" })).toBeNull();

    await user.type(answerField(/^Od kiedy dostępny\?$/), "Od zaraz");
    await user.click(screen.getByRole("button", { name: "Zapisz screening" }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    const payload = submit.mock.calls[0][1];
    expect(payload.answers).toEqual([
      expect.objectContaining({
        question_id: "q1",
        response: SUGGESTION.text,
        origin: "reassign_suggested",
        skipped: false,
      }),
      expect.objectContaining({ question_id: "q2", origin: "manual", skipped: false }),
    ]);
    expect(payload.internal_note).toBeNull();
  });

  it("„Popraw” wpisuje i ustawia kursor w polu; „Odrzuć podpowiedź” nic nie wpisuje", async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(await screen.findByRole("button", { name: /Podpowiedz odpowiedzi/ }));
    await screen.findByText(SUGGESTION.text);
    await user.click(screen.getByRole("button", { name: "Odrzuć podpowiedź" }));
    expect(answerField(/^Doświadczenie z Kafką\?$/).value).toBe("");

    await user.click(screen.getByRole("button", { name: /Podpowiedz ponownie/ }));
    await user.click(await screen.findByRole("button", { name: "Popraw" }));
    const field = answerField(/^Doświadczenie z Kafką\?$/);
    expect(field.value).toBe(SUGGESTION.text);
    await waitFor(() => expect(document.activeElement).toBe(field));
  });

  it("niedostępna Luna to komunikat, nie blokada arkusza", async () => {
    const user = userEvent.setup();
    reassignSuggestions.mockResolvedValue({
      data: {
        stage_id: 7,
        available: false,
        message: "Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie.",
        source: REASSIGNED.data.source,
        suggestions: [],
      },
    });
    renderHarness();
    await user.click(await screen.findByRole("button", { name: /Podpowiedz odpowiedzi/ }));
    expect(
      await screen.findByText("Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zapisz screening" })).toBeEnabled();
  });

  it("bez „Pomiń brakujące” pusta odpowiedź blokuje zapis", async () => {
    const user = userEvent.setup();
    renderHarness();
    await screen.findByText(/Luna przygotuje odpowiedzi/);
    await user.type(answerField(/^Doświadczenie z Kafką\?$/), "5 lat");
    await user.click(screen.getByRole("button", { name: "Zapisz screening" }));
    expect(await screen.findByText("Odpowiedź jest wymagana")).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
  });

  it("„Pomiń brakujące — przepięcie” zapisuje puste jako pominięte z notatką wewnętrzną", async () => {
    const user = userEvent.setup();
    renderHarness();
    await screen.findByText(/Luna przygotuje odpowiedzi/);
    await user.type(answerField(/^Doświadczenie z Kafką\?$/), "5 lat");
    await user.click(screen.getByLabelText("Pomiń brakujące — przepięcie"));
    expect(screen.getByText(/1 pytanie bez odpowiedzi zapisze się jako pominięte/)).toBeTruthy();
    expect(screen.getByText("pominięte — przepięcie")).toBeTruthy();
    await user.type(
      screen.getByPlaceholderText(/te same pytania co w poprzedniej rekrutacji/),
      "Klient zna kandydata",
    );
    await user.click(screen.getByRole("button", { name: "Zapisz screening" }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    const payload = submit.mock.calls[0][1];
    expect(payload.answers[0]).toMatchObject({ question_id: "q1", skipped: false });
    expect(payload.answers[1]).toMatchObject({ question_id: "q2", response: "", skipped: true });
    expect(payload.internal_note).toBe("Klient zna kandydata");
  });
});

describe("buildScreeningPayload", () => {
  const values = {
    answers: {
      q1: { response: "tak", deal_breaker_hit: false },
      q2: { response: "  ", deal_breaker_hit: false },
    },
    overall_fit: "fit" as const,
    notes: "",
  };

  it("bez pominięcia nic nie jest skipped i nie ma notatki wewnętrznej", () => {
    const payload = buildScreeningPayload(QUESTIONS, values);
    expect(payload.answers.map((a) => a.skipped)).toEqual([false, false]);
    expect(payload.internal_note).toBeNull();
  });

  it("pominięcie bez własnej notatki dostaje notatkę domyślną", () => {
    const payload = buildScreeningPayload(QUESTIONS, {
      ...values,
      skip_missing: true,
      internal_note: "",
    });
    expect(payload.answers.map((a) => a.skipped)).toEqual([false, true]);
    expect(payload.internal_note).toBe(DEFAULT_SKIP_NOTE);
  });
});
