import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  candidateGet: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  workbenchProps: {} as Record<string, Record<string, unknown>>,
}));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.apiGet, post: mocks.apiPost },
  candidatesApi: { get: mocks.candidateGet },
  extractErrorMsg: () => "",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

// Warsztaty mają własne testy — tu liczy się, CO panel im podaje. Pole tekstowe
// w atrapie pozwala sprawdzić, że sekcja nie jest odmontowywana.
function workbenchMock(name: string) {
  function WorkbenchMock(props: Record<string, unknown>) {
    mocks.workbenchProps[name] = props;
    return (
      <div data-testid={`wb-${name}`}>
        <input aria-label={`pole ${name}`} defaultValue="" />
      </div>
    );
  }
  return WorkbenchMock;
}
// Ciężkie warsztaty stoją za `next/dynamic` (`panel-workbenches`) — atrapa
// modułu-granicy, nie samych warsztatów, żeby sekcja renderowała się od razu.
vi.mock("@/components/v2/recruitment/panel-workbenches", () => ({
  ScreeningWorkbench: workbenchMock("screening"),
  CvHandoffWorkbench: workbenchMock("cv"),
}));
vi.mock("@/components/v2/jobs/JobInterviewsTab", () => ({ JobInterviewsTab: workbenchMock("interviews") }));
vi.mock("@/components/v2/jobs/JobContractTab", () => ({ JobContractTab: workbenchMock("contract") }));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({ DopasowanieTab: workbenchMock("match") }));

import {
  HeadcountFilledHint,
  PersonPanel,
  type PersonPanelProps,
} from "@/components/v2/recruitment/PersonPanel";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { PipelineMoveControls } from "@/hooks/usePipelineMove";

import { item, template } from "./recruitment-fixtures";

const columns = template({
  1: [item(1, { name: "Ewa", lastname: "Pawlak" })],
  2: [item(2)],
  3: [item(3, { name: "Marek", lastname: "Zieliński" })],
  6: [item(4)],
  8: [item(5)],
  10: [item(6)],
});
const rows = buildProcessRows(columns);
const rowOf = (id: number) => rows.find((r) => r.candidateId === id)!;

function moveControls(): PipelineMoveControls {
  return {
    requestMove: vi.fn(),
    requestBulkMove: vi.fn(),
    requestReject: vi.fn(),
    isMoving: false,
    dialogs: null,
  };
}

const workbenchContext: PersonPanelProps["workbenchContext"] = {
  jobTitle: "Senior Java Developer",
  clientId: 9,
  clientName: "Bank Alfa",
  budgetHourly: 190,
  kanbanQueryState: { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() },
  onMoved: vi.fn(),
  canCloseJob: false,
};

function Harness(props: Partial<PersonPanelProps> & { candidateId: number }) {
  const { candidateId, ...rest } = props;
  return (
    <PersonPanel
      row={rowOf(candidateId)}
      jobId={42}
      columns={columns}
      move={moveControls()}
      readOnly={false}
      canWriteClientRate
      workbenchContext={workbenchContext}
      {...rest}
    />
  );
}

function renderPanel(props: Partial<PersonPanelProps> & { candidateId: number }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
  return {
    ...utils,
    rerenderPanel: (next: Partial<PersonPanelProps> & { candidateId: number }) =>
      utils.rerender(
        <QueryClientProvider client={client}>
          <Harness {...next} />
        </QueryClientProvider>,
      ),
  };
}

const visiblePanel = () =>
  screen.getAllByRole("tabpanel").filter((panel) => !panel.hasAttribute("hidden"));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.workbenchProps = {};
  mocks.apiGet.mockResolvedValue({ data: { items: [] } });
  mocks.apiPost.mockResolvedValue({ data: {} });
  mocks.candidateGet.mockResolvedValue({ data: { linkedin_current_title: "Java Developer", city: "Warszawa" } });
});

describe("PersonPanel — sekcja domyślna z etapu", () => {
  it.each([
    [2, "screening"],
    [3, "cv"],
    [4, "interviews"],
    [5, "contract"],
  ])("osoba %i otwiera sekcję %s w układzie panelu, zawężoną do niej", (candidateId, section) => {
    renderPanel({ candidateId });
    expect(screen.getByTestId(`wb-${section}`)).toBeInTheDocument();
    expect(mocks.workbenchProps[section]).toMatchObject({
      layout: "panel",
      focusCandidateId: candidateId,
      jobId: 42,
      columns,
      readOnly: false,
    });
    // Tylko odwiedzona sekcja jest zamontowana — reszta nie strzela zapytaniami.
    expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(1);
  });

  it("sekcja CV mówi, dlaczego automat NIE przygotował CV tej osoby — po polsku, z „Pracy w tle”", async () => {
    const events = (items: unknown[]) =>
      mocks.apiGet.mockImplementation((url: string) =>
        Promise.resolve({ data: url.endsWith("/background-events") ? { job_id: 42, items, limit: 30 } : { items: [] } }),
      );
    events([
      { id: 9, kind: "cv_auto_generate_skipped", created_at: "2026-09-21T08:00:00Z", reason: "consent_screenshot_required", candidate: { id: 3, name: "Marek Zieliński" } },
      { id: 8, kind: "cv_auto_generate_skipped", created_at: "2026-09-21T07:00:00Z", reason: "no_cv_document", candidate: { id: 2, name: null } },
    ]);
    const first = renderPanel({ candidateId: 3 });
    expect(await screen.findByTestId("auto-cv-skip-notice")).toHaveTextContent(
      "CV nie zostało wygenerowane automatycznie: reguła klienta wymaga zrzutu zgody RODO.",
    );
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/jobs/42/background-events", { params: { limit: 30 } });
    first.unmount();

    // Późniejsza udana generacja gasi stary powód.
    events([
      { id: 10, kind: "cv_auto_generate", created_at: "2026-09-21T09:00:00Z", candidate: { id: 3, name: null }, generated_id: 1, document_status: "ready" },
      { id: 9, kind: "cv_auto_generate_skipped", created_at: "2026-09-21T08:00:00Z", reason: "consent_screenshot_required", candidate: { id: 3, name: null } },
    ]);
    renderPanel({ candidateId: 3 });
    await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith("/api/jobs/42/background-events", expect.anything()));
    await waitFor(() => expect(screen.queryByTestId("auto-cv-skip-notice")).not.toBeInTheDocument());
  });

  it("etap wejściowy i zamknięty otwierają „Notatki i historia”", async () => {
    renderPanel({ candidateId: 1 });
    expect(screen.getByRole("tab", { name: "Notatki i historia" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Brak notatek w tej rekrutacji.")).toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/notes?candidate_id=1&job_id=42");
  });

  it("sekcja z propsa wygrywa z etapem", () => {
    renderPanel({ candidateId: 3, section: "match" });
    expect(screen.getByTestId("wb-match")).toBeInTheDocument();
    expect(mocks.workbenchProps.match).toMatchObject({ candidateId: 3, defaultJobId: 42 });
    expect(screen.queryByTestId("wb-cv")).not.toBeInTheDocument();
  });

  it("warsztaty dostają kontekst strony rekrutacji", () => {
    renderPanel({ candidateId: 3 });
    expect(mocks.workbenchProps.cv).toMatchObject({
      jobTitle: "Senior Java Developer",
      clientId: 9,
      canWriteClientRate: true,
      budgetHourly: 190,
      isSuccess: true,
    });
  });
});

describe("PersonPanel — nagłówek i ruch etapu", () => {
  it("nagłówek: nazwisko, podtytuł z profilu, link do pełnego profilu z powrotem do rekrutacji", async () => {
    renderPanel({ candidateId: 3 });
    expect(screen.getByText("Marek Zieliński")).toBeInTheDocument();
    expect(await screen.findByText(/Java Developer · Warszawa/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pełny profil" })).toHaveAttribute(
      "href",
      "/candidates/3?from=job&jobId=42",
    );
  });

  it("główny przycisk prowadzi na pierwszy etap po bieżącym — przez usePipelineMove", async () => {
    const move = moveControls();
    renderPanel({ candidateId: 3, move, section: "notes" });
    await userEvent.click(screen.getByRole("button", { name: "Przenieś na etap: Wysłać do Cpro" }));
    expect(move.requestMove).toHaveBeenCalledWith(rowOf(3).item, rowOf(3).column, columns[3]);
  });

  it("sekcja z własnym przyciskiem ruchu (Screening, CV) chowa ogólny „Przenieś na etap”", async () => {
    // Zweryfikowany + sekcja CV: warsztat ma „Oznacz CV Wysłane” — jedno wejście do ruchu.
    const { rerenderPanel } = renderPanel({ candidateId: 3 });
    expect(screen.queryByRole("button", { name: /Przenieś na etap/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Etap")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odrzuć" })).toBeInTheDocument();
    // Ta sama osoba, inna sekcja — ogólny przycisk wraca.
    rerenderPanel({ candidateId: 3, section: "notes" });
    expect(screen.getByRole("button", { name: /Przenieś na etap/ })).toBeInTheDocument();
    // Screening na etapie „Screening” — tak samo.
    rerenderPanel({ candidateId: 2 });
    expect(screen.queryByRole("button", { name: /Przenieś na etap/ })).not.toBeInTheDocument();
    // Osoba u klienta otwiera sekcję CV tylko do odczytu — warsztat nie ma tam ruchu.
    rerenderPanel({ candidateId: 4, section: "cv" });
    expect(screen.getByRole("button", { name: /Przenieś na etap/ })).toBeInTheDocument();
  });

  it("warsztaty Screening i CV dostają podgląd tylko do odczytu na osobę spoza kolejki", () => {
    renderPanel({ candidateId: 4, section: "cv" });
    expect(mocks.workbenchProps.cv.panelFallback).toBeTruthy();
    renderPanel({ candidateId: 4, section: "screening" });
    expect(mocks.workbenchProps.screening.panelFallback).toBeTruthy();
  });

  it("wybór etapu i „Odrzuć” idą przez usePipelineMove; select oferuje też etapy końcowe", async () => {
    const move = moveControls();
    renderPanel({ candidateId: 3, move });
    const select = screen.getByLabelText("Etap");
    expect(select).toHaveValue("def:3");
    // „Odrzucony” w selekcie = to samo okno powodu co upuszczenie karty na kolumnę.
    await userEvent.selectOptions(select, "Odrzucony");
    expect(move.requestMove).toHaveBeenLastCalledWith(rowOf(3).item, rowOf(3).column, columns[9]);
    await userEvent.selectOptions(select, "CV Wysłane");
    expect(move.requestMove).toHaveBeenCalledWith(rowOf(3).item, rowOf(3).column, columns[4]);
    // Kontrolowany etapem z wiersza: anulowane okno ruchu nie zostawia złej wartości.
    expect(select).toHaveValue("def:3");
    await userEvent.click(screen.getByRole("button", { name: "Odrzuć" }));
    expect(move.requestReject).toHaveBeenCalledWith(rowOf(3).item);
  });

  it("tylko do odczytu: ruch wyłączony z powodem, notatki bez pola", async () => {
    renderPanel({ candidateId: 1, readOnly: true });
    expect(screen.getByLabelText("Etap")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Odrzuć" })).toBeDisabled();
    const forward = screen.getByRole("button", { name: "Przenieś na kolejny etap" });
    expect(forward).toBeDisabled();
    expect(screen.getAllByText(/Tylko do odczytu/).length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Nowa notatka")).not.toBeInTheDocument();
  });

  it("osoba odrzucona: bieżący etap jest opcją selecta, bez „Odrzuć” i bez ruchu naprzód", () => {
    renderPanel({ candidateId: 6 });
    expect(screen.getByLabelText("Etap")).toHaveValue("def:10");
    expect(screen.queryByRole("button", { name: "Odrzuć" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Przenieś na/ })).not.toBeInTheDocument();
  });
});

describe("PersonPanel — wpisany tekst nie ginie", () => {
  it("odwiedzone sekcje zostają zamontowane przy przełączaniu i przy przerysowaniu tabeli", async () => {
    const { rerenderPanel } = renderPanel({ candidateId: 3 });
    await userEvent.type(screen.getByLabelText("pole cv"), "215 zł/h");
    await userEvent.click(screen.getByRole("tab", { name: "Notatki i historia" }));
    await userEvent.type(screen.getByLabelText("Nowa notatka"), "Oddzwonić jutro");
    expect(visiblePanel()).toHaveLength(1);

    // Tabela przerysowuje się co odświeżenie tablicy — NOWY obiekt wiersza.
    const fresh = buildProcessRows(columns).find((r) => r.candidateId === 3)!;
    rerenderPanel({ candidateId: 3, row: fresh });

    expect(screen.getByLabelText("Nowa notatka")).toHaveValue("Oddzwonić jutro");
    await userEvent.click(screen.getByRole("tab", { name: "CV" }));
    expect(screen.getByLabelText("pole cv")).toHaveValue("215 zł/h");
  });

  it("zmiana osoby zaczyna od sekcji JEJ etapu i czyści poprzednie sekcje", async () => {
    const { rerenderPanel } = renderPanel({ candidateId: 3 });
    await userEvent.click(screen.getByRole("tab", { name: "Dopasowanie" }));
    rerenderPanel({ candidateId: 2 });
    expect(screen.getByTestId("wb-screening")).toBeInTheDocument();
    expect(screen.queryByTestId("wb-match")).not.toBeInTheDocument();
    expect(screen.queryByTestId("wb-cv")).not.toBeInTheDocument();
  });

  it("nieudany zapis notatki zostawia tekst w polu", async () => {
    mocks.apiPost.mockRejectedValue(new Error("500"));
    renderPanel({ candidateId: 1 });
    const field = await screen.findByLabelText("Nowa notatka");
    await userEvent.type(field, "Ważna notatka");
    await userEvent.click(screen.getByRole("button", { name: "Dodaj notatkę" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalled());
    expect(field).toHaveValue("Ważna notatka");
  });

  it("udany zapis idzie na trasę notatek z rekrutacją i czyści pole", async () => {
    renderPanel({ candidateId: 1 });
    const field = await screen.findByLabelText("Nowa notatka");
    await userEvent.type(field, "Dostępny od razu");
    await userEvent.click(screen.getByRole("button", { name: "Dodaj notatkę" }));
    await waitFor(() =>
      expect(mocks.apiPost).toHaveBeenCalledWith("/api/notes", {
        candidate_id: 1,
        job_id: 42,
        content: "Dostępny od razu",
        note_type: "general",
      }),
    );
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("awaria notatek nie wygląda jak „brak notatek”", async () => {
    mocks.apiGet.mockRejectedValue(new Error("500"));
    renderPanel({ candidateId: 1 });
    expect(await screen.findByText(/Nie udało się wczytać notatek/)).toBeInTheDocument();
    expect(screen.queryByText("Brak notatek w tej rekrutacji.")).not.toBeInTheDocument();
  });
});

describe("PersonPanel — tryb szeroki", () => {
  it("„Rozwiń” otwiera nakładkę z TĄ SAMĄ treścią (tekst zostaje), Esc ją zamyka", async () => {
    renderPanel({ candidateId: 3 });
    await userEvent.type(screen.getByLabelText("pole cv"), "w trakcie");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Rozwiń" }));
    const dialog = await screen.findByRole("dialog");
    // Treść przeniesiona do nakładki, nie wyrenderowana drugi raz.
    expect(within(dialog).getByLabelText("pole cv")).toHaveValue("w trakcie");
    expect(screen.getAllByLabelText("pole cv")).toHaveLength(1);
    expect(screen.getByText(/otwarty w szerokim widoku/)).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByLabelText("pole cv")).toHaveValue("w trakcie");
    expect(screen.getByRole("button", { name: "Rozwiń" })).toBeInTheDocument();
  });

  it("zgłasza zmianę trybu rodzicowi", async () => {
    const onWideChange = vi.fn();
    renderPanel({ candidateId: 3, onWideChange });
    await userEvent.click(screen.getByRole("button", { name: "Rozwiń" }));
    expect(onWideChange).toHaveBeenCalledWith(true);
  });
});

describe("PersonPanel — skróty z tabeli", () => {
  it("sygnał „N” przełącza na notatki i ustawia fokus w polu; nie kradnie fokusu następnej osobie", async () => {
    const { rerenderPanel } = renderPanel({ candidateId: 3, noteFocusSignal: 0 });
    rerenderPanel({ candidateId: 3, noteFocusSignal: 1 });
    const field = await screen.findByLabelText("Nowa notatka");
    await waitFor(() => expect(field).toHaveFocus());

    // Kolejna osoba (strzałka w dół) z TYM SAMYM, starym sygnałem.
    rerenderPanel({ candidateId: 1, noteFocusSignal: 1 });
    const next = await screen.findByLabelText("Nowa notatka");
    expect(next).not.toHaveFocus();
  });

  it("sygnał „E” ustawia fokus na wyborze etapu", async () => {
    const { rerenderPanel } = renderPanel({ candidateId: 3, stageFocusSignal: 0 });
    rerenderPanel({ candidateId: 3, stageFocusSignal: 1 });
    await waitFor(() => expect(screen.getByLabelText("Etap")).toHaveFocus());
  });
});

describe("sekcja „Umowa” — podpowiedź „Obsada kompletna”", () => {
  const hiredColumns = template({ 9: [item(11), item(12)] });

  it("komplet obsady po zatrudnieniu: podpowiedź otwiera okno „Zlecenie” na zamknięciu rekrutacji", async () => {
    const onRequestCloseJob = vi.fn();
    render(
      <HeadcountFilledHint columns={hiredColumns} headcount={2} enabled onRequestCloseJob={onRequestCloseJob} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Obsada kompletna — zamknij rekrutację/ }));
    expect(onRequestCloseJob).toHaveBeenCalledTimes(1);
    expect(screen.getByText("2 z 2")).toBeInTheDocument();
  });

  it.each([
    ["obsada niepełna", { headcount: 3, enabled: true }],
    ["rola bez `job.update` / tryb odczytu / rekrutacja zamknięta", { headcount: 2, enabled: false }],
  ])("nie pokazuje się: %s", (_name, over) => {
    render(<HeadcountFilledHint columns={hiredColumns} onRequestCloseJob={vi.fn()} {...over} />);
    expect(screen.queryByRole("button", { name: /zamknij rekrutację/ })).toBeNull();
  });

  it.each([[null], [0]])(
    "obsada nieznana (%s): każde zatrudnienie podpowiada zamknięcie, bez twierdzenia o komplecie",
    async (headcount) => {
      const onRequestCloseJob = vi.fn();
      render(
        <HeadcountFilledHint
          columns={template({ 9: [item(11)] })}
          headcount={headcount}
          enabled
          onRequestCloseJob={onRequestCloseJob}
        />,
      );
      const button = screen.getByRole("button", {
        name: "Jest zatrudnienie — zamknij rekrutację, jeśli obsada jest kompletna",
      });
      expect(button).not.toHaveTextContent(/ z /);
      expect(screen.queryByText(/Obsada kompletna/)).toBeNull();
      await userEvent.click(button);
      expect(onRequestCloseJob).toHaveBeenCalledTimes(1);
    },
  );

  it("obsada nieznana i nikt nie jest zatrudniony: podpowiedzi nie ma", () => {
    render(
      <HeadcountFilledHint
        columns={template({ 6: [item(11)] })}
        headcount={null}
        enabled
        onRequestCloseJob={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /zamknij rekrutację/ })).toBeNull();
  });

  it("panel podaje podpowiedzi kontekst strony: obsadę, bramkę `job.update` i akcję", async () => {
    const onRequestCloseJob = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const cols = template({ 9: [item(21, { name: "Hanna", lastname: "Zatrudniona" })] });
    const row = buildProcessRows(cols).find((r) => r.candidateId === 21)!;
    render(
      <QueryClientProvider client={client}>
        <PersonPanel
          row={row}
          jobId={42}
          columns={cols}
          move={moveControls()}
          readOnly={false}
          canWriteClientRate
          section="contract"
          workbenchContext={{ ...workbenchContext, canCloseJob: true, headcount: 1, onRequestCloseJob }}
        />
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Obsada kompletna — zamknij rekrutację/ }));
    expect(onRequestCloseJob).toHaveBeenCalledTimes(1);
    // Sama akcja zamknięcia nadal NIE mieszka w panelu jednej osoby.
    expect(mocks.workbenchProps.contract.hideCloseJob).toBe(true);
  });
});
