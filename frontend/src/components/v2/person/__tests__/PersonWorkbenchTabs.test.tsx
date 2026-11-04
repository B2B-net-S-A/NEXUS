/**
 * Pełne narzędzia osoby w rozwiniętym panelu osoby (jeden panel osoby,
 * 04.10.2026). Przeniesione przypadki z testów dawnego warsztatu
 * (`PersonPanel` + `BoardWorkbenchDrawer`): zakładka z etapu, kontekst
 * warsztatów, zamontowane zakładki, podpowiedź zamknięcia rekrutacji, „jedno
 * wejście do ruchu”. Nagłówek, wybór etapu, „Odrzuć” i pole notatki są
 * w doku (jego testy), a „Rozwiń” / Esc — w testach Tablicy.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  candidateGet: vi.fn(),
  workbenchProps: {} as Record<string, Record<string, unknown>>,
}));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.apiGet, post: vi.fn() },
  candidatesApi: { get: mocks.candidateGet },
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
// Podgląd po lewej (pdf.js) ma własne testy — tu liczy się, ile egzemplarzy
// powstaje i czy przeżywają zmianę zakładki.
vi.mock("@/components/v2/person/PersonSidePreview", () => ({
  PersonSidePreview: ({ extraTab }: { extraTab?: unknown }) => (
    <div data-testid={extraTab ? "side-preview-interviews" : "side-preview-shared"}>
      <input aria-label={extraTab ? "podgląd rozmów" : "podgląd wspólny"} defaultValue="" />
    </div>
  ),
}));
vi.mock("@/components/v2/jobs/JobContractTab", () => ({ JobContractTab: workbenchMock("contract") }));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({ DopasowanieTab: workbenchMock("match") }));
// 0506: sekcja umowy przedwstępnej ma własne testy (`PreContractSection.test.tsx`).
vi.mock("@/components/v2/person/pre-contract/PreContractSection", () => ({
  PreContractSection: ({ readOnly }: { readOnly?: boolean }) => (
    <div data-testid="pre-contract-section" data-read-only={String(Boolean(readOnly))} />
  ),
}));

import {
  HeadcountFilledHint,
  PersonWorkbenchTabs,
  workbenchDefaultSection,
  workbenchSectionOwnsMove,
  type WorkbenchContext,
} from "@/components/v2/person/PersonWorkbenchTabs";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { PersonPanelSection } from "@/components/v2/recruitment/types";
import { WorkbenchBelowTabsContext } from "@/components/v2/person/WorkbenchBelowTabs";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { formatWarsawDay } from "@/lib/added-to-base";
import { useAuthStore, type UserRole } from "@/store/auth";

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
  mocks.candidateGet.mockResolvedValue({ data: {} });
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
    expect(await screen.findByText(/Jeszcze nic nie zapisano\./)).toBeInTheDocument();
    // 12.10.2026: jedno zapytanie o WSZYSTKIE notatki osoby — podział na tę
    // rekrutację i „Wcześniej u nas” liczy przeglądarka.
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/notes?candidate_id=6", expect.anything());
    expect(mocks.apiGet.mock.calls.some(([url]) => String(url).includes("job_id="))).toBe(false);
    // Pole nowej notatki stoi na dole panelu, nie w zakładce.
    expect(screen.queryByLabelText("Nowa notatka")).toBeNull();
  });

  it("awaria notatek nie wygląda jak „brak notatek”", async () => {
    mocks.apiGet.mockRejectedValue(new Error("500"));
    renderTabs({ candidateId: 6 });
    expect(await screen.findByText(/Nie udało się wczytać: notatki/)).toBeInTheDocument();
    expect(screen.queryByText(/Jeszcze nic nie zapisano/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nie ma wcześniejszych notatek/)).not.toBeInTheDocument();
  });

  it("licznik zakładki liczy notatki ludzi, a historia pokazuje prawdziwe ruchy tej osoby", async () => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.startsWith("/api/notes")) {
        return Promise.resolve({
          data: {
            items: [
              { id: 1, job_id: 42, content: "Umówiony telefon.", author_name: "Anna Kowalczyk", created_at: "2026-10-12T08:00:00Z", group: "talks", replies: [] },
              { id: 2, job_id: 7, job_title: "Analityk systemowy", content: "Feedback klienta.", author_name: "Piotr Wrona", created_at: "2025-04-02T09:40:00Z", group: "talks", replies: [] },
              { id: 3, job_id: 7, content: "Auto-match 70/100.", is_system: true, group: "automat", created_at: "2025-03-01T00:00:00Z", replies: [] },
            ],
          },
        });
      }
      if (url === "/api/pipeline/job/42/moves") {
        return Promise.resolve({
          data: {
            total: 3,
            items: [
              { id: 12, candidate_id: 6, candidate_name: null, from_stage_name: "Nowi", to_stage_name: "Screening", moved_by_name: "Anna Kowalczyk", moved_at: "2026-10-12T08:42:00Z", source: "nexus" },
              // Serwer sprzed filtra oddałby też cudze ruchy — panel ich nie pokazuje.
              { id: 13, candidate_id: 99, candidate_name: null, from_stage_name: "Screening", to_stage_name: "Zweryfikowany", moved_by_name: "Ktoś Inny", moved_at: "2026-10-12T08:41:00Z", source: "nexus" },
              { id: 11, candidate_id: 6, candidate_name: null, from_stage_name: null, to_stage_name: "Nowi", moved_by_name: null, moved_at: "2026-10-12T08:40:00Z", source: "traffit" },
            ],
          },
        });
      }
      return Promise.resolve({ data: { items: [] } });
    });
    renderTabs({ candidateId: 6 });

    // Dwie notatki ludzi (ta rekrutacja + wcześniejsza); wpis automatu się nie liczy.
    expect(await screen.findByRole("tab", { name: /Notatki i historia\s*2/ })).toBeInTheDocument();
    const history = screen.getByRole("region", { name: "Historia w rekrutacji" });
    expect(await within(history).findByText("Nowi → Screening")).toBeInTheDocument();
    expect(within(history).getByText("Dodany do rekrutacji · Nowi")).toBeInTheDocument();
    expect(within(history).getByText("import z Traffita")).toBeInTheDocument();
    expect(within(history).queryByText(/Zweryfikowany/)).toBeNull();
    expect(within(history).queryByText("Ktoś Inny")).toBeNull();
    expect(mocks.apiGet).toHaveBeenCalledWith(
      "/api/pipeline/job/42/moves",
      expect.objectContaining({ params: { candidate_id: 6, limit: 200 } }),
    );
  });

  it("„Osoba w bazie” na górze zakładki i „Dodany do bazy” na końcu historii (13.10.2026)", async () => {
    const addedAt = new Date(Date.now() - 3 * 24 * 3_600_000).toISOString();
    mocks.candidateGet.mockResolvedValue({
      data: {
        added_to_base_at: addedAt,
        added_to_base_exact: true,
        added_via: "CV upload",
        created_by_user: { id: 7, name: "Marta Nowak" },
      },
    });
    renderTabs({ candidateId: 6 });

    const block = await screen.findByTestId("person-in-base");
    expect(within(block).getByText("Osoba w bazie")).toBeInTheDocument();
    expect(await within(block).findByText(formatWarsawDay(addedAt)!)).toBeInTheDocument();
    expect(within(block).getByText("CV upload · dodał(a) Marta Nowak")).toBeInTheDocument();
    expect(mocks.candidateGet).toHaveBeenCalledWith(6);

    const history = screen.getByRole("region", { name: "Historia w rekrutacji" });
    const row = await within(history).findByTestId("history-added-to-base");
    expect(within(row).getByText("Dodany do bazy")).toBeInTheDocument();
    expect(within(row).getByText("przed tą rekrutacją")).toBeInTheDocument();
  });

  it("osoba z importu bez daty u źródła: „przed …”, bez udawanej daty", async () => {
    mocks.candidateGet.mockResolvedValue({
      data: { added_to_base_at: "2026-04-16T10:00:00Z", added_to_base_exact: false, added_via: "Traffit" },
    });
    renderTabs({ candidateId: 6 });

    const block = await screen.findByTestId("person-in-base");
    expect(await within(block).findByText("przed 16.04.2026")).toBeInTheDocument();
    expect(within(block).getByText(/dokładnej daty nie znamy/)).toBeInTheDocument();
  });

  it("bez notatek zakładka nie dostaje licznika, a bez ruchów zostają fakty z karty", async () => {
    renderTabs({ candidateId: 6 });
    expect(screen.getByRole("tab", { name: "Notatki i historia" })).toBeInTheDocument();
    const history = screen.getByRole("region", { name: "Historia w rekrutacji" });
    expect(await within(history).findByText("Dodany do rekrutacji")).toBeInTheDocument();
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

  it("Screening dostaje podgląd tylko do odczytu na osobę spoza kolejki; CV nie — warsztat sam pokazuje kartę (D3)", () => {
    renderTabs({ candidateId: 4, section: "cv" });
    expect(mocks.workbenchProps.cv.panelFallback).toBeUndefined();
    renderTabs({ candidateId: 4, section: "screening" });
    expect(mocks.workbenchProps.screening.panelFallback).toBeTruthy();
  });
});

describe("PersonWorkbenchTabs — miejsce pod paskiem zakładek (09.10.2026)", () => {
  it("treść z doku stoi między paskiem zakładek a treścią zakładki — w każdej zakładce", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <WorkbenchBelowTabsContext.Provider value={<div data-testid="below-tabs">Warunki i następny etap</div>}>
          <Harness candidateId={3} />
        </WorkbenchBelowTabsContext.Provider>
      </QueryClientProvider>,
    );
    const follows = (first: Element, second: Element) =>
      Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
    const below = screen.getByTestId("below-tabs");
    expect(follows(screen.getByRole("tablist", { name: "Narzędzia osoby" }), below)).toBe(true);
    expect(follows(below, screen.getByLabelText("pole cv"))).toBe(true);

    await userEvent.click(screen.getByRole("tab", { name: "Dopasowanie" }));
    expect(follows(screen.getByTestId("below-tabs"), screen.getByLabelText("pole match"))).toBe(true);
  });

  it("bez treści z doku pod paskiem nie ma nic dodatkowego", () => {
    renderTabs({ candidateId: 3 });
    expect(screen.queryByTestId("below-tabs")).toBeNull();
  });
});

describe("PersonWorkbenchTabs — podgląd po lewej w każdej zakładce (09.10.2026)", () => {
  it("CV, Umowa, Dopasowanie i Notatki mają JEDEN wspólny podgląd, który przeżywa zmianę zakładki", async () => {
    renderTabs({ candidateId: 3 });
    expect(screen.getAllByTestId("side-preview-shared")).toHaveLength(1);
    await userEvent.type(screen.getByLabelText("podgląd wspólny"), "strona 2");

    for (const name of ["Umowa", "Dopasowanie", "Notatki i historia", "CV"]) {
      await userEvent.click(screen.getByRole("tab", { name }));
      expect(screen.getAllByTestId("side-preview-shared")).toHaveLength(1);
      expect(screen.getByLabelText("podgląd wspólny")).toHaveValue("strona 2");
    }
  });

  it("„Screening” ma własny podgląd w warsztacie — wspólny powstaje dopiero po wejściu w inną zakładkę", async () => {
    renderTabs({ candidateId: 1 });
    expect(screen.getByRole("tab", { name: "Screening" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("side-preview-shared")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Notatki i historia" }));
    expect(screen.getAllByTestId("side-preview-shared")).toHaveLength(1);
  });

  it("„Rozmowy” zostają przy własnym podglądzie z zakładką „Pytania klienta”", async () => {
    renderTabs({ candidateId: 3 });
    await userEvent.click(screen.getByRole("tab", { name: "Rozmowy" }));
    expect(screen.getAllByTestId("side-preview-interviews")).toHaveLength(1);
    expect(screen.getAllByTestId("side-preview-shared")).toHaveLength(1);
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

describe("umowa przedwstępna w zakładce „Umowa” — kto ją widzi (audyt F54)", () => {
  function loginAs(role: UserRole) {
    useAuthStore.setState({ user: { id: 7, role, roles: [role] } } as never);
  }

  it("Viewer nie dostaje sekcji, która zawsze kończyła się „Nie udało się sprawdzić…”", () => {
    loginAs("user");
    renderTabs({ candidateId: 5, section: "contract", readOnly: true });
    expect(screen.queryByTestId("pre-contract-section")).toBeNull();
  });

  it("Finanse prowadzą przedwstępną jak rekruter (decyzja Artura 22.10.2026)", () => {
    loginAs("finance");
    renderTabs({ candidateId: 5, section: "contract" });
    expect(screen.getByTestId("pre-contract-section").dataset.readOnly).toBe("false");
  });

  it("Automatyzacje mają przyciski przedwstępnej mimo podglądu Tablicy", () => {
    loginAs("automation");
    renderTabs({ candidateId: 5, section: "contract", readOnly: true });
    expect(screen.getByTestId("pre-contract-section").dataset.readOnly).toBe("false");
  });

  it("rekruter bez zapisu w Rekrutacjach dalej tylko czyta", () => {
    loginAs("recruiter");
    renderTabs({ candidateId: 5, section: "contract", readOnly: true });
    expect(screen.getByTestId("pre-contract-section").dataset.readOnly).toBe("true");
  });
});
