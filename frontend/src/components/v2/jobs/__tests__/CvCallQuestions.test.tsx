/**
 * „Dopytaj pod CV”: pytania z firmą i wymaganiem, jedno odświeżenie, awaria z
 * „Ponów” zamiast pustej listy, sekcja znika poza „Nowymi” i „Screeningiem”.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvCallQuestions } from "@/components/v2/jobs/CvCallQuestions";
import {
  shouldAutoRefreshCvCallQuestions,
  type CvCallQuestionsView,
} from "@/lib/api/cvCallQuestions";

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
  },
}));

function view(patch: Partial<CvCallQuestionsView> = {}): CvCallQuestionsView {
  return {
    status: "ready",
    can_refresh: true,
    stale: false,
    questions: [
      {
        requirement: "Kafka",
        company: "Firma Alfa",
        state: "tylko_lista",
        question: "Jak wyglądała Twoja praca z Kafką w Firmie Alfa?",
      },
      {
        requirement: "Liquibase",
        company: "",
        state: "brak",
        question: "W której pracy był u Ciebie Liquibase i do czego?",
      },
    ],
    generated_at: "2026-11-05T10:00:00Z",
    ...patch,
  };
}

function show(framed = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CvCallQuestions candidateId={7} jobId={12} framed={framed} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

describe("CvCallQuestions", () => {
  it("pokazuje pytania, wymaganie z firmą i mówi, gdzie wpisać odpowiedź", async () => {
    apiGet.mockResolvedValue({ data: view() });
    show();
    expect(await screen.findByText("Dopytaj pod CV · 2 opcjonalne")).toBeInTheDocument();
    expect(screen.getByText(/Jak wyglądała Twoja praca z Kafką/)).toBeInTheDocument();
    expect(screen.getByText("Kafka · Firma Alfa")).toBeInTheDocument();
    expect(screen.getByText("Liquibase")).toBeInTheDocument();
    expect(screen.getByText(/podaj nazwę firmy/)).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("bez pytań prosi o nie raz i pokazuje wynik", async () => {
    apiGet.mockResolvedValue({ data: view({ status: "none", questions: [] }) });
    apiPost.mockResolvedValue({ data: view() });
    show();
    expect(await screen.findByText("Dopytaj pod CV · 2 opcjonalne")).toBeInTheDocument();
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost.mock.calls[0][0]).toBe("/api/candidates/7/jobs/12/call-questions/refresh");
  });

  it.each(["not_applicable", "no_requirements", "no_cv"] as const)(
    "w stanie %s sekcji nie ma i model nie rusza",
    async (status) => {
      apiGet.mockResolvedValue({
        data: view({ status, questions: [], can_refresh: false }),
      });
      const { container } = show();
      await waitFor(() => expect(apiGet).toHaveBeenCalled());
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(container).toBeEmptyDOMElement();
      expect(apiPost).not.toHaveBeenCalled();
    },
  );

  it("awaria odczytu nie wygląda jak brak pytań i ma „Ponów”", async () => {
    apiGet.mockRejectedValueOnce(new Error("bez sieci"));
    apiGet.mockResolvedValueOnce({ data: view() });
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać pytań/);
    await userEvent.click(screen.getByRole("button", { name: /Ponów/ }));
    expect(await screen.findByText("Dopytaj pod CV · 2 opcjonalne")).toBeInTheDocument();
  });

  it("awaria modelu daje „Ponów” bez samoczynnego powtarzania", async () => {
    apiGet.mockResolvedValue({ data: view({ status: "failed", questions: [] }) });
    apiPost.mockResolvedValue({ data: view() });
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się przygotować/);
    expect(apiPost).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Ponów/ }));
    expect(await screen.findByText("Dopytaj pod CV · 2 opcjonalne")).toBeInTheDocument();
    expect(apiPost).toHaveBeenCalledTimes(1);
  });

  it("w podglądzie jako inna osoba nie prosi o model i nie daje „Ponów”", async () => {
    apiGet.mockResolvedValue({
      data: view({ status: "failed", questions: [], can_refresh: false, stale: true }),
    });
    show();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ponów/ })).not.toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("gotowa pusta lista mówi, że nie ma o co dopytać", async () => {
    apiGet.mockResolvedValue({ data: view({ questions: [] }) });
    show();
    expect(await screen.findByText(/Nie ma o co dopytać pod CV/)).toBeInTheDocument();
  });

  it("sama sekcja dostaje ramkę ściągi", async () => {
    apiGet.mockResolvedValue({ data: view() });
    show(true);
    expect(await screen.findByText("Ściąga do rozmowy")).toBeInTheDocument();
    expect(screen.getByText("Dopytaj pod CV · 2 opcjonalne")).toBeInTheDocument();
  });
});

describe("shouldAutoRefreshCvCallQuestions", () => {
  it("prosi tylko, gdy brak pytań albo zmieniły się źródła", () => {
    expect(shouldAutoRefreshCvCallQuestions(view({ status: "none" }))).toBe(true);
    expect(shouldAutoRefreshCvCallQuestions(view({ stale: true }))).toBe(true);
    expect(shouldAutoRefreshCvCallQuestions(view({ status: "failed", stale: true }))).toBe(true);
    expect(shouldAutoRefreshCvCallQuestions(view())).toBe(false);
    expect(shouldAutoRefreshCvCallQuestions(view({ status: "failed" }))).toBe(false);
    expect(shouldAutoRefreshCvCallQuestions(view({ status: "none", can_refresh: false }))).toBe(false);
    expect(shouldAutoRefreshCvCallQuestions(undefined)).toBe(false);
  });
});
