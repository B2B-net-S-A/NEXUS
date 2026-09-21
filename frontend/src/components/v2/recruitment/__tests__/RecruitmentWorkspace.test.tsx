import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pipelineScores: vi.fn(),
  moveOptions: null as Record<string, unknown> | null,
  move: {
    requestMove: vi.fn(),
    requestBulkMove: vi.fn(),
    requestReject: vi.fn(),
    isMoving: false,
    dialogs: null,
  },
  panelProps: null as Record<string, unknown> | null,
  bulkCvOptions: null as Record<string, unknown> | null,
  bulkCvStart: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  matchingApi: { pipelineScores: mocks.pipelineScores },
  candidatesApi: { removeFromRecruitment: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/CandidatePipelinesWidget", () => ({
  candidatePipelinesQueryKey: (id: number) => ["candidate-pipelines", id],
}));
vi.mock("@/hooks/useCandidateContactFeature", () => ({
  useCandidateContactFeature: () => ({ enabled: false }),
}));
vi.mock("@/hooks/usePipelineMove", () => ({
  usePipelineMove: (options: Record<string, unknown>) => {
    mocks.moveOptions = options;
    return mocks.move;
  },
}));
// Zbiorcza wysyłka CV ma własne testy (pętla i okno wyniku) — tu liczy się,
// że workspace ją uruchamia dla ZAZNACZONYCH wierszy.
vi.mock("@/components/v2/recruitment/useBulkCvHandoff", () => ({
  useBulkCvHandoff: (options: Record<string, unknown>) => {
    mocks.bulkCvOptions = options;
    return { start: mocks.bulkCvStart, busy: false, dialogs: null };
  },
}));
// Panel ma własne testy — tu liczy się, KOGO i z czym workspace mu podaje.
vi.mock("@/components/v2/recruitment/PersonPanel", () => ({
  PersonPanel: (props: Record<string, unknown>) => {
    mocks.panelProps = props;
    const row = props.row as { fullName: string };
    return <aside data-testid="person-panel">{row.fullName}</aside>;
  },
}));

import {
  RecruitmentWorkspace,
  type RecruitmentWorkspaceProps,
} from "@/components/v2/recruitment/RecruitmentWorkspace";
import type { PersonPanelSection, RecruitmentSegment } from "@/components/v2/recruitment/types";

import { item, template } from "./recruitment-fixtures";

const columns = template({
  1: [item(1, { name: "Ewa", lastname: "Pawlak", days_in_stage: 9 })],
  3: [
    item(2, { name: "Marek", lastname: "Zieliński", days_in_stage: 4 }),
    item(3, { name: "Katarzyna", lastname: "Wójcik", days_in_stage: 3 }),
  ],
  5: [item(4, { name: "Natalia", lastname: "Krawczyk", days_in_stage: 2 })],
  10: [item(5, { name: "Paweł", lastname: "Król" })],
});

const okState = { isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() };

function Harness(over: Partial<RecruitmentWorkspaceProps>) {
  const [segment, setSegment] = useState<RecruitmentSegment>(over.segment ?? "in-process");
  const [active, setActive] = useState<number | null>(over.activeCandidateId ?? null);
  const [section, setSection] = useState<PersonPanelSection | null>(null);
  return (
    <RecruitmentWorkspace
      jobId={42}
      job={{ title: "Senior Java", budgetHourly: 190, rejectionReasons: [] }}
      kanban={{ columns }}
      kanbanQueryState={okState}
      canWritePipeline
      canWriteClientRate
      openProposalsCount={52}
      shortlistCount={3}
      workbenchContext={{ clientId: 9, onMoved: vi.fn(), canCloseJob: false }}
      onOpenSlideOver={vi.fn()}
      virtualize={false}
      {...over}
      segment={segment}
      onSegmentChange={(next) => {
        over.onSegmentChange?.(next);
        setSegment(next);
      }}
      activeCandidateId={active}
      onActiveCandidateChange={setActive}
      panelSection={section}
      onPanelSectionChange={setSection}
    />
  );
}

function renderWorkspace(over: Partial<RecruitmentWorkspaceProps> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness {...over} />
    </QueryClientProvider>,
  );
}

const names = () =>
  within(screen.getByRole("grid"))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("gridcell")[1]?.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  mocks.panelProps = null;
  mocks.pipelineScores.mockResolvedValue({ data: { scores: { "2": 91 } } });
});

describe("RecruitmentWorkspace — stany zapytania", () => {
  it("ładowanie: szkielet tabeli, nigdy „nikogo nie ma”", () => {
    renderWorkspace({
      kanban: undefined,
      kanbanQueryState: { ...okState, isLoading: true, isSuccess: false },
    });
    expect(screen.getByTestId("virtual-table-loading")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze nikogo/)).not.toBeInTheDocument();
  });

  it("przerwa między ponowieniami (ani loading, ani error, ani success) to nadal ładowanie", () => {
    renderWorkspace({
      kanban: undefined,
      kanbanQueryState: { ...okState, isLoading: false, isSuccess: false },
    });
    expect(screen.getByTestId("virtual-table-loading")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze nikogo/)).not.toBeInTheDocument();
  });

  it("błąd: komunikat z ponowieniem zamiast pustej tabeli", async () => {
    const refetch = vi.fn();
    renderWorkspace({
      kanban: undefined,
      kanbanQueryState: { isLoading: false, isError: true, error: new Error("500"), isSuccess: false, refetch },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się pobrać");
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(refetch).toHaveBeenCalled();
  });

  it("403 mówi o uprawnieniach, nie o pustce", () => {
    renderWorkspace({
      kanban: undefined,
      kanbanQueryState: {
        isLoading: false,
        isError: true,
        error: { response: { status: 403 } },
        isSuccess: false,
        refetch: vi.fn(),
      },
    });
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
  });

  it("pusta rekrutacja (po sukcesie): zachęta do propozycji", async () => {
    const onSegmentChange = vi.fn();
    renderWorkspace({ kanban: { columns: template() }, onSegmentChange });
    expect(screen.getByText("W tej rekrutacji nie ma jeszcze nikogo.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zobacz propozycje z bazy" }));
    expect(onSegmentChange).toHaveBeenCalledWith("proposals");
  });
});

describe("RecruitmentWorkspace — tabela", () => {
  it("domyślnie: w procesie, najpierw to, co wymaga mojego ruchu; dopasowanie z pipeline-scores", async () => {
    renderWorkspace();
    // Zweryfikowani: mój ruch. Ewa stoi na wejściu („Do przejrzenia"), Natalia
    // czeka na klienta — obie po moich, po dniach malejąco.
    expect(names()).toEqual(["Marek Zieliński", "Katarzyna Wójcik", "Ewa Pawlak", "Natalia Krawczyk"]);
    expect(await screen.findByLabelText("Dopasowanie: 91 na 100")).toBeInTheDocument();
    expect(mocks.pipelineScores).toHaveBeenCalledWith(42);
  });

  it("segment paska etapów filtruje tabelę", async () => {
    renderWorkspace();
    await userEvent.click(screen.getByRole("button", { name: /^\d+Zweryfikowani$/ }));
    expect(names()).toEqual(["Marek Zieliński", "Katarzyna Wójcik"]);
    await userEvent.click(screen.getByRole("button", { name: /Odrzuceni/ }));
    expect(names()).toEqual(["Paweł Król"]);
  });

  it("chip i tekst zawężają; pusty wynik filtrów ma własny komunikat i „Wyczyść filtry”", async () => {
    renderWorkspace();
    await userEvent.click(screen.getByRole("button", { name: /Czeka na klienta/ }));
    expect(names()).toEqual(["Natalia Krawczyk"]);
    await userEvent.type(screen.getByRole("searchbox"), "zielinski");
    expect(screen.getByText("Nikt nie pasuje do ustawionych filtrów.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Wyczyść filtry" }));
    expect(names()).toHaveLength(4);
  });

  it("przełącznik grupowania dzieli tabelę według tego, kto ma ruch", async () => {
    renderWorkspace();
    expect(
      within(screen.getByRole("grid")).queryByRole("button", { name: /Wymaga mojego ruchu/ }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Grupuj: kto ma ruch" }));
    const grid = within(screen.getByRole("grid"));
    expect(grid.getByRole("button", { name: /Wymaga mojego ruchu/ })).toHaveTextContent("2");
    expect(grid.getByRole("button", { name: /Do przejrzenia/ })).toHaveTextContent("1");
    expect(grid.getByRole("button", { name: /Czeka na klienta/ })).toHaveTextContent("1");
  });

  it("propozycje i shortlista są wstrzykiwane — bez tabeli procesu", async () => {
    renderWorkspace({
      renderProposals: () => <p>segment propozycji</p>,
      renderShortlist: () => <p>segment shortlisty</p>,
    });
    await userEvent.click(screen.getByRole("button", { name: /Propozycje z bazy/ }));
    expect(screen.getByText("segment propozycji")).toBeInTheDocument();
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Shortlista/ }));
    expect(screen.getByText("segment shortlisty")).toBeInTheDocument();
  });
});

describe("RecruitmentWorkspace — pierwsza osoba w panelu (makieta v3)", () => {
  function wideScreen(matches: boolean) {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({ matches: matches && query.includes("min-width"), media: query })),
    );
  }
  afterEach(() => vi.unstubAllGlobals());

  it("na szerokim ekranie panel od razu pokazuje pierwszą osobę z listy", async () => {
    wideScreen(true);
    renderWorkspace();
    await waitFor(() =>
      expect(screen.getByTestId("person-panel")).toHaveTextContent("Marek Zieliński"),
    );
  });

  it("na wąskim ekranie nie otwiera niczego sam", () => {
    wideScreen(false);
    renderWorkspace();
    expect(screen.getByText("Wybierz osobę z listy")).toBeInTheDocument();
  });

  it("wskazana osoba (np. z adresu) wygrywa z pierwszą na liście", async () => {
    wideScreen(true);
    renderWorkspace({ activeCandidateId: 4 });
    expect(screen.getByTestId("person-panel")).toHaveTextContent("Natalia Krawczyk");
  });
});

describe("RecruitmentWorkspace — panel i akcje", () => {
  it("klik w wiersz otwiera panel tej osoby; przed wyborem jest podpowiedź", async () => {
    renderWorkspace();
    expect(screen.getByText("Wybierz osobę z listy")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Marek Zieliński"));
    expect(screen.getByTestId("person-panel")).toHaveTextContent("Marek Zieliński");
    expect(mocks.panelProps).toMatchObject({ jobId: 42, readOnly: false, section: null });
    expect((mocks.panelProps?.workbenchContext as Record<string, unknown>)).toMatchObject({
      jobTitle: "Senior Java",
      budgetHourly: 190,
      clientId: 9,
    });
  });

  it("panel zostaje na osobie, która wypadła z filtra (np. po ruchu)", async () => {
    renderWorkspace({ activeCandidateId: 2 });
    await userEvent.click(screen.getByRole("button", { name: /Odrzuceni/ }));
    expect(names()).toEqual(["Paweł Król"]);
    expect(screen.getByTestId("person-panel")).toHaveTextContent("Marek Zieliński");
  });

  it("skrót „N” otwiera notatki aktywnej osoby", async () => {
    renderWorkspace({ activeCandidateId: 2 });
    fireEvent.keyDown(screen.getByRole("grid"), { key: "n" });
    await waitFor(() => expect(mocks.panelProps).toMatchObject({ section: "notes", noteFocusSignal: 1 }));
  });

  it("zaznaczenie pokazuje pasek zbiorczy; wysyłka CV = useBulkCvHandoff (ruch + linki), nie sam ruch zbiorczy", async () => {
    renderWorkspace();
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Marek Zieliński" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Katarzyna Wójcik" }));
    const bar = screen.getByRole("toolbar");
    expect(bar).toHaveTextContent("Zaznaczono 2");
    await userEvent.click(within(bar).getByRole("button", { name: "Wyślij CV do klienta" }));
    expect(mocks.move.requestBulkMove).not.toHaveBeenCalled();
    expect(mocks.bulkCvStart).toHaveBeenCalledTimes(1);
    const [rows, opts] = mocks.bulkCvStart.mock.calls[0];
    expect(rows.map((r: { candidateId: number }) => r.candidateId)).toEqual([2, 3]);
    expect(rows.map((r: { item: { id: number } }) => typeof r.item.id)).toEqual(["number", "number"]);
    expect(mocks.bulkCvOptions).toMatchObject({ jobId: 42, canWriteClientRate: true, columns });
    // `onHandled` czyści zaznaczenie po pętli.
    act(() => opts.onHandled());
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("zmiana segmentu czyści zaznaczenie", async () => {
    renderWorkspace();
    await userEvent.click(screen.getByRole("checkbox", { name: "Zaznacz: Marek Zieliński" }));
    await userEvent.click(screen.getByRole("button", { name: /^\d+Zweryfikowani$/ }));
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  });

  it("usePipelineMove dostaje budżet, powody i prawa z propsów", () => {
    renderWorkspace({ canWriteClientRate: false });
    expect(mocks.moveOptions).toMatchObject({
      jobId: 42,
      readOnly: false,
      canWriteClientRate: false,
      job: { budgetHourly: 190, rejectionReasons: [] },
      columns,
    });
  });

  it("tylko do odczytu: bez checkboxów, bez paska zbiorczego, bez „Dodaj kandydatów”", () => {
    renderWorkspace({ canWritePipeline: false });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj kandydatów/ })).not.toBeInTheDocument();
    expect(mocks.moveOptions).toMatchObject({ readOnly: true });
  });

  it("„Szukaj ręcznie” otwiera okno wysuwane", async () => {
    const onOpenSlideOver = vi.fn();
    renderWorkspace({ onOpenSlideOver });
    await userEvent.click(screen.getByRole("button", { name: /Szukaj ręcznie/ }));
    expect(onOpenSlideOver).toHaveBeenCalledWith("manual-search");
  });
});
