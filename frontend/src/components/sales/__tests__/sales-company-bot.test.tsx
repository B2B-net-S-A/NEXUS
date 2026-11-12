/** Karta firmy: „Uzupełnij z bota” (G-A) i „Zapytaj bota” (G-B). Dane fikcyjne. */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SalesCompany } from "@/lib/api/sales";
import type { BotQuestion, EnrichResult, EnrichState } from "@/lib/api/sales-bot";

type QueryState<T> = {
  data?: T;
  isLoading: boolean;
  isError: boolean;
  isSuccess: boolean;
  refetch: () => void;
};

const refetch = vi.fn();
const decide = vi.fn();
const reject = vi.fn();
const start = vi.fn();
const ask = vi.fn();
const toast = { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() };

let enrichQuery: QueryState<EnrichState>;
let questionsQuery: QueryState<{ enabled: boolean; items: BotQuestion[] }>;

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
  useDecideEnrich: () => ({ mutate: decide, isPending: false }),
  useRejectEnrich: () => ({ mutate: reject, isPending: false }),
  useCompanyQuestions: () => questionsQuery,
  useAskBot: () => ({ mutate: ask, isPending: false }),
}));

import { AskBotCard } from "../bot/AskBotCard";
import { EnrichButton, EnrichCard } from "../bot/EnrichCard";

const company = {
  id: 7,
  name: "Firma Testowa",
  nip: null,
  domain: null,
  website_url: null,
  hq_city: "Gdańsk",
  industry: null,
  tier: null,
  parent: null,
} as unknown as SalesCompany;

function result(over: Partial<EnrichResult["payload"]> = {}): EnrichResult {
  return {
    id: 31,
    kind: "enrich",
    company: { id: 7, name: "Firma Testowa" },
    status: "new",
    payload: {
      fields: {
        domain: { value: "firma-testowa.example", source: "https://rejestr.example/a" },
        hq_city: { value: "Kraków", source: "https://www.firma-testowa.example/kontakt" },
        tier: { value: "enterprise", employees: "1000+", source: "https://rejestr.example/b" },
      },
      checked_at: "2026-11-12T03:00:00Z",
      ...over,
    },
    created_at: "2026-11-12T03:00:00Z",
    run_id: 4,
  };
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
  enrichQuery = ok<EnrichState>({ enabled: true, run: null, result: result() });
  questionsQuery = ok({ enabled: true, items: [question()] });
});

describe("EnrichCard", () => {
  it("w trakcie wczytywania i przy wyłączonej fladze nic nie pokazuje", () => {
    enrichQuery = loading;
    const { container, rerender } = render(<EnrichCard company={company} canEdit />);
    expect(container).toBeEmptyDOMElement();
    enrichQuery = ok<EnrichState>({ enabled: false, run: null, result: null });
    rerender(<EnrichCard company={company} canEdit />);
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria zapytania to komunikat z ponowieniem, nie brak propozycji", () => {
    enrichQuery = failed;
    render(<EnrichCard company={company} canEdit />);
    expect(screen.getByText("Nie udało się wczytać propozycji bota dla tej karty.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /spróbuj/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("bez propozycji pokazuje tylko trwające sprawdzanie", () => {
    enrichQuery = ok<EnrichState>({ enabled: true, run: { id: 4, status: "started", started_at: "2026-11-12T08:00:00Z" }, result: null });
    const { container, rerender } = render(<EnrichCard company={company} canEdit />);
    expect(screen.getByText("Bot sprawdza kartę, zwykle kilka minut.")).toBeInTheDocument();
    enrichQuery = ok<EnrichState>({ enabled: true, run: { id: 4, status: "received", started_at: "2026-11-12T08:00:00Z" }, result: null });
    rerender(<EnrichCard company={company} canEdit />);
    expect(container).toBeEmptyDOMElement();
  });

  it("pokazuje obecną i proponowaną wartość ze źródłem", () => {
    render(<EnrichCard company={company} canEdit />);
    expect(screen.getByText("Bot uzupełnił kartę")).toBeInTheDocument();
    // Wartość pola i domena źródła ze strony firmy.
    expect(screen.getAllByText("firma-testowa.example")).toHaveLength(2);
    expect(screen.getByText("teraz: Gdańsk")).toBeInTheDocument();
    expect(screen.getByText("Duża (1000+ osób)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /firma-testowa\.example/ })).toHaveAttribute(
      "href",
      "https://www.firma-testowa.example/kontakt",
    );
    expect(screen.getByText(/Nic nie zapisuje się samo/)).toBeInTheDocument();
  });

  it("przyjmuje i odrzuca pole po polu", () => {
    render(<EnrichCard company={company} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Przyjmij: Domena" }));
    expect(decide).toHaveBeenLastCalledWith({ resultId: 31, fields: ["domain"] }, expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć: Miasto" }));
    expect(decide).toHaveBeenLastCalledWith({ resultId: 31, fields: [], reject: ["hq_city"] }, expect.anything());
  });

  it("„Przyjmij puste pola” nie nadpisuje wartości z karty", () => {
    render(<EnrichCard company={company} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Przyjmij puste pola" }));
    expect(decide).toHaveBeenLastCalledWith({ resultId: 31, fields: ["domain", "tier"] }, expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć resztę" }));
    expect(reject).toHaveBeenCalledWith(31, expect.anything());
  });

  it("po zapisie pokazuje zapisane pola i uwagi", () => {
    decide.mockImplementation((_vars, options) =>
      options.onSuccess({ id: 31, status: "partial", company_id: 7, applied: ["domain"], rejected: [], notes: ["Uwaga testowa"] }),
    );
    render(<EnrichCard company={company} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Przyjmij: Domena" }));
    expect(toast.showSuccess).toHaveBeenCalledWith("Zapisano na karcie: Domena.");
    expect(toast.showInfo).toHaveBeenCalledWith("Uwaga testowa");
  });

  it("odmowa z serwera (np. domena na innej karcie) idzie do komunikatu", () => {
    decide.mockImplementation((_vars, options) =>
      options.onError({ response: { status: 409, data: { detail: "Domena jest już na karcie „Inna”." } } }),
    );
    render(<EnrichCard company={company} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Przyjmij: Domena" }));
    expect(toast.showError).toHaveBeenCalledWith(expect.stringContaining("Inna"));
  });

  it("rozstrzygnięte pola i podgląd bez edycji nie mają przycisków", () => {
    enrichQuery = ok<EnrichState>({
      enabled: true,
      run: null,
      result: { ...result({ decisions: { domain: "accepted", hq_city: "rejected" } }), status: "partial" },
    });
    render(<EnrichCard company={company} canEdit={false} />);
    expect(screen.getByText("przyjęte")).toBeInTheDocument();
    expect(screen.getByText("odrzucone")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Przyjmij/ })).not.toBeInTheDocument();
  });
});

describe("EnrichButton", () => {
  it("z wyłączoną flagą go nie ma, w trakcie biegu jest nieaktywny", () => {
    enrichQuery = ok<EnrichState>({ enabled: false, run: null, result: null });
    const { container, rerender } = render(<EnrichButton companyId={7} />);
    expect(container).toBeEmptyDOMElement();
    enrichQuery = ok<EnrichState>({ enabled: true, run: { id: 4, status: "started", started_at: "2026-11-12T08:00:00Z" }, result: null });
    rerender(<EnrichButton companyId={7} />);
    expect(screen.getByRole("button", { name: "Bot sprawdza kartę…" })).toBeDisabled();
  });

  it("zleca sprawdzenie karty", () => {
    enrichQuery = ok<EnrichState>({ enabled: true, run: null, result: null });
    render(<EnrichButton companyId={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij z bota" }));
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

  it("odpowiedź ze źródłem, wniosek bota i czas odpowiedzi", () => {
    render(<AskBotCard companyId={7} companyName="Firma Testowa" canEdit />);
    expect(screen.getByText("Zapytaj bota o Firma Testowa")).toBeInTheDocument();
    expect(screen.getByText(/Ewa Testowa · .* · odpowiedź po 4 min/)).toBeInTheDocument();
    expect(screen.getByText("„Czy mają centrum IT w Polsce?”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /news\.example/ })).toBeInTheDocument();
    expect(screen.getByText("wniosek bota")).toBeInTheDocument();
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
