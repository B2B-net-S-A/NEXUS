/**
 * Jeden widok „Screening” tylko do odczytu (09.10.2026) — zastąpił zwartą
 * kartę rekomendacji, okno całej karty i zapisany arkusz. Dane fikcyjne.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  showInfo: vi.fn(),
  showError: vi.fn(),
  copy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.get(...args) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showInfo: mocks.showInfo, showError: mocks.showError }),
}));
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...args: unknown[]) => mocks.copy(...args),
}));

import { ScreeningSummaryDialog } from "@/components/v2/screening-form/ScreeningSummaryDialog";
import {
  ScreeningLegacyText,
  ScreeningSummarySection,
  ScreeningSummaryView,
} from "@/components/v2/screening-form/ScreeningSummaryView";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

function withClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const FILLED = formState({
  sheet: {
    answers: [{ question_id: "q1", response: "6 lat", deal_breaker_hit: true, question_text: "Ile lat pracujesz z Javą?" }],
    overall_fit: "uncertain",
    notes: "",
    answered_at: "2026-10-06T10:00:00Z",
  },
  questions: [
    {
      number: 1,
      question: "Ile lat pracujesz z Javą?",
      answer: "6 lat",
      source: "sheet",
      question_id: "q1",
      deal_breaker: "Poniżej 2 lat",
      deal_breaker_hit: true,
    },
    {
      number: 2,
      question: "Czy pracowałeś z Kafką?",
      answer: "Tak, produkcyjnie",
      source: "note",
      question_id: "q2",
      deal_breaker: null,
      deal_breaker_hit: false,
    },
  ],
  card: {
    fields: {
      availability: { raw: "od 1 listopada", source: "manual", by_name: "Marta Testowa" },
      recommendation: { raw: "Zna domenę płatności.", source: "manual", by_name: "Marta Testowa" },
    },
    previous: { work_mode: { raw: "zdalnie" } },
    suggestions: {},
    completeness: { status: "partial", filled: 3, total: 10, missing: ["work_mode", "red_flags"] },
    labels: { availability: "Dostępność", work_mode: "Tryb pracy", recommendation: "Notatka", red_flags: "Red flags" },
    editable_fields: ["availability", "work_mode", "rate", "recommendation", "red_flags"],
  },
  rate: { amount: 140, unit: "hourly", currency: "PLN", source: "stage", at: null },
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ScreeningSummaryView", () => {
  it("pokazuje warunki, pytania i ocenę w kolejności formularza — bez słowa „karta”", () => {
    render(<ScreeningSummaryView state={FILLED} />);
    const view = screen.getByTestId("screening-form-readonly");

    const status = within(view).getByTestId("screening-summary-status");
    expect(status).toHaveTextContent("Niepewne");
    expect(status).toHaveTextContent("Odpowiedzi: 2 z 2");
    expect(status).toHaveTextContent("Brakuje pól: 2");
    expect(within(status).getByText("Brakuje pól: 2")).toHaveAttribute("title", "Brakuje: Tryb pracy, Red flags");

    const terms = within(view).getByTestId("screening-form-readonly-terms");
    expect(terms).toHaveTextContent("Stawka kandydata");
    expect(terms).toHaveTextContent("140 zł/h");
    expect(terms).toHaveTextContent("od 1 listopada");
    // Puste pole podpowiada wartość z poprzedniej próby zamiast samego „brak”.
    expect(terms).toHaveTextContent("brak — ostatnio: zdalnie");
    // Skąd jest wartość — w dymku.
    expect(within(terms).getByText("od 1 listopada")).toHaveAttribute("title", "wpisał(a) Marta Testowa");

    const answers = within(view).getByRole("list", { name: "Pytania i odpowiedzi" });
    expect(within(answers).getByText("Odpada, gdy: Poniżej 2 lat")).toBeInTheDocument();
    expect(within(answers).getByText("odpowiedź z notatki")).toBeInTheDocument();
    expect(within(view).getByTestId("screening-summary-deal-breaker")).toHaveTextContent(
      "Odpowiedź na pytanie 1 narusza „Odpada, gdy…”.",
    );

    const assessment = within(view).getByTestId("screening-form-readonly-assessment");
    expect(assessment).toHaveTextContent("Dlaczego ten kandydat");
    expect(assessment).toHaveTextContent("Zna domenę płatności.");
    expect(assessment).toHaveTextContent("Red flags — tylko dla zespołu");

    // Kolejność: warunki → pytania → ocena.
    const order = [terms, answers, assessment].map((node) => Array.from(view.querySelectorAll("*")).indexOf(node));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(view).not.toHaveTextContent(/kart[aęyą] rekomendacji/i);
  });

  it("stawka zapisana tekstem zostaje widoczna, gdy nie ma stawki na etapie", () => {
    render(<ScreeningSummaryView state={{ ...FILLED, rate: null, rate_text: "130–150 zł/h" }} />);
    expect(screen.getByTestId("screening-form-readonly-terms")).toHaveTextContent("130–150 zł/h");
  });

  it("komunikat blokady stoi tylko tam, gdzie widok zastępuje formularz", () => {
    const locked = { ...FILLED, editable: false, read_only_message: "Proces zakończony." };
    const { rerender } = render(<ScreeningSummaryView state={locked} />);
    expect(screen.queryByText("Proces zakończony.")).toBeNull();
    rerender(<ScreeningSummaryView state={locked} showLockNote />);
    expect(screen.getByText("Proces zakończony.")).toBeInTheDocument();
  });

  it("pusty screening mówi wprost, czego nie ma", () => {
    render(
      <ScreeningSummaryView
        state={formState({ champion_profile: {}, questions: [], card: { ...FILLED.card, fields: {}, previous: {} } })}
      />,
    );
    expect(screen.getByText("Ta rekrutacja nie ma pytań ani zapisanych odpowiedzi.")).toBeInTheDocument();
    const terms = screen.getByTestId("screening-form-readonly-terms");
    expect(within(terms).getByText("Stawka kandydata").nextElementSibling).toHaveTextContent("brak");
  });

  it("rekrutacja bez pytań w profilu: pytania z notatki nie udają pytań z Profilu Championa", () => {
    render(
      <ScreeningSummaryView
        state={formState({
          champion_profile: {},
          questions: [
            {
              number: 1,
              question: "Doświadczenie z mikroserwisami?",
              answer: "Pięć lat.",
              source: "note",
              question_id: null,
              deal_breaker: null,
              deal_breaker_hit: false,
            },
          ],
        })}
      />,
    );
    expect(screen.getByRole("heading", { name: "Pytania i odpowiedzi" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Pytania z Profilu Championa" })).toBeNull();
    expect(screen.getByText("odpowiedź z notatki")).toBeInTheDocument();
  });

  it("„Edytuj” otwiera formularz w panelu, a bez niego jest link do rekrutacji", async () => {
    const onEdit = vi.fn();
    const { rerender } = render(<ScreeningSummaryView state={FILLED} onEdit={onEdit} />);
    await userEvent.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(onEdit).toHaveBeenCalledTimes(1);
    rerender(<ScreeningSummaryView state={FILLED} editHref="/jobs/201?candidate=101&panel=screening" />);
    expect(screen.getByRole("link", { name: /Edytuj w screeningu/ })).toHaveAttribute(
      "href",
      "/jobs/201?candidate=101&panel=screening",
    );
  });
});

describe("ScreeningLegacyText", () => {
  it("pobiera tekst w starym formacie dopiero po rozwinięciu i kopiuje go", async () => {
    mocks.get.mockResolvedValue({ data: { legacy_text: "Stawka: 140 zł/h\nDostępność: od 1 listopada" } });
    mocks.copy.mockResolvedValue(true);
    withClient(<ScreeningLegacyText candidateId={101} jobId={201} />);
    const toggle = screen.getByRole("button", { name: "W starym formacie" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(mocks.get).not.toHaveBeenCalled();

    await userEvent.click(toggle);
    expect(await screen.findByText(/Stawka: 140 zł\/h/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/recommendation-cards",
      expect.objectContaining({ params: { candidate_id: 101, job_id: 201 } }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Kopiuj" }));
    expect(mocks.copy).toHaveBeenCalledWith("Stawka: 140 zł/h\nDostępność: od 1 listopada");
    await waitFor(() => expect(mocks.showInfo).toHaveBeenCalledWith("Skopiowano tekst w starym formacie."));
  });

  it("awaria odczytu to komunikat z „Ponów”, nie pusty tekst", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    withClient(<ScreeningLegacyText candidateId={101} jobId={201} />);
    await userEvent.click(screen.getByRole("button", { name: "W starym formacie" }));
    expect(await screen.findByText("Nie udało się wczytać tekstu.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kopiuj" })).toBeNull();
  });
});

describe("ScreeningSummarySection i okno w profilu", () => {
  it("awaria odczytu screeningu nie wygląda jak pusty screening", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    withClient(<ScreeningSummarySection candidateId={101} jobId={201} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać screeningu.");
    expect(screen.queryByTestId("screening-form-readonly")).toBeNull();

    mocks.get.mockResolvedValue({ data: FILLED });
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByTestId("screening-form-readonly")).toBeInTheDocument();
  });

  it("okno „Screening” w profilu: tylko odczyt, link do edycji przy trwającym procesie", async () => {
    mocks.get.mockResolvedValue({ data: FILLED });
    withClient(
      <ScreeningSummaryDialog
        open
        onOpenChange={() => undefined}
        candidateId={101}
        jobId={201}
        candidateName="Tomasz Wzorcowy"
        jobTitle="Senior Java Developer"
      />,
    );
    const dialog = await screen.findByRole("dialog", { name: "Screening" });
    expect(dialog).toHaveTextContent("Tomasz Wzorcowy · Senior Java Developer");
    expect(await within(dialog).findByTestId("screening-form-readonly")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Edytuj w screeningu/ })).toHaveAttribute(
      "href",
      "/jobs/201?candidate=101&panel=screening",
    );
    // Jedno zapytanie na okno — nagłówek i treść czytają ten sam klucz.
    expect(mocks.get.mock.calls.filter(([url]) => url === "/api/screening-form")).toHaveLength(1);
  });

  it("zakończony proces albo profil bez prawa zapisu: bez linku do edycji", async () => {
    mocks.get.mockResolvedValue({ data: { ...FILLED, editable: false, read_only_reason: "process_closed" } });
    withClient(
      <ScreeningSummaryDialog open onOpenChange={() => undefined} candidateId={101} jobId={201} candidateName="Tomasz Wzorcowy" />,
    );
    await screen.findByTestId("screening-form-readonly");
    expect(screen.queryByRole("link", { name: /Edytuj w screeningu/ })).toBeNull();
  });
});
