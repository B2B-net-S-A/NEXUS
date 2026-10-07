/**
 * ScreeningWorkbench — sekcja „Screening” panelu osoby (0424, 07.10.2026).
 *
 * Gospodarz decyduje, CO stoi po lewej (profil przed telefonem, formularz,
 * historia zakończonego procesu) i z jakimi ruchami, a obok zawsze podgląd
 * CV/wymagań. Sam formularz i podgląd mają własne testy — tu są stubami,
 * które mówią, jakie propsy dostały.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { formState } from "@/test/fixtures/screening-form";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  listForJob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  interviewQuestionsApi: { listForJob: (...a: unknown[]) => mocks.listForJob(...a) },
}));

vi.mock("@/components/v2/screening-form/ScreeningFullForm", () => ({
  ScreeningFullForm: (props: {
    candidateId: number;
    forward: { label: string; stage: string; stageDefId: number | null } | null;
    reject: { stage: string; previousStage: string } | null;
    readOnly: boolean;
    banner?: React.ReactNode;
  }) => (
    <div data-testid="full-form">
      <span>formularz kandydata {props.candidateId}</span>
      <span>{props.forward ? `dalej: ${props.forward.label} (${props.forward.stageDefId})` : "bez ruchu dalej"}</span>
      <span>{props.reject ? `odrzuć: ${props.reject.stage} z ${props.reject.previousStage}` : "bez odrzucenia"}</span>
      <span>{props.readOnly ? "tylko odczyt" : "edycja"}</span>
      {props.banner}
    </div>
  ),
}));

vi.mock("@/components/v2/screening-form/BeforeCallProfile", () => ({
  BeforeCallProfile: (props: { onStartScreening: () => void; onTake?: () => void }) => (
    <div data-testid="before-call">
      <button type="button" onClick={props.onStartScreening}>
        Zacznij screening
      </button>
      {props.onTake ? (
        <button type="button" onClick={props.onTake}>
          Biorę — 12 h
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/v2/screening-form/CandidatePreviewPane", () => ({
  CandidatePreviewPane: (props: { tab: string; stageId: number | null; onTabChange: (tab: string) => void }) => (
    <div data-testid="preview-pane">
      podgląd: {props.tab} · etap {props.stageId}
      <button type="button" onClick={() => props.onTabChange("plain")}>
        Po ludzku
      </button>
    </div>
  ),
}));

vi.mock("@/components/v2/screening/RecommendationCardSection", () => ({
  RecommendationCardSection: (props: { readOnly?: boolean }) => (
    <div data-testid="card-section">{props.readOnly ? "karta tylko do odczytu" : "karta"}</div>
  ),
}));

vi.mock("@/components/v2/screening-form/ScreeningFormHistory", () => ({
  ScreeningFormHistory: (props: { canRestore: boolean }) => (
    <div data-testid="form-history">{props.canRestore ? "z przywracaniem" : "bez przywracania"}</div>
  ),
}));

import { ScreeningWorkbench } from "@/components/v2/jobs/ScreeningWorkbench";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 11,
    candidate_id: 111,
    stage: "new",
    name: "Grzegorz",
    lastname: "Żebrowski",
    days_in_stage: 3,
    ...overrides,
  };
}

function board(): KanbanColumn[] {
  return [
    { stage: "new", name: "Nowi", category: "internal", stage_def_id: 1, count: 1, items: [item()] },
    {
      stage: "screening",
      name: "Screening",
      category: "internal",
      stage_def_id: 2,
      count: 1,
      items: [item({ id: 12, candidate_id: 112, stage: "screening", name: "Marcin", lastname: "Jóźwiak" })],
    },
    { stage: "verified", name: "Zweryfikowany", category: "internal", stage_def_id: 4, count: 0, items: [] },
    {
      stage: "cv_sent",
      name: "CV wysłane",
      category: "external",
      stage_def_id: 6,
      count: 1,
      items: [item({ id: 13, candidate_id: 113, stage: "cv_sent", name: "Ewa", lastname: "Przykładowa" })],
    },
    {
      stage: "rejected",
      name: "Odrzucony",
      category: "internal",
      stage_def_id: 9,
      count: 0,
      items: [],
      is_terminal: true,
      terminal_type: "rejected",
    } as KanbanColumn,
  ];
}

const states = new Map<number, ScreeningFormState>();

function renderWorkbench(overrides: Partial<ComponentProps<typeof ScreeningWorkbench>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onTabChange = vi.fn();
  const onRetry = vi.fn();
  const onTake = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ScreeningWorkbench
        jobId={7}
        jobBudgetHourly={100}
        columns={board()}
        isLoading={false}
        isError={false}
        error={null}
        isSuccess
        onRetry={onRetry}
        onMoved={vi.fn()}
        readOnly={false}
        onTabChange={onTabChange}
        onTake={onTake}
        focusCandidateId={111}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { onTabChange, onRetry, onTake };
}

beforeEach(() => {
  vi.clearAllMocks();
  states.clear();
  states.set(111, formState({ candidate_id: 111, job_id: 7, stage_id: 11, board_column: "new" }));
  states.set(
    112,
    formState({
      candidate_id: 112,
      job_id: 7,
      stage_id: 12,
      board_column: "screening",
      version: 1,
      versions_count: 1,
      sheet: { answers: [{ question_id: "q1", response: "6 lat", deal_breaker_hit: false }], overall_fit: "fit", notes: "" },
    }),
  );
  states.set(113, formState({ candidate_id: 113, job_id: 7, stage_id: 13, board_column: "cv_sent", version: 2, versions_count: 2 }));
  mocks.get.mockImplementation((_url: string, config: { params: { candidate_id: number } }) =>
    Promise.resolve({ data: states.get(config.params.candidate_id) }),
  );
  mocks.listForJob.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }] });
});

describe("ScreeningWorkbench — co stoi po lewej", () => {
  it("„Nowi” bez zapisanego formularza: profil przed telefonem i CV obok; „Zacznij screening” otwiera formularz", async () => {
    const user = userEvent.setup();
    renderWorkbench();
    expect(await screen.findByTestId("before-call")).toBeVisible();
    expect(screen.queryByTestId("full-form")).toBeNull();
    expect(await screen.findByTestId("preview-pane")).toHaveTextContent("podgląd: cv · etap 11");

    await user.click(screen.getByRole("button", { name: "Zacznij screening" }));
    expect(screen.getByTestId("full-form")).toHaveTextContent("dalej: Zweryfikowany (4)");
    expect(screen.getByTestId("full-form")).toHaveTextContent("odrzuć: rejected z new");
    expect(screen.getByTestId("before-call")).not.toBeVisible();
    expect(screen.getByTestId("preview-pane")).toHaveTextContent("podgląd: requirements");

    // Powrót do profilu nie gubi formularza (zostaje zamontowany).
    await user.click(screen.getByRole("button", { name: /Profil przed telefonem/ }));
    expect(screen.getByTestId("before-call")).toBeVisible();
    expect(screen.getByTestId("full-form")).not.toBeVisible();
  });

  it("„Biorę — 12 h” z profilu przed telefonem woła blokadę dla tej osoby", async () => {
    const user = userEvent.setup();
    const { onTake } = renderWorkbench();
    await user.click(await screen.findByRole("button", { name: "Biorę — 12 h" }));
    expect(onTake).toHaveBeenCalledWith(expect.objectContaining({ candidate_id: 111 }));
  });

  it("„Screening”: od razu formularz z wymaganiami obok", async () => {
    renderWorkbench({ focusCandidateId: 112 });
    expect(await screen.findByTestId("full-form")).toHaveTextContent("formularz kandydata 112");
    expect(screen.getByTestId("full-form")).toHaveTextContent("odrzuć: rejected z screening");
    expect(screen.queryByTestId("before-call")).toBeNull();
    expect(await screen.findByTestId("preview-pane")).toHaveTextContent("podgląd: requirements · etap 12");
  });

  it("„Nowi” z zapisanym formularzem nie wraca do profilu przed telefonem", async () => {
    states.set(111, formState({ candidate_id: 111, job_id: 7, stage_id: 11, version: 1, versions_count: 1 }));
    renderWorkbench();
    expect(await screen.findByTestId("full-form")).toBeInTheDocument();
    expect(screen.queryByTestId("before-call")).toBeNull();
  });

  it("po „CV wysłane”: formularz z banerem D8, bez ruchu dalej i odrzucenia", async () => {
    renderWorkbench({ focusCandidateId: 113 });
    const form = await screen.findByTestId("full-form");
    expect(form).toHaveTextContent("bez ruchu dalej");
    expect(form).toHaveTextContent("bez odrzucenia");
    expect(await screen.findByTestId("screening-after-cv-sent")).toHaveTextContent(
      "trafi do następnego CV firmowego",
    );
  });

  it("proces zakończony: zapisany arkusz, karta tylko do odczytu i historia bez przywracania", async () => {
    states.set(
      112,
      formState({
        candidate_id: 112,
        job_id: 7,
        editable: false,
        read_only_reason: "process_closed",
        read_only_message: "Proces zakończony.",
        version: 3,
        versions_count: 3,
      }),
    );
    renderWorkbench({ focusCandidateId: 112, panelFallback: <p>Zapisany arkusz screeningu</p> });
    expect(await screen.findByTestId("screening-ended")).toHaveTextContent("Zapisany arkusz screeningu");
    expect(screen.getByTestId("card-section")).toHaveTextContent("karta tylko do odczytu");
    expect(screen.getByTestId("form-history")).toHaveTextContent("bez przywracania");
    expect(screen.queryByTestId("full-form")).toBeNull();
  });

  it("tryb tylko do odczytu: formularz bez ruchów", async () => {
    renderWorkbench({ focusCandidateId: 112, readOnly: true });
    const form = await screen.findByTestId("full-form");
    expect(form).toHaveTextContent("bez ruchu dalej");
    expect(form).toHaveTextContent("bez odrzucenia");
    expect(form).toHaveTextContent("tylko odczyt");
  });
});

describe("ScreeningWorkbench — stany i nagłówek", () => {
  it("osoby nie ma na Tablicy: fallback panelu albo zdanie, nie pustka", async () => {
    renderWorkbench({ focusCandidateId: 999 });
    expect(screen.getByText("Tej osoby nie ma dziś na Tablicy tej rekrutacji.")).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalledWith("/api/screening-form", expect.anything());
  });

  it("403 na kanbanie renderuje brak uprawnień", () => {
    renderWorkbench({ columns: [], isError: true, isSuccess: false, error: { response: { status: 403 } } });
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
  });

  it("awaria kanbana daje „Ponów”", async () => {
    const user = userEvent.setup();
    const { onRetry } = renderWorkbench({
      columns: [],
      isError: true,
      isSuccess: false,
      error: { response: { status: 500 } },
    });
    await user.click(screen.getByRole("button", { name: /Ponów|Spróbuj ponownie/ }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("nagłówek: Prep-kit, „Baza pytań” z liczbą przypiętych i pełny profil", async () => {
    const user = userEvent.setup();
    const { onTabChange } = renderWorkbench({ focusCandidateId: 112 });
    await screen.findByTestId("full-form");
    expect(screen.getByRole("link", { name: /Prep-kit/ })).toHaveAttribute("href", "/jobs/7/prep/112");
    expect(screen.getByRole("link", { name: /Pełny profil/ }).getAttribute("href")).toMatch(/^\/candidates\/112\?/);
    const questions = await screen.findByRole("button", { name: /Baza pytań · przypięte: 2/ });
    await user.click(questions);
    expect(onTabChange).toHaveBeenCalledWith("questions");
  });

  it("plakietki „Ponad budżet” i „Weto HM” to informacja przy osobie", async () => {
    const columns = board();
    columns[1].items[0] = {
      ...columns[1].items[0],
      expected_rate_value: 200,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
      hm_veto: { rejection_reason_name: "Za mało doświadczenia" },
    } as KanbanItem;
    renderWorkbench({ focusCandidateId: 112, columns });
    await screen.findByTestId("full-form");
    expect(screen.getByText("Weto HM")).toBeInTheDocument();
    expect(screen.getByText("Ponad budżet")).toBeInTheDocument();
  });

  it("na wąskim panelu podgląd chowa się za przyciskiem", async () => {
    const user = userEvent.setup();
    renderWorkbench({ focusCandidateId: 112 });
    await screen.findByTestId("full-form");
    const toggle = screen.getByRole("button", { name: "Pokaż CV i wymagania" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("screening-preview-column").className).toContain("hidden");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Schowaj podgląd" })).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(screen.getByTestId("screening-preview-column").className).not.toMatch(/(^| )hidden( |$)/));
  });
});
