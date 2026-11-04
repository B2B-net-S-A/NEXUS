import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { FormProvider, useForm } from "react-hook-form";

import type { ScreeningQuestion } from "@/lib/api";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }),
}));

import type { PhraseController } from "../PhraseSuggestion";
import { ScreeningFormFields, type ScreeningFormValues } from "../ScreeningForm";

const QUESTIONS = [{ id: "q1", question: "Jakie ma doświadczenie z Kafką?" }] as ScreeningQuestion[];

function controller(overrides: Partial<PhraseController> = {}): PhraseController {
  return {
    language: "pl",
    setLanguage: vi.fn(),
    results: {},
    isPending: () => false,
    request: vi.fn(async () => undefined),
    dismiss: vi.fn(),
    ...overrides,
  };
}

let captured: ScreeningFormValues | null = null;

function Harness({ phrase }: { phrase?: PhraseController }) {
  const methods = useForm<ScreeningFormValues>({
    defaultValues: {
      answers: { q1: { response: "kafka 3 lata prod", deal_breaker_hit: false, origin: "manual" } },
      overall_fit: "uncertain",
      notes: "",
    },
  });
  captured = methods.getValues();
  return (
    <FormProvider {...methods}>
      <ScreeningFormFields questions={QUESTIONS} methods={methods} phrase={phrase} />
      <button type="button" onClick={() => (captured = methods.getValues())}>
        odczytaj
      </button>
    </FormProvider>
  );
}

describe("„Ułóż w zdanie” w arkuszu screeningu", () => {
  it("bez kontrolera nie ma przycisku", () => {
    render(<Harness />);
    expect(screen.queryByRole("button", { name: "Ułóż w zdanie" })).toBeNull();
  });

  it("przycisk wysyła hasła i pytanie", () => {
    const phrase = controller();
    render(<Harness phrase={phrase} />);
    fireEvent.click(screen.getByRole("button", { name: "Ułóż w zdanie" }));
    expect(phrase.request).toHaveBeenCalledWith([
      { key: "q1", keywords: "kafka 3 lata prod", question: "Jakie ma doświadczenie z Kafką?" },
    ]);
  });

  it("„Użyj zdania” wstawia zdanie i zapamiętuje hasła", () => {
    const phrase = controller({
      results: {
        q1: {
          key: "q1",
          sentence: "Kandydat od 3 lat pracuje z Kafką na produkcji.",
          problem: null,
          keywords: "kafka 3 lata prod",
        },
      },
    });
    render(<Harness phrase={phrase} />);
    fireEvent.click(screen.getByRole("button", { name: "Użyj zdania" }));
    fireEvent.click(screen.getByRole("button", { name: "odczytaj" }));
    expect(captured?.answers.q1).toMatchObject({
      response: "Kandydat od 3 lat pracuje z Kafką na produkcji.",
      origin: "phrased",
      keywords: "kafka 3 lata prod",
    });
    expect(phrase.dismiss).toHaveBeenCalledWith("q1");
  });

  it("odrzucone zdanie mówi, co dopisała Luna", () => {
    const phrase = controller({
      results: { q1: { key: "q1", sentence: null, problem: "5", keywords: "kafka 3 lata" } },
    });
    render(<Harness phrase={phrase} />);
    expect(screen.getByText(/czego nie ma w hasłach: „5”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Użyj zdania" })).toBeNull();
  });
});
