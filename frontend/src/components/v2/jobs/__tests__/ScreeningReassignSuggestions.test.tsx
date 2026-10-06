/**
 * Wcześniejsze odpowiedzi kandydata w arkuszu screeningu (02.10.2026;
 * przepięcie — Pipeline v4, 23.09.2026).
 *
 * Arkusz jest prawdziwy (`useScreeningForm` + `ScreeningFormFields`), sieć
 * zamockowana na granicy `screeningApi`. Sprawdzamy: Luna rusza sama i tylko
 * raz, podpowiedź stoi pod pytaniem ze źródłem rozmowy, „Użyj tej odpowiedzi”
 * / „Pomiń”, awarię Luny jako komunikat oraz „Pomiń brakujące — przepięcie”
 * (tylko przy przepięciu) aż do payloadu zapisu.
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
  makeSchema,
  useScreeningForm,
} from "@/components/v2/screening/ScreeningForm";
import {
  ScreeningReassignSuggestions,
  answerAgeNote,
  earlierConversationsLabel,
} from "@/components/v2/jobs/ScreeningReassignSuggestions";

const QUESTIONS = [
  { id: "q1", question: "Czy pracowałeś na mikroserwisach?", ideal_answer: "", deal_breaker: "" },
  { id: "q2", question: "Od kiedy dostępny?", ideal_answer: "", deal_breaker: "" },
];

function Harness({ readOnly = false }: { readOnly?: boolean }) {
  const screening = useScreeningForm({ stageId: 7 });
  if (!screening.data) return <p>Ładowanie</p>;
  return (
    <Form methods={screening.methods} onSubmit={screening.onSubmit}>
      <ScreeningReassignSuggestions
        stageId={7}
        questions={screening.questions}
        methods={screening.methods}
        saved={screening.existing}
        readOnly={readOnly}
      >
        {(renderQuestionExtra) => (
          <ScreeningFormFields
            questions={screening.questions}
            methods={screening.methods}
            renderQuestionExtra={renderQuestionExtra}
          />
        )}
      </ScreeningReassignSuggestions>
      <button type="submit">Zapisz screening</button>
    </Form>
  );
}

function renderHarness(props: { readOnly?: boolean } = {}, client?: QueryClient) {
  const queryClient =
    client ?? new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
  return { ...view, queryClient };
}

const HISTORY = {
  data: {
    stage_id: 7,
    candidate_id: 1,
    available: true,
    kind: "history",
    source: null,
    previous_answers_count: 3,
    earlier_conversations: 2,
  },
};

const REASSIGNED = {
  data: {
    stage_id: 7,
    candidate_id: 1,
    available: true,
    kind: "reassign",
    source: { job_id: 3, job_title: "Java Developer — Bank A", date: "2026-09-02" },
    previous_answers_count: 2,
    earlier_conversations: 1,
  },
};

const HINT = {
  question_id: "q1",
  text: "Tak, 3 lata: 12 usług, Kafka i Spring Boot.",
  source_kind: "answer" as const,
  source_quote: "12 usług, Kafka",
  confidence: "high" as const,
  source: { job_id: 3, job_title: "Java Developer", client_name: "Telekom Przykładowy", date: "2026-08-14" },
  source_question: "Mikroserwisy?",
};

const suggestions = (list: unknown[], over: Record<string, unknown> = {}) => ({
  data: { stage_id: 7, available: true, message: null, kind: "history", source: null, suggestions: list, ...over },
});

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
  reassignContext.mockResolvedValue(HISTORY);
  reassignSuggestions.mockResolvedValue(suggestions([HINT]));
});

const questionCard = (label: RegExp) => screen.getByText(label).closest("div.rounded-lg") as HTMLElement;
const answerField = (label: RegExp) => within(questionCard(label)).getByRole("textbox") as HTMLTextAreaElement;
const Q1 = /^Czy pracowałeś na mikroserwisach\?$/;
const Q2 = /^Od kiedy dostępny\?$/;

describe("wcześniejsze odpowiedzi w arkuszu screeningu", () => {
  it("osoba bez wcześniejszych rozmów: arkusz bez banera i bez wywołania Luny", async () => {
    reassignContext.mockResolvedValue({
      data: {
        stage_id: 7,
        candidate_id: 1,
        available: false,
        kind: null,
        source: null,
        previous_answers_count: 0,
        earlier_conversations: 0,
      },
    });
    renderHarness();
    await screen.findByText(Q1);
    await waitFor(() => expect(reassignContext).toHaveBeenCalledWith(7));
    expect(screen.queryByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" })).toBeNull();
    expect(screen.queryByLabelText("Pomiń brakujące — przepięcie")).toBeNull();
    expect(reassignSuggestions).not.toHaveBeenCalled();
  });

  it("Luna rusza sama po otwarciu arkusza, a wcześniejsza odpowiedź stoi pod pytaniem ze źródłem", async () => {
    renderHarness();
    const banner = await screen.findByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" });
    expect(banner).toHaveTextContent("Ta osoba ma 2 wcześniejsze rozmowy screeningowe");
    await waitFor(() => expect(reassignSuggestions).toHaveBeenCalledTimes(1));
    const hint = await within(questionCard(Q1)).findByTestId("earlier-answer-hint");
    expect(hint).toHaveTextContent("Z rozmowy 14.08.2026 · Java Developer, Telekom Przykładowy");
    expect(hint).toHaveTextContent("Pytanie wtedy: Mikroserwisy?");
    expect(hint).toHaveTextContent("„Tak, 3 lata: 12 usług, Kafka i Spring Boot.”");
    expect(banner).toHaveTextContent("Pod 1 pytaniem widzisz, co ta osoba już mówiła");
    expect(within(banner).getByRole("link", { name: "Wszystkie odpowiedzi w profilu" })).toHaveAttribute(
      "href",
      "/candidates/1",
    );
    // Pytanie bez wcześniejszej odpowiedzi mówi to wprost.
    expect(questionCard(Q2)).toHaveTextContent("We wcześniejszych rozmowach nie ma odpowiedzi na to pytanie.");
    // Bez przepięcia nie ma „Pomiń brakujące”.
    expect(screen.queryByLabelText("Pomiń brakujące — przepięcie")).toBeNull();
  });

  it("„Użyj tej odpowiedzi” wpisuje ją w pole i zapisuje jako przeniesioną z podpowiedzi", async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(await screen.findByRole("button", { name: "Użyj tej odpowiedzi" }));
    const field = answerField(Q1);
    expect(field.value).toBe(HINT.text);
    await waitFor(() => expect(document.activeElement).toBe(field));
    expect(screen.getByText("z podpowiedzi Luny")).toBeTruthy();
    expect(screen.queryByTestId("earlier-answer-hint")).toBeNull();
    // Baner nie obiecuje już podpowiedzi, której pod pytaniem nie ma.
    expect(screen.getByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" })).not.toHaveTextContent(
      /Pod \d+ pytani/,
    );

    await user.type(answerField(Q2), "Od zaraz");
    await user.click(screen.getByRole("button", { name: "Zapisz screening" }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    const payload = submit.mock.calls[0][1];
    expect(payload.answers).toEqual([
      expect.objectContaining({ question_id: "q1", response: HINT.text, origin: "reassign_suggested", skipped: false }),
      expect.objectContaining({ question_id: "q2", origin: "manual", skipped: false }),
    ]);
    expect(payload.internal_note).toBeNull();
  });

  it("podpowiedź poprawiona ręcznie jest już odpowiedzią z tej rozmowy", async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(await screen.findByRole("button", { name: "Użyj tej odpowiedzi" }));
    await user.type(answerField(Q1), " Od roku także Kubernetes.");
    expect(screen.queryByText("z podpowiedzi Luny")).toBeNull();
    await user.type(answerField(Q2), "Od zaraz");
    await user.click(screen.getByRole("button", { name: "Zapisz screening" }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0][1].answers[0]).toMatchObject({
      response: `${HINT.text} Od roku także Kubernetes.`,
      origin: "manual",
    });
  });

  it("„Pomiń” chowa podpowiedź i nic nie wpisuje; własna odpowiedź też ją chowa", async () => {
    const user = userEvent.setup();
    reassignSuggestions.mockResolvedValue(
      suggestions([HINT, { ...HINT, question_id: "q2", text: "Od 1 października." }]),
    );
    renderHarness();
    await waitFor(() => expect(screen.getAllByTestId("earlier-answer-hint")).toHaveLength(2));
    await user.click(within(questionCard(Q1)).getByRole("button", { name: "Pomiń" }));
    expect(answerField(Q1).value).toBe("");
    expect(within(questionCard(Q1)).queryByTestId("earlier-answer-hint")).toBeNull();
    await user.type(answerField(Q2), "Od listopada");
    expect(screen.queryByTestId("earlier-answer-hint")).toBeNull();
  });

  it("odpowiedź sprzed ponad 30 dni dostaje „dopytaj”", async () => {
    const old = new Date(Date.now() - 49 * 86_400_000).toISOString().slice(0, 10);
    reassignSuggestions.mockResolvedValue(suggestions([{ ...HINT, source: { ...HINT.source, date: old } }]));
    renderHarness();
    expect(await screen.findByTestId("earlier-answer-hint")).toHaveTextContent(
      "to 7 tygodni temu — dopytaj, czy nadal aktualne",
    );
  });

  it("ponowne otwarcie arkusza nie płaci za Lunę drugi raz", async () => {
    const first = renderHarness();
    await screen.findByTestId("earlier-answer-hint");
    first.unmount();
    renderHarness({}, first.queryClient);
    await screen.findByTestId("earlier-answer-hint");
    expect(reassignSuggestions).toHaveBeenCalledTimes(1);
  });

  it("bez prawa zapisu Luna nie jest wołana — odpowiedzi są w profilu", async () => {
    renderHarness({ readOnly: true });
    const banner = await screen.findByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" });
    expect(banner).toHaveTextContent("Wcześniejsze odpowiedzi zobaczysz w profilu kandydata.");
    expect(reassignSuggestions).not.toHaveBeenCalled();
    expect(screen.queryByTestId("earlier-answer-hint")).toBeNull();
  });

  it("zapisany arkusz z kompletem odpowiedzi — nie ma czego podpowiadać", async () => {
    getForStage.mockResolvedValue({
      data: {
        stage_id: 7,
        candidate_id: 1,
        job_id: 2,
        champion_profile: { screening_questions: QUESTIONS },
        screening_answers: {
          answers: [
            { question_id: "q1", response: "Tak", deal_breaker_hit: false },
            { question_id: "q2", response: "Od zaraz", deal_breaker_hit: false },
          ],
          overall_fit: "fit",
          notes: "",
        },
      },
    });
    renderHarness();
    const banner = await screen.findByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" });
    expect(banner).toHaveTextContent("Arkusz ma już odpowiedź na każde pytanie.");
    expect(reassignSuggestions).not.toHaveBeenCalled();
  });

  it("niedostępna Luna to komunikat z „Spróbuj ponownie”, nie blokada arkusza", async () => {
    const user = userEvent.setup();
    reassignSuggestions.mockResolvedValueOnce(
      suggestions([], { available: false, message: "Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie." }),
    );
    renderHarness();
    const banner = await screen.findByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" });
    expect(await within(banner).findByText(/Luna nie odpowiedziała — uzupełnij odpowiedzi ręcznie\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zapisz screening" })).toBeEnabled();
    await user.click(within(banner).getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByTestId("earlier-answer-hint")).toBeTruthy();
    expect(reassignSuggestions).toHaveBeenCalledTimes(2);
  });

  it("awaria sprawdzenia wcześniejszych rozmów nie zabiera arkusza", async () => {
    reassignContext.mockRejectedValue(new Error("sieć"));
    renderHarness();
    expect(await screen.findByText(/Nie udało się sprawdzić wcześniejszych rozmów tej osoby/)).toBeTruthy();
    expect(screen.getByText(Q1)).toBeTruthy();
    expect(reassignSuggestions).not.toHaveBeenCalled();
  });
});

describe("przepięcie", () => {
  beforeEach(() => {
    reassignContext.mockResolvedValue(REASSIGNED);
    reassignSuggestions.mockResolvedValue(
      suggestions(
        [
          {
            ...HINT,
            question_id: "q2",
            text: "Od października.",
            source_kind: "note",
            source_quote: "Dostępny od października",
            source: null,
            source_question: null,
          },
        ],
        { kind: "reassign", source: REASSIGNED.data.source },
      ),
    );
  });

  it("baner mówi, skąd osoba przyszła, a podpowiedź z notatki pokazuje jej fragment", async () => {
    renderHarness();
    const banner = await screen.findByRole("region", { name: "Wcześniejsze odpowiedzi kandydata" });
    expect(banner).toHaveTextContent("Przepięcie z: Java Developer — Bank A · 2.09.2026");
    const hint = await within(questionCard(Q2)).findByTestId("earlier-answer-hint");
    expect(hint).toHaveTextContent("Z notatki rekrutera");
    expect(hint).toHaveTextContent("Fragment notatki: „Dostępny od października”");
    // Zdanie Luny z notatki nie udaje cytatu kandydata.
    expect(within(hint).getByText("Od października.")).toBeTruthy();
  });

  it("bez „Pomiń brakujące” pusta odpowiedź blokuje zapis", async () => {
    const user = userEvent.setup();
    renderHarness();
    await screen.findByLabelText("Pomiń brakujące — przepięcie");
    await user.type(answerField(Q1), "5 lat");
    await user.click(screen.getByRole("button", { name: "Zapisz screening" }));
    expect(await screen.findByText("Odpowiedź jest wymagana")).toBeTruthy();
    expect(submit).not.toHaveBeenCalled();
  });

  it("„Pomiń brakujące — przepięcie” zapisuje puste jako pominięte z notatką wewnętrzną", async () => {
    const user = userEvent.setup();
    renderHarness();
    await screen.findByLabelText("Pomiń brakujące — przepięcie");
    await user.type(answerField(Q1), "5 lat");
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

  it("serwer sprzed zmiany (bez `kind`) dalej pokazuje przepięcie", async () => {
    reassignContext.mockResolvedValue({
      data: { stage_id: 7, available: true, source: REASSIGNED.data.source, previous_answers_count: 2 },
    });
    renderHarness();
    expect(await screen.findByLabelText("Pomiń brakujące — przepięcie")).toBeTruthy();
  });
});

describe("opisy wcześniejszych rozmów", () => {
  const now = new Date("2026-10-02T12:00:00Z");

  it("wiek odpowiedzi: do 30 dni bez dopisku, potem tygodnie, potem miesiące", () => {
    expect(answerAgeNote("2026-09-20", now)).toBeNull();
    expect(answerAgeNote("2026-09-02", now)).toBeNull();
    expect(answerAgeNote("2026-08-14", now)).toBe("to 7 tygodni temu — dopytaj, czy nadal aktualne");
    expect(answerAgeNote("2026-03-01", now)).toBe("to 7 miesięcy temu — dopytaj, czy nadal aktualne");
    expect(answerAgeNote(null, now)).toBeNull();
    expect(answerAgeNote("nie data", now)).toBeNull();
  });

  it("liczba wcześniejszych rozmów po polsku", () => {
    expect([1, 2, 5].map(earlierConversationsLabel)).toEqual([
      "1 wcześniejszą rozmowę screeningową",
      "2 wcześniejsze rozmowy screeningowe",
      "5 wcześniejszych rozmów screeningowych",
    ]);
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

  it("odpowiedź przepisana z notatki (`note_sync`) przechodzi walidację i zapis", () => {
    const fromNote = {
      ...values,
      answers: {
        q1: { response: "tak", deal_breaker_hit: false, origin: "note_sync" as const },
        q2: { response: "miesiąc", deal_breaker_hit: false, origin: "note_sync" as const },
      },
    };
    expect(makeSchema(QUESTIONS).safeParse(fromNote).success).toBe(true);
    const payload = buildScreeningPayload(QUESTIONS, fromNote);
    // Serwer zamienia `note_sync` na `note_import` przy zapisie człowieka.
    expect(payload.answers.map((a) => a.origin)).toEqual(["note_sync", "note_sync"]);
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
