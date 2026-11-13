/** Karta firmy: „Uzupełnij dane” (G-A, zapis od razu od 13.11.2026), historia karty i „Zapytaj bota” (G-B). Dane fikcyjne. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BotHistory, BotQuestion, EnrichState } from "@/lib/api/sales-bot";

type QueryState<T> = {
  data?: T;
  isLoading: boolean;
  isError: boolean;
  isSuccess: boolean;
  refetch: () => void;
};

const refetch = vi.fn();
const start = vi.fn();
const ask = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };

let enrichQuery: QueryState<EnrichState>;
let questionsQuery: QueryState<{ enabled: boolean; items: BotQuestion[] }>;
let historyQuery: QueryState<BotHistory>;

function ok<T>(data: T): QueryState<T> {
  return { data, isLoading: false, isError: false, isSuccess: true, refetch };
}
const loading = { isLoading: true, isError: false, isSuccess: false, refetch };
const failed = { isLoading: false, isError: true, isSuccess: false, refetch };

vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/lib/api/sales-bot", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-bot")>()),
  useCompanyEnrich: () => enrichQuery,
  useStartEnrich: () => ({ mutate: start, isPending: false }),
  useCompanyBotHistory: () => historyQuery,
  useCompanyQuestions: () => questionsQuery,
  useAskBot: () => ({ mutate: ask, isPending: false }),
}));

import { AskBotCard } from "../bot/AskBotCard";
import { BotCardHistory } from "../bot/BotCardHistory";
import { EnrichButton, EnrichCard } from "../bot/EnrichCard";

const RUNNING: EnrichState = {
  enabled: true,
  run: { id: 4, status: "started", started_at: "2026-11-12T08:00:00Z" },
  result: null,
};

function withClient(node: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>;
}

function question(over: Partial<BotQuestion> = {}): BotQuestion {
  return {
    run_id: 1,
    status: "received",
    question: "Czy mają centrum IT w Polsce?",
    asked_by: { id: 5, name: "Ewa Testowa" },
    asked_at: "2026-11-12T08:00:00Z",
    answered_at: "2026-11-12T08:04:00Z",
    minutes: 4,
    answer: [
      { text: "Centrum w Krakowie od 2024", url: "https://news.example/a", published: "2026-10-01" },
      { text: "Wniosek: rosną", url: null },
    ],
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  enrichQuery = ok<EnrichState>({ enabled: true, run: null, result: null });
  historyQuery = ok<BotHistory>({ enabled: true, items: [] });
  questionsQuery = ok({ enabled: true, items: [question()] });
});

describe("EnrichCard", () => {
  it("pokazuje tylko trwające szukanie, bez „Przyjmij”", () => {
    enrichQuery = ok(RUNNING);
    const { container, rerender } = render(withClient(<EnrichCard companyId={7} />));
    expect(screen.getByRole("status")).toHaveTextContent("Szukam danych firmy");
    expect(screen.queryByRole("button", { name: /Przyjmij/ })).not.toBeInTheDocument();
    enrichQuery = ok<EnrichState>({ ...RUNNING, run: { ...RUNNING.run!, status: "received" } });
    rerender(withClient(<EnrichCard companyId={7} />));
    expect(container).toBeEmptyDOMElement();
  });

  it("z wyłączoną flagą i przy błędzie nic nie pokazuje", () => {
    enrichQuery = ok<EnrichState>({ enabled: false, run: null, result: null });
    const { container, rerender } = render(withClient(<EnrichCard companyId={7} />));
    expect(container).toBeEmptyDOMElement();
    enrichQuery = failed;
    rerender(withClient(<EnrichCard companyId={7} />));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("BotCardHistory", () => {
  it("pokazuje, co wpisał automat, co zostało ręczne i link do innej karty", () => {
    historyQuery = ok<BotHistory>({
      enabled: true,
      items: [
        {
          at: "2026-11-13T01:14:00Z",
          bot: "Dane firm",
          lines: [
            { label: "NIP", before: null, after: "1234563218", source: "https://rejestr.example/a", note: null, other_company: null },
            { label: "Miasto", before: "Gdańsk", after: "Kraków", source: null, note: "na karcie zostaje wartość wpisana ręcznie", other_company: null },
            { label: "Domena", before: null, after: "firma.example", source: null, note: "jest już na innej karcie, scal karty ręcznie", other_company: { id: 8, name: "Inna Karta" } },
          ],
        },
      ],
    });
    render(<BotCardHistory companyId={7} />);
    expect(screen.getByText("Historia zmian karty")).toBeInTheDocument();
    expect(screen.getByText(/Dane firm \(automat\)/)).toBeInTheDocument();
    expect(screen.getByText("Gdańsk")).toHaveClass("line-through");
    expect(screen.getByRole("link", { name: "Inna Karta" })).toHaveAttribute("href", "/sales/companies/8");
    expect(screen.getByRole("link", { name: /rejestr\.example/ })).toBeInTheDocument();
  });

  it("bez wpisów nic nie pokazuje, błąd to komunikat, nie pustka", () => {
    const { container, rerender } = render(<BotCardHistory companyId={7} />);
    expect(container).toBeEmptyDOMElement();
    historyQuery = failed;
    rerender(<BotCardHistory companyId={7} />);
    expect(screen.getByText("Nie udało się wczytać historii zmian karty.")).toBeInTheDocument();
  });
});

describe("EnrichButton", () => {
  it("z wyłączoną flagą go nie ma, w trakcie biegu jest nieaktywny", () => {
    enrichQuery = ok<EnrichState>({ enabled: false, run: null, result: null });
    const { container, rerender } = render(<EnrichButton companyId={7} />);
    expect(container).toBeEmptyDOMElement();
    enrichQuery = ok(RUNNING);
    rerender(<EnrichButton companyId={7} />);
    expect(screen.getByRole("button", { name: "Szukam danych…" })).toBeDisabled();
  });

  it("zleca uzupełnienie karty", () => {
    render(<EnrichButton companyId={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij dane" }));
    expect(start).toHaveBeenCalled();
  });
});

describe("AskBotCard", () => {
  it("w trakcie wczytywania i przy wyłączonej fladze nic nie pokazuje", () => {
    questionsQuery = loading;
    const { container, rerender } = render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(container).toBeEmptyDOMElement();
    questionsQuery = ok({ enabled: false, items: [] });
    rerender(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria zapytania to komunikat, nie „nikt nie pytał”", () => {
    questionsQuery = failed;
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(screen.getByText("Nie udało się wczytać pytań do bota.")).toBeInTheDocument();
    expect(screen.queryByText("Nikt jeszcze nie pytał bota o tę firmę.")).not.toBeInTheDocument();
  });

  it("pusta lista po udanym zapytaniu", () => {
    questionsQuery = ok({ enabled: true, items: [] });
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(screen.getByText("Nikt jeszcze nie pytał bota o tę firmę.")).toBeInTheDocument();
  });

  it("odpowiedź ze źródłem i czas odpowiedzi, bez plakietki „wniosek bota”", () => {
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(screen.getByText("Zapytaj bota o Firma Testowa")).toBeInTheDocument();
    expect(screen.getByText(/Ewa Testowa · .* · odpowiedź po 4 min/)).toBeInTheDocument();
    expect(screen.getByText("„Czy mają centrum IT w Polsce?”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /news\.example/ })).toBeInTheDocument();
    expect(screen.getByText(/Wniosek: rosną/)).toBeInTheDocument();
    expect(screen.queryByText("wniosek bota")).not.toBeInTheDocument();
  });

  it("trwające pytanie i nieudany bieg z ponowieniem", () => {
    questionsQuery = ok({
      enabled: true,
      items: [
        question({ run_id: 2, status: "started", answer: null, minutes: null, answered_at: null }),
        question({ run_id: 1, status: "expired", answer: null, minutes: null, answered_at: null }),
      ],
    });
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(screen.getByText("Bot szuka odpowiedzi, zwykle kilka minut.")).toBeInTheDocument();
    expect(screen.getByText("Bot nie odpowiedział w ciągu 2 godzin.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapytaj ponownie" }));
    expect(ask).toHaveBeenCalledWith("Czy mają centrum IT w Polsce?", expect.anything());
  });

  it("wysyła pytanie, za krótkie zatrzymuje, odmowę serwera pokazuje", () => {
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    const input = screen.getByLabelText("Pytanie do bota");
    fireEvent.change(input, { target: { value: "co?" } });
    fireEvent.click(screen.getByRole("button", { name: /Zapytaj$/ }));
    expect(ask).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("co najmniej 5 znaków");

    ask.mockImplementation((_q, options) =>
      options.onError({ response: { status: 422, data: { detail: "Pytanie nie może zawierać adresu e-mail." } } }),
    );
    fireEvent.change(input, { target: { value: "  Kogo teraz rekrutują?  " } });
    fireEvent.click(screen.getByRole("button", { name: /Zapytaj$/ }));
    expect(ask).toHaveBeenCalledWith("Kogo teraz rekrutują?", expect.anything());
    expect(screen.getByRole("alert")).toHaveTextContent("adresu e-mail");
  });

  it("podgląd bez edycji nie ma pola pytania", () => {
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit={false} />);
    expect(screen.queryByLabelText("Pytanie do bota")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapytaj ponownie" })).not.toBeInTheDocument();
  });
});
