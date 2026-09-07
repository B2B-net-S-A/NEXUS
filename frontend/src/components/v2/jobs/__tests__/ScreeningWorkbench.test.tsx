/**
 * ScreeningWorkbench — stanowisko screeningu (krok 05, program „flow w języku
 * C2", PR 6/7).
 *
 * Zakres: kolejka (kto się w niej znajduje i co ją opisuje), stany widoku
 * (awaria ≠ pustka), bramka ruchu „Zweryfikowany" widoczna z powodem oraz to,
 * że ruch idzie DOKŁADNIE tym samym `POST /api/pipeline/move` z
 * `expected_rate_*`, którym przenosi karty tablica.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const move = vi.fn();
const getForStage = vi.fn();
const submitScreening = vi.fn();
const listForJob = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
  screeningApi: {
    getForStage: (...a: unknown[]) => getForStage(...a),
    submit: (...a: unknown[]) => submitScreening(...a),
  },
  interviewQuestionsApi: { listForJob: (...a: unknown[]) => listForJob(...a) },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

import { ScreeningWorkbench } from "@/components/v2/jobs/ScreeningWorkbench";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 11,
    candidate_id: 111,
    stage: "screening",
    name: "Grzegorz",
    lastname: "Żebrowski",
    days_in_stage: 3,
    ...overrides,
  };
}

function columns(screeningItems: KanbanItem[]): KanbanColumn[] {
  return [
    {
      stage: "screening",
      name: "Screening",
      category: "internal",
      stage_def_id: 3,
      count: screeningItems.length,
      items: screeningItems,
    },
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: 4,
      count: 0,
      items: [],
    },
  ];
}

function renderWorkbench(
  overrides: Partial<React.ComponentProps<typeof ScreeningWorkbench>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onMoved = vi.fn();
  const onRetry = vi.fn();
  const onTabChange = vi.fn();
  const utils = render(
    <QueryClientProvider client={client}>
      <ScreeningWorkbench
        jobId={7}
        jobBudgetMax={20000}
        columns={columns([item(), item({ id: 12, candidate_id: 112, name: "Marcin", lastname: "Jóźwiak", days_in_stage: 8 })])}
        isLoading={false}
        isError={false}
        error={null}
        isSuccess
        onRetry={onRetry}
        onMoved={onMoved}
        readOnly={false}
        onTabChange={onTabChange}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onMoved, onRetry, onTabChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  getForStage.mockResolvedValue({
    data: {
      stage_id: 11,
      candidate_id: 111,
      job_id: 7,
      champion_profile: {
        screening_questions: [
          {
            id: "q1",
            question: "Kafka w produkcji?",
            ideal_answer: "projektował topics",
            deal_breaker: "tylko konsumował",
          },
        ],
      },
      screening_answers: null,
    },
  });
  listForJob.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }, { id: 3 }] });
  move.mockResolvedValue({ data: { id: 99, verification_status: "active" } });
});

describe("ScreeningWorkbench", () => {
  it("kolejka pokazuje osoby z etapu Screening z wiekiem na etapie", async () => {
    renderWorkbench();
    const queue = screen.getByRole("list", { name: "Kolejka screeningu" });
    expect(within(queue).getByText("Grzegorz Żebrowski")).toBeTruthy();
    expect(within(queue).getByText("Marcin Jóźwiak")).toBeTruthy();
    expect(within(queue).getByText("3 d")).toBeTruthy();
    expect(within(queue).getByText("8 d")).toBeTruthy();
  });

  it("pierwsza pozycja kolejki jest wybrana sama — stanowisko nie startuje puste", async () => {
    renderWorkbench();
    expect(
      await screen.findByRole("heading", {
        name: /Screening · Grzegorz Żebrowski/,
      }),
    ).toBeTruthy();
  });

  it("pusta kolejka to pusty stan, a nie awaria", () => {
    renderWorkbench({ columns: columns([]) });
    expect(
      screen.getByText(/Kolejka screeningu jest pusta/),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("403 na kanbanie renderuje brak uprawnień, nigdy pustej kolejki", () => {
    renderWorkbench({
      columns: [],
      isError: true,
      isSuccess: false,
      error: { response: { status: 403 } },
    });
    expect(screen.getByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText(/Kolejka screeningu jest pusta/)).toBeNull();
  });

  it("awaria kanbana daje przycisk ponowienia, nie pustkę", async () => {
    const { onRetry } = renderWorkbench({
      columns: [],
      isError: true,
      isSuccess: false,
      error: { response: { status: 500 } },
    });
    await userEvent.click(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    );
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("bez stawki ruch jest zablokowany z powodem, nie 422 po kliknięciu", async () => {
    renderWorkbench();
    const button = await screen.findByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      "title",
      expect.stringContaining("Podaj stawkę oczekiwaną"),
    );
    expect(move).not.toHaveBeenCalled();
  });

  it("weto hiring managera blokuje ruch i mówi dlaczego", async () => {
    renderWorkbench({
      columns: columns([
        item({
          hm_veto: {
            hiring_manager_contact_id: 5,
            source_job_id: 2,
            rejected_at: "2026-01-01",
            rejection_reason_name: "Brak bankowości",
          },
        }),
      ]),
    });
    const button = await screen.findByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("Brak bankowości");
  });

  it("tryb tylko do odczytu chowa zapis screeningu i ruch", async () => {
    renderWorkbench({ readOnly: true });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    expect(
      screen.queryByRole("button", { name: /Zapisz screening/ }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: /Zweryfikowany — zapisz stawkę i przenieś/,
      }),
    ).toBeNull();
  });

  it("wpisana stawka odblokowuje ruch i idzie tym samym endpointem co drag&drop", async () => {
    const { onMoved } = renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });

    await userEvent.type(screen.getByLabelText("Kwota"), "118");

    const button = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    await userEvent.click(button);

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(move).toHaveBeenCalledWith({
      candidate_id: 111,
      job_id: 7,
      stage: "verified",
      stage_def_id: 4,
      expected_rate_value: 118,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
    });
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
  });

  it("stawka ponad budżet zapowiada akceptację ZANIM ktoś kliknie", async () => {
    renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    // 130 × 168 = 21 840 > 20 000 — surowe porównanie mówiłoby „mieści się".
    await userEvent.type(screen.getByLabelText("Kwota"), "130");
    expect(await screen.findByText(/Karta trafi na „Pending”/)).toBeTruthy();
  });

  it("linkuje prep-kit, który dotąd nie miał żadnego wejścia w aplikacji", async () => {
    renderWorkbench();
    const link = await screen.findByRole("link", { name: /Prep-kit/ });
    expect(link).toHaveAttribute("href", "/jobs/7/prep/111");
  });

  it("pokazuje liczbę pytań przypiętych do rekrutacji", async () => {
    renderWorkbench();
    await waitFor(() => expect(listForJob).toHaveBeenCalledWith(7));
    expect(await screen.findByText("3")).toBeTruthy();
  });
});
