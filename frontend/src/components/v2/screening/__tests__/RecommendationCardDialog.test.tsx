import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { RecommendationCard } from "@/lib/api/recommendationCards";

const showSuccess = vi.fn();
const showError = vi.fn();
const mutate = vi.fn();
const applyMutate = vi.fn();
const readNote = vi.fn();
let cardData: RecommendationCard;

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
  useRecommendationCard: () => ({ data: cardData, isLoading: false, isError: false }),
  useSaveRecommendationCard: () => ({ mutate, isPending: false }),
  useApplyNote: () => ({ mutate: applyMutate, isPending: false }),
  recommendationCardsApi: {
    readNote: (...args: unknown[]) => readNote(...args),
    readNoteFile: vi.fn(),
    phrase: vi.fn(),
  },
}));

import { RecommendationCardDialog } from "../RecommendationCardDialog";

function mount(onOpenChange = vi.fn(), props: { screeningDirty?: boolean } = {}) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RecommendationCardDialog
        open
        onOpenChange={onOpenChange}
        candidateId={1}
        jobId={2}
        candidateName="Tomasz Wzorcowy"
        {...props}
      />
    </QueryClientProvider>,
  );
}

function renderDialog(onOpenChange = vi.fn()) {
  mount(onOpenChange);
  fireEvent.change(screen.getByLabelText("Stawka"), { target: { value: "130" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz kartę" }));
  return onOpenChange;
}

describe("RecommendationCardDialog — zapis", () => {
  beforeEach(() => {
    showSuccess.mockReset();
    showError.mockReset();
    mutate.mockReset();
    cardData = CARD;
  });

  it("po zapisie potwierdza i zamyka okno", () => {
    mutate.mockImplementation((_fields, opts) => opts.onSuccess());
    const onOpenChange = renderDialog();

    expect(mutate).toHaveBeenCalledWith(
      { fields: { rate: "130" }, origins: {} },
      expect.anything(),
    );
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

const PROPOSAL = {
  fields: [
    {
      key: "english",
      label: "Angielski",
      current: null,
      current_source: null,
      proposed: "B2",
      quote: "eng B2 gada swobodnie",
      origin: "note_ai",
      changed: true,
    },
  ],
  answers: [
    {
      question_id: "q1",
      number: 1,
      question: "Jakie ma doświadczenie z Kafką?",
      current: null,
      keywords: "kafka 3 lata prod",
      sentence: "Kandydat od 3 lat pracuje z Kafką na produkcji.",
      problem: null,
    },
  ],
  available: true,
  message: null,
  language: "pl",
  rate_change_notifies: false,
  text: "eng B2 gada swobodnie\nkafka 3 lata prod",
};

describe("RecommendationCardDialog — karta z notatki", () => {
  beforeEach(() => {
    applyMutate.mockReset();
    readNote.mockReset();
    showSuccess.mockReset();
    cardData = { ...CARD, assist_enabled: true, phrase_language: "pl" };
  });

  it("bez włączonej funkcji nie pokazuje kafli źródła", () => {
    cardData = CARD;
    mount();
    expect(screen.queryByRole("radio", { name: /Wklej tekst/ })).toBeNull();
  });

  it("wklejona notatka → przegląd → zapis zaznaczonych pozycji", async () => {
    readNote.mockResolvedValue(PROPOSAL);
    applyMutate.mockImplementation((_input, opts) => opts.onSuccess());
    mount();

    fireEvent.click(screen.getByRole("radio", { name: /Wklej tekst/ }));
    fireEvent.change(screen.getByLabelText("Notatka z rozmowy"), {
      target: { value: "eng B2 gada swobodnie\nkafka 3 lata prod, eventy płatności" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odczytaj notatkę" }));

    const apply = await screen.findByRole("button", { name: "Zastosuj zaznaczone (2)" });
    expect(readNote).toHaveBeenCalledWith(1, 2, expect.stringContaining("kafka"));
    expect(screen.getByText("„eng B2 gada swobodnie”")).toBeInTheDocument();
    fireEvent.click(apply);

    expect(applyMutate).toHaveBeenCalledWith(
      {
        text: PROPOSAL.text,
        source_name: null,
        fields: { english: "B2" },
        field_origins: { english: "note_ai" },
        answers: [
          {
            question_id: "q1",
            response: "Kandydat od 3 lat pracuje z Kafką na produkcji.",
            keywords: "kafka 3 lata prod",
            origin: "phrased",
          },
        ],
      },
      expect.anything(),
    );
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith("Karta uzupełniona z notatki."),
    );
  });

  it("odczyt zakończony po zamknięciu okna nie otwiera przeglądu", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    readNote.mockReturnValue(new Promise((r) => (resolve = r)));
    const client = new QueryClient();
    const view = (open: boolean) => (
      <QueryClientProvider client={client}>
        <RecommendationCardDialog
          open={open}
          onOpenChange={vi.fn()}
          candidateId={1}
          jobId={2}
          candidateName="Tomasz Wzorcowy"
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view(true));
    fireEvent.click(screen.getByRole("radio", { name: /Wklej tekst/ }));
    fireEvent.change(screen.getByLabelText("Notatka z rozmowy"), {
      target: { value: "x".repeat(40) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odczytaj notatkę" }));
    rerender(view(false));
    resolve(PROPOSAL);
    await waitFor(() => expect(readNote).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    rerender(view(true));
    expect(screen.queryByRole("button", { name: /Zastosuj zaznaczone/ })).toBeNull();
  });

  it("niezapisany arkusz screeningu blokuje odczyt notatki", () => {
    mount(vi.fn(), { screeningDirty: true });
    fireEvent.click(screen.getByRole("radio", { name: /Wklej tekst/ }));
    fireEvent.change(screen.getByLabelText("Notatka z rozmowy"), {
      target: { value: "x".repeat(40) },
    });
    expect(screen.getByRole("button", { name: "Odczytaj notatkę" })).toBeDisabled();
    expect(screen.getByText(/niezapisane odpowiedzi w arkuszu/)).toBeInTheDocument();
  });
});
