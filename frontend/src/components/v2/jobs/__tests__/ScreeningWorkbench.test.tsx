/**
 * ScreeningWorkbench — sekcja „Screening” panelu osoby (0424, 07.10.2026).
 *
 * Gospodarz decyduje, CO stoi po lewej (blok „Co już wiemy” i formularz,
 * historia zakończonego procesu) i z jakimi ruchami, a obok zawsze podgląd
 * CV/wymagań. Sam formularz i podgląd mają własne testy — tu są stubami,
 * które mówią, jakie propsy dostały. Od 14.10.2026 (P2) bez kroku „Zacznij
 * screening”: formularz stoi od razu także w „Nowych”.
 */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

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
    onForwarded?: () => void;
    noteFill?: unknown;
  }) => (
    <div data-testid="full-form">
      <span>formularz kandydata {props.candidateId}</span>
      <span>{props.forward ? `dalej: ${props.forward.label} (${props.forward.stageDefId})` : "bez ruchu dalej"}</span>
      <span>{props.reject ? `odrzuć: ${props.reject.stage} z ${props.reject.previousStage}` : "bez odrzucenia"}</span>
      <span>{props.readOnly ? "tylko odczyt" : "edycja"}</span>
      <span>{props.noteFill ? "z kanałem notatki" : "bez kanału notatki"}</span>
      {props.onForwarded ? (
        <button type="button" onClick={props.onForwarded}>
          przekazano dalej
        </button>
      ) : null}
      {props.banner}
    </div>
  ),
}));

vi.mock("@/components/v2/screening-form/BeforeCallProfile", () => ({
  BeforeCallProfile: (props: { readOnly: boolean; onOpenHistory?: () => void }) => (
    <div data-testid="before-call">
      <button type="button" onClick={props.onOpenHistory}>
        Pokaż wcześniejsze notatki
      </button>
    </div>
  ),
}));

vi.mock("@/components/v2/screening-form/CandidatePreviewPane", () => ({
  CandidatePreviewPane: (props: {
    tab: string;
    stageId: number | null;
    onTabChange: (tab: string) => void;
    historyOpen?: boolean;
    onHistoryOpenChange?: (open: boolean) => void;
  }) => (
    <div data-testid="preview-pane">
      podgląd: {props.tab} · etap {props.stageId}
      {props.historyOpen ? " · historia osoby" : ""}
      <button type="button" onClick={() => props.onTabChange("plain")}>
        Po ludzku
      </button>
      <button type="button" onClick={() => props.onHistoryOpenChange?.(false)}>
        Zamknij historię
      </button>
    </div>
  ),
}));

vi.mock("@/components/v2/screening-form/ScreeningFormHistory", () => ({
  ScreeningFormHistory: (props: { canRestore: boolean }) => (
    <div data-testid="form-history">{props.canRestore ? "z przywracaniem" : "bez przywracania"}</div>
  ),
}));

vi.mock("@/components/v2/screening-form/JointScreeningPicker", () => ({
  JointScreeningPicker: (props: { pairs: unknown[]; selected: ReadonlySet<number> }) =>
    props.pairs.length ? <div data-testid="joint-picker">wybrane: {[...props.selected].join(",")}</div> : null,
}));

vi.mock("@/components/v2/screening-form/JointScreeningForm", () => ({
  JointScreeningForm: (props: { others: Array<{ job_id: number }>; onSessionChange?: (active: boolean) => void }) => (
    <div data-testid="joint-form">
      wspólny z: {props.others.map((p) => p.job_id).join(",")}
      <button type="button" onClick={() => props.onSessionChange?.(true)}>
        zapis ruszył
      </button>
      <button type="button" onClick={() => props.onSessionChange?.(false)}>
        zamknij wynik
      </button>
    </div>
  ),
}));

import { ScreeningWorkbench } from "@/components/v2/jobs/ScreeningWorkbench";
import { useJointScreeningIntent } from "@/store/joint-screening";
import { createNoteFillChannel } from "@/lib/note-fill-channel";
import { PersonPanelSideProvider, PersonPanelSideZone } from "@/components/v2/person/PersonPanelSide";
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
  it("„Nowi” bez zapisanego formularza: od razu formularz, nad nim „Co już wiemy”, CV obok (P2, 14.10.2026)", async () => {
    renderWorkbench();
    const form = await screen.findByTestId("full-form");
    expect(form).toHaveTextContent("dalej: Zweryfikowany (4)");
    expect(form).toHaveTextContent("odrzuć: rejected z new");
    const known = screen.getByTestId("before-call");
    expect(Boolean(known.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(await screen.findByTestId("preview-pane")).toHaveTextContent("podgląd: cv · etap 11");
    // Bez kroku „Zacznij screening” i bez „Biorę — 12 h” — pierwszy zapis bierze osobę sam.
    expect(screen.queryByRole("button", { name: /Zacznij screening/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Biorę/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Profil przed telefonem/ })).toBeNull();
  });

  it("udane „Zapisz i przekaż dalej” mówi panelowi, kogo przekazano; kanał notatki idzie do formularza", async () => {
    const user = userEvent.setup();
    const onForwarded = vi.fn();
    const noteFill = createNoteFillChannel();
    renderWorkbench({ onForwarded, noteFill });
    const form = await screen.findByTestId("full-form");
    expect(form).toHaveTextContent("z kanałem notatki");
    await user.click(within(form).getByRole("button", { name: "przekazano dalej" }));
    expect(onForwarded).toHaveBeenCalledWith(111);
  });

  it("„Pokaż” przy wcześniejszych notatkach otwiera historię osoby w podglądzie, na zakładce CV", async () => {
    const user = userEvent.setup();
    renderWorkbench();
    await screen.findByTestId("before-call");
    // Rekruter jest na innej zakładce podglądu — historia stoi w „CV”.
    await user.click(await screen.findByRole("button", { name: "Po ludzku" }));
    expect(screen.getByTestId("preview-pane")).toHaveTextContent("podgląd: plain");
    expect(screen.getByTestId("preview-pane")).not.toHaveTextContent("historia osoby");

    // W wąskim oknie (test: bez strefy panelu) podgląd jest schowany pod przyciskiem.
    expect(screen.getByTestId("screening-preview-column").className).toContain("hidden");

    await user.click(screen.getByRole("button", { name: "Pokaż wcześniejsze notatki" }));
    expect(screen.getByTestId("preview-pane")).toHaveTextContent("podgląd: cv");
    expect(screen.getByTestId("preview-pane")).toHaveTextContent("historia osoby");
    // „Pokaż” odsłania też sam podgląd — inaczej klik wyglądałby na pusty.
    expect(screen.getByTestId("screening-preview-column").className).not.toMatch(/(^| )hidden( |$)/);

    // Podgląd oddaje stan gospodarzowi (wybór źródła CV, „Szukaj w CV”).
    await user.click(screen.getByRole("button", { name: "Zamknij historię" }));
    expect(screen.getByTestId("preview-pane")).not.toHaveTextContent("historia osoby");
  });

  it("„Screening”: formularz z wymaganiami obok, nad nim „Co już wiemy”", async () => {
    renderWorkbench({ focusCandidateId: 112 });
    expect(await screen.findByTestId("full-form")).toHaveTextContent("formularz kandydata 112");
    expect(screen.getByTestId("full-form")).toHaveTextContent("odrzuć: rejected z screening");
    expect(screen.getByTestId("before-call")).toBeInTheDocument();
    expect(await screen.findByTestId("preview-pane")).toHaveTextContent("podgląd: requirements · etap 12");
  });

  it("„Nowi” z zapisanym formularzem: ten sam układ, podgląd dalej od CV", async () => {
    states.set(111, formState({ candidate_id: 111, job_id: 7, stage_id: 11, version: 1, versions_count: 1 }));
    renderWorkbench();
    expect(await screen.findByTestId("full-form")).toBeInTheDocument();
    expect(screen.getByTestId("before-call")).toBeInTheDocument();
    expect(await screen.findByTestId("preview-pane")).toHaveTextContent("podgląd: cv");
  });

  it("po „CV wysłane”: formularz z banerem D8, bez ruchu dalej, odrzucenia i bloku „Co już wiemy”", async () => {
    renderWorkbench({ focusCandidateId: 113 });
    const form = await screen.findByTestId("full-form");
    expect(screen.queryByTestId("before-call")).toBeNull();
    expect(form).toHaveTextContent("bez ruchu dalej");
    expect(form).toHaveTextContent("bez odrzucenia");
    expect(await screen.findByTestId("screening-after-cv-sent")).toHaveTextContent(
      "trafi do następnego CV firmowego",
    );
  });

  it("proces zakończony: jeden widok „Screening” tylko do odczytu i historia bez przywracania", async () => {
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
        sheet: { answers: [{ question_id: "q1", response: "6 lat", deal_breaker_hit: false }], overall_fit: "fit", notes: "" },
        questions: [
          {
            number: 1,
            question: "Ile lat pracujesz z Javą?",
            answer: "6 lat",
            source: "sheet",
            question_id: "q1",
            deal_breaker: "Poniżej 2 lat",
            deal_breaker_hit: false,
          },
          {
            number: 2,
            question: "Czy pracowałeś z Kafką?",
            answer: "Tak, 3 projekty",
            source: "note",
            question_id: "q2",
            deal_breaker: null,
            deal_breaker_hit: false,
          },
        ],
      }),
    );
    renderWorkbench({ focusCandidateId: 112, panelFallback: <p>Widok zapasowy</p> });
    const ended = await screen.findByTestId("screening-ended");
    expect(within(ended).getByTestId("screening-form-readonly")).toHaveTextContent("Proces zakończony.");
    // Warunki, odpowiedzi (z arkusza i z notatki) i „Odpada, gdy…” w jednym widoku.
    expect(ended).toHaveTextContent("Pasuje");
    expect(ended).toHaveTextContent("6 lat");
    expect(ended).toHaveTextContent("odpowiedź z notatki");
    expect(ended).toHaveTextContent("Odpada, gdy: Poniżej 2 lat");
    // 09.10.2026: bez osobnej „Karty rekomendacji” i bez drugiego widoku arkusza.
    expect(screen.queryByText("Karta rekomendacji")).toBeNull();
    expect(screen.queryByText("Widok zapasowy")).toBeNull();
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
  it("w szerokim oknie podgląd stoi w lewej strefie panelu osoby, bez przycisku", async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    try {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={client}>
          <PersonPanelSideProvider>
            <PersonPanelSideZone />
            <div data-testid="dock-column">
              <ScreeningWorkbench
                jobId={7}
                jobBudgetHourly={100}
                columns={board()}
                isLoading={false}
                isError={false}
                error={null}
                isSuccess
                onRetry={vi.fn()}
                onMoved={vi.fn()}
                readOnly={false}
                onTabChange={vi.fn()}
                focusCandidateId={112}
              />
            </div>
          </PersonPanelSideProvider>
        </QueryClientProvider>,
      );
      await screen.findByTestId("full-form");
      const zone = screen.getByTestId("person-panel-side");
      expect(await within(zone).findByTestId("preview-pane")).toHaveTextContent("podgląd: requirements");
      expect(within(screen.getByTestId("dock-column")).queryByTestId("preview-pane")).toBeNull();
      expect(screen.queryByRole("button", { name: "Pokaż CV i wymagania" })).toBeNull();
      expect(screen.queryByTestId("screening-preview-column")).toBeNull();
    } finally {
      window.matchMedia = original;
    }
  });
});

describe("ScreeningWorkbench — „Screening dla” (14.10.2026)", () => {
  const contextPair = (job_id: number) => ({
    job_id,
    title: `Rekrutacja ${job_id}`,
    client_id: 1,
    client_name: null,
    board_column: "new",
    process_state_version: 1,
    claim: null,
    selectable: true,
    reason: null,
    reason_message: null,
    budget_hourly: null,
    verified_stage_def_id: 5,
  });

  beforeEach(() => {
    useJointScreeningIntent.setState({ intent: null });
    mocks.get.mockImplementation((url: string, config: { params: { candidate_id: number } }) => {
      if (url === "/api/screening-form/joint-context") {
        return Promise.resolve({
          data: {
            candidate_id: 111,
            job_id: 7,
            anchor: { job_id: 7, title: "Kotwica", client_id: 1, client_name: null, budget_hourly: null },
            pairs: [201, 202, 203, 204, 205].map(contextPair),
          },
        });
      }
      if (url.includes("/also-fits")) return Promise.resolve({ data: { status: "ok", jobs: [] } });
      return Promise.resolve({ data: states.get(config.params.candidate_id) });
    });
  });

  function renderJoint() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const ui = (columns: KanbanColumn[]) => (
      <QueryClientProvider client={client}>
        <ScreeningWorkbench
          jobId={7}
          jobBudgetHourly={100}
          columns={columns}
          isLoading={false}
          isError={false}
          error={null}
          isSuccess
          onRetry={vi.fn()}
          onMoved={vi.fn()}
          readOnly={false}
          onTabChange={vi.fn()}
          onTake={vi.fn()}
          focusCandidateId={111}
        />
      </QueryClientProvider>
    );
    const view = render(ui(board()));
    return { rerender: (columns: KanbanColumn[]) => view.rerender(ui(columns)) };
  }

  it("„Screening razem” for the person already open selects at most three other recruitments", async () => {
    renderJoint();
    await screen.findByTestId("joint-picker");
    expect(screen.getByTestId("full-form")).toBeInTheDocument();
    act(() => useJointScreeningIntent.getState().setIntent(111, [201, 202, 203, 204, 205]));
    expect(await screen.findByTestId("joint-form")).toHaveTextContent("wspólny z: 201,202,203");
    // Wybór dalej można zmieniać.
    expect(screen.getByTestId("joint-picker")).toHaveTextContent("wybrane: 201,202,203");
  });

  it("keeps the joint form and its result after the anchor has moved on, until the result is closed", async () => {
    const user = userEvent.setup();
    useJointScreeningIntent.getState().setIntent(111, [201]);
    const { rerender } = renderJoint();
    await user.click(await screen.findByRole("button", { name: "zapis ruszył" }));
    // Kotwica przeszła na „Zweryfikowany” — Tablica odświeżona.
    rerender(
      board().map((col) =>
        col.stage === "new"
          ? { ...col, items: [], count: 0 }
          : col.stage === "verified"
            ? { ...col, items: [item({ stage: "verified" })], count: 1 }
            : col,
      ),
    );
    expect(screen.getByTestId("joint-form")).toHaveTextContent("wspólny z: 201");
    await user.click(screen.getByRole("button", { name: "zamknij wynik" }));
    await waitFor(() => expect(screen.queryByTestId("joint-form")).toBeNull());
  });
});

