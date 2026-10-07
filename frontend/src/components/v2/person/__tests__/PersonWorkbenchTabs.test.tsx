/**
 * Pełne narzędzia osoby w rozwiniętym panelu osoby (jeden panel osoby,
 * 04.10.2026). Przeniesione przypadki z testów dawnego warsztatu
 * (`PersonPanel` + `BoardWorkbenchDrawer`): zakładka z etapu, kontekst
 * warsztatów, zamontowane zakładki, podpowiedź zamknięcia rekrutacji, „jedno
 * wejście do ruchu”. Nagłówek, wybór etapu, „Odrzuć” i pole notatki są
 * w doku (jego testy), a „Rozwiń” / Esc — w testach Tablicy.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  workbenchProps: {} as Record<string, Record<string, unknown>>,
}));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.apiGet, post: vi.fn() },
  extractErrorMsg: () => "",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

// Warsztaty mają własne testy — tu liczy się, CO panel im podaje. Pole tekstowe
// w atrapie pozwala sprawdzić, że zakładka nie jest odmontowywana.
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
vi.mock("@/components/v2/recruitment/panel-workbenches", () => ({
  ScreeningWorkbench: workbenchMock("screening"),
  CvHandoffWorkbench: workbenchMock("cv"),
}));
vi.mock("@/components/v2/jobs/JobInterviewsTab", () => ({ JobInterviewsTab: workbenchMock("interviews") }));
vi.mock("@/components/v2/jobs/JobContractTab", () => ({ JobContractTab: workbenchMock("contract") }));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({ DopasowanieTab: workbenchMock("match") }));

import {
  HeadcountFilledHint,
  PersonWorkbenchTabs,
  workbenchDefaultSection,
  workbenchSectionOwnsMove,
  type WorkbenchContext,
} from "@/components/v2/person/PersonWorkbenchTabs";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { PersonPanelSection } from "@/components/v2/recruitment/types";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

import { item, template } from "../../recruitment/__tests__/recruitment-fixtures";

const columns = template({
  1: [item(1, { name: "Ewa", lastname: "Pawlak" })],
  2: [item(2)],
  3: [item(3, { name: "Marek", lastname: "Zieliński" })],
  6: [item(4)],
  8: [item(5)],
  10: [item(6)],
});
const rowOf = (id: number, cols: KanbanColumn[] = columns) =>
  buildProcessRows(cols).find((r) => r.candidateId === id)!;

const workbenchContext: WorkbenchContext = {
  jobTitle: "Senior Java Developer",
  clientId: 9,
  clientName: "Bank Alfa",
  budgetHourly: 190,
  kanbanQueryState: { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() },
  onMoved: vi.fn(),
  canCloseJob: false,
};

function Harness({
  candidateId,
  section: initial,
  cols = columns,
  ctx = workbenchContext,
  readOnly = false,
}: {
  candidateId: number;
  section?: PersonPanelSection;
  cols?: KanbanColumn[];
  ctx?: WorkbenchContext;
  readOnly?: boolean;
}) {
  const row = rowOf(candidateId, cols);
  const [section, setSection] = useState<PersonPanelSection>(initial ?? workbenchDefaultSection(row));
  return (
    <PersonWorkbenchTabs
      row={row}
      jobId={42}
      columns={cols}
      readOnly={readOnly}
      canWriteClientRate
      workbenchContext={ctx}
      section={section}
      onSectionChange={setSection}
    />
  );
}

function renderTabs(props: Parameters<typeof Harness>[0]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.workbenchProps = {};
  mocks.apiGet.mockResolvedValue({ data: { items: [] } });
});

describe("PersonWorkbenchTabs — zakładka z etapu i kontekst warsztatów", () => {
  it.each([
    [3, "cv"],
    [4, "interviews"],
    [5, "contract"],
  ])("osoba %i otwiera zakładkę %s w układzie panelu, zawężoną do niej", (candidateId, section) => {
    renderTabs({ candidateId });
    expect(screen.getByTestId(`wb-${section}`)).toBeInTheDocument();
    expect(mocks.workbenchProps[section]).toMatchObject({
      layout: "panel",
      focusCandidateId: candidateId,
      jobId: 42,
      columns,
      readOnly: false,
    });
    // Tylko odwiedzona zakładka jest zamontowana — reszta nie strzela zapytaniami.
    expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(1);
  });

  it.each([1, 2])("osoba %i z „Nowych” i „Screeningu” otwiera formularz screeningu (0424)", (candidateId) => {
    renderTabs({ candidateId });
    expect(screen.getByTestId("wb-screening")).toBeInTheDocument();
    // Formularz screeningu nie ma już układu „full” z kolejką — bez `layout`.
    expect(mocks.workbenchProps.screening).toMatchObject({
      focusCandidateId: candidateId,
      jobId: 42,
      columns,
      readOnly: false,
    });
    expect(mocks.workbenchProps.screening).not.toHaveProperty("layout");
    expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(1);
  });

  it("formularz dostaje „Biorę — 12 h” z kontekstu Tablicy", () => {
    const onTake = vi.fn();
    renderTabs({ candidateId: 1, ctx: { ...workbenchContext, onTake } });
    expect(mocks.workbenchProps.screening.onTake).toBe(onTake);
  });

  it("etap zamknięty otwiera „Notatki i historia”", async () => {
    renderTabs({ candidateId: 6 });
    expect(screen.getByRole("tab", { name: "Notatki i historia" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Brak notatek w tej rekrutacji.")).toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/notes?candidate_id=6&job_id=42");
    // Pole nowej notatki stoi na dole panelu, nie w zakładce.
    expect(screen.queryByLabelText("Nowa notatka")).toBeNull();
  });

  it("awaria notatek nie wygląda jak „brak notatek”", async () => {
    mocks.apiGet.mockRejectedValue(new Error("500"));
    renderTabs({ candidateId: 6 });
    expect(await screen.findByText(/Nie udało się wczytać: notatki/)).toBeInTheDocument();
    expect(screen.queryByText("Brak notatek w tej rekrutacji.")).not.toBeInTheDocument();
  });

  it("zakładka z propsa wygrywa z etapem", () => {
    renderTabs({ candidateId: 3, section: "match" });
    expect(screen.getByTestId("wb-match")).toBeInTheDocument();
    expect(mocks.workbenchProps.match).toMatchObject({ candidateId: 3, defaultJobId: 42 });
    expect(screen.queryByTestId("wb-cv")).not.toBeInTheDocument();
  });

  it("warsztaty dostają kontekst strony rekrutacji; zakładka CV nie pyta o „Pracę w tle”", () => {
    renderTabs({ candidateId: 3 });
    expect(mocks.workbenchProps.cv).toMatchObject({
      jobTitle: "Senior Java Developer",
      clientId: 9,
      canWriteClientRate: true,
      budgetHourly: 190,
      isSuccess: true,
    });
    expect(mocks.apiGet).not.toHaveBeenCalledWith("/api/jobs/42/background-events", expect.anything());
  });

  it("warsztaty Screening i CV dostają podgląd tylko do odczytu na osobę spoza kolejki", () => {
    renderTabs({ candidateId: 4, section: "cv" });
    expect(mocks.workbenchProps.cv.panelFallback).toBeTruthy();
    renderTabs({ candidateId: 4, section: "screening" });
    expect(mocks.workbenchProps.screening.panelFallback).toBeTruthy();
  });
});

describe("PersonWorkbenchTabs — wpisany tekst nie ginie", () => {
  it("odwiedzone zakładki zostają zamontowane przy przełączaniu", async () => {
    renderTabs({ candidateId: 3 });
    await userEvent.type(screen.getByLabelText("pole cv"), "215 zł/h");
    await userEvent.click(screen.getByRole("tab", { name: "Dopasowanie" }));
    await userEvent.type(screen.getByLabelText("pole match"), "uwaga");
    await userEvent.click(screen.getByRole("tab", { name: "CV" }));
    expect(screen.getByLabelText("pole cv")).toHaveValue("215 zł/h");
    await userEvent.click(screen.getByRole("tab", { name: "Dopasowanie" }));
    expect(screen.getByLabelText("pole match")).toHaveValue("uwaga");
    expect(screen.getAllByRole("tabpanel").filter((p) => !p.hasAttribute("hidden"))).toHaveLength(1);
  });

  it("odświeżenie tablicy (nowy obiekt wiersza) nie odmontowuje zakładki", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = (row: ReturnType<typeof rowOf>) => (
      <QueryClientProvider client={client}>
        <PersonWorkbenchTabs
          row={row}
          jobId={42}
          columns={columns}
          readOnly={false}
          canWriteClientRate
          workbenchContext={workbenchContext}
          section="cv"
          onSectionChange={vi.fn()}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(view(rowOf(3)));
    await userEvent.type(screen.getByLabelText("pole cv"), "w trakcie");
    rerender(view(buildProcessRows(columns).find((r) => r.candidateId === 3)!));
    expect(screen.getByLabelText("pole cv")).toHaveValue("w trakcie");
  });
});

describe("workbenchSectionOwnsMove — jedno wejście do ruchu", () => {
  const owns = (candidateId: number, section: PersonPanelSection, readOnly = false) =>
    workbenchSectionOwnsMove({ row: rowOf(candidateId), section, columns, readOnly, budgetHourly: 190 });

  it("CV na „Zweryfikowanym” i screening w „Nowych” mają własny ruch", () => {
    expect(owns(3, "cv")).toBe(true);
    expect(owns(1, "screening")).toBe(true);
    expect(owns(2, "screening")).toBe(true);
  });

  it("inna zakładka, osoba u klienta albo tryb odczytu — ogólny ruch zostaje", () => {
    expect(owns(3, "notes")).toBe(false);
    expect(owns(4, "cv")).toBe(false);
    expect(owns(3, "cv", true)).toBe(false);
    // Od „Zweryfikowany” formularz zapisuje, ale ruch zostaje w ramce doku.
    expect(owns(3, "screening")).toBe(false);
  });
});

describe("zakładka „Umowa” — podpowiedź „Obsada kompletna”", () => {
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
      await userEvent.click(button);
      expect(onRequestCloseJob).toHaveBeenCalledTimes(1);
    },
  );

  it("obsada nieznana i nikt nie jest zatrudniony: podpowiedzi nie ma", () => {
    render(
      <HeadcountFilledHint columns={template({ 6: [item(11)] })} headcount={null} enabled onRequestCloseJob={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /zamknij rekrutację/ })).toBeNull();
  });

  it("zakładka podaje podpowiedzi kontekst strony; sama akcja zamknięcia nie mieszka w panelu", async () => {
    const onRequestCloseJob = vi.fn();
    const cols = template({ 9: [item(21, { name: "Hanna", lastname: "Zatrudniona" })] });
    renderTabs({
      candidateId: 21,
      cols,
      section: "contract",
      ctx: { ...workbenchContext, canCloseJob: true, headcount: 1, onRequestCloseJob },
    });
    await userEvent.click(await screen.findByRole("button", { name: /Obsada kompletna — zamknij rekrutację/ }));
    expect(onRequestCloseJob).toHaveBeenCalledTimes(1);
    expect(mocks.workbenchProps.contract.hideCloseJob).toBe(true);
  });
});
