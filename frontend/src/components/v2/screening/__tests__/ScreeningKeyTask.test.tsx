import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { FormProvider, useForm } from "react-hook-form";

import type { ScreeningQuestion } from "@/lib/api";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }),
}));

import { ScreeningFormFields, type ScreeningFormValues } from "../ScreeningForm";

const QUESTIONS = [
  { id: "q1", question: "Jak wyglądała migracja, którą prowadził?", key_task: true },
  { id: "q2", question: "Jakie ma doświadczenie z Kafką?" },
] as ScreeningQuestion[];

function Harness() {
  const methods = useForm<ScreeningFormValues>({
    defaultValues: { answers: {}, overall_fit: "uncertain", notes: "" },
  });
  return (
    <FormProvider {...methods}>
      <ScreeningFormFields questions={QUESTIONS} methods={methods} />
    </FormProvider>
  );
}

describe("Arkusz screeningu: pytanie o najważniejsze zadanie (23.11.2026)", () => {
  it("oznacza tylko pytanie, które sprawdza zadanie, i mówi, że odpowiedź trafia do CV", () => {
    render(<Harness />);
    expect(screen.getByTestId("screening-q-q1-key-task")).toHaveTextContent("trafia do CV");
    expect(screen.queryByTestId("screening-q-q2-key-task")).toBeNull();
  });
});
