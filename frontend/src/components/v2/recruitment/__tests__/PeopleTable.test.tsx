import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  removeFromRecruitment: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  candidatesApi: { removeFromRecruitment: mocks.removeFromRecruitment },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));
vi.mock("@/components/CandidatePipelinesWidget", () => ({
  candidatePipelinesQueryKey: (id: number) => ["candidate-pipelines", id],
}));

import { PeopleTable, type PeopleTableProps } from "@/components/v2/recruitment/PeopleTable";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { ProposalPersonRow } from "@/components/v2/recruitment/types";

import { item, template } from "./recruitment-fixtures";

const processRows = buildProcessRows(
  template({
    3: [
      item(1, {
        name: "Marek",
        lastname: "Zieliński",
        days_in_stage: 4,
        expected_rate_value: "210",
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
        availability_status: "open_to_offers",
        screening_done: false,
      }),
    ],
    1: [item(2, { name: "Ewa", lastname: "Pawlak", days_in_stage: 0 })],
  }),
  { scores: new Map([[1, 91]]), budgetHourly: 190 },
);

const proposalRows: ProposalPersonRow[] = [
  {
    kind: "proposal",
    key: "prop:7",
    candidateId: 7,
    fullName: "Łukasz Pietrzak",
    rateLabel: "180 PLN/h",
    availabilityLabel: "od razu",
    fitScore: 88,
    warnings: [],
    sources: ["new_cv", "similar_projects"],
    reason: "CV z maila wczoraj · płatności, Kafka Streams",
    isNew: true,
    previouslyDismissed: false,
    runId: null,
  },
  {
    kind: "proposal",
    key: "prop:8",
    candidateId: 8,
    fullName: "Kamil Borkowski",
    rateLabel: null,
    availabilityLabel: null,
    fitScore: null,
    warnings: [],
    sources: ["full_base"],
    reason: null,
    isNew: false,
    previouslyDismissed: true,
    runId: "run-1",
  },
];

function renderTable(props: Partial<PeopleTableProps> & Pick<PeopleTableProps, "variant" | "rows">) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <PeopleTable jobId={42} virtualize={false} {...props} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

const rowOf = (name: string) => screen.getByText(name).closest("[role='row']") as HTMLElement;

beforeEach(() => vi.clearAllMocks());

describe("PeopleTable — osoby w procesie", () => {
  it("kolumny procesu: etap, następny krok z odznakami, dni, stawka, dostępność, dopasowanie", () => {
    renderTable({ variant: "process", rows: processRows, onSelectionChange: vi.fn(), selectedKeys: new Set() });
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "", "Kandydat", "Etap", "Następny krok", "W etapie", "Stawka", "Dostępność", "Dop.", "Akcje",
    ]);
    const marek = within(rowOf("Marek Zieliński"));
    expect(marek.getByText("Zweryfikowany")).toBeInTheDocument();
    expect(marek.getByText("Wyślij CV do klienta")).toBeInTheDocument();
    expect(marek.getByText("ponad budżet")).toBeInTheDocument();
    expect(marek.getByText("Uzupełnij screening")).toBeInTheDocument();
    expect(marek.getByText("4 d")).toBeInTheDocument();
    expect(marek.getByText("210 PLN/h")).toBeInTheDocument();
    expect(marek.getByText("Otwarty na oferty")).toBeInTheDocument();
    expect(marek.getByLabelText("Dopasowanie: 91 na 100")).toHaveTextContent("91");
    expect(within(rowOf("Ewa Pawlak")).getByText("dziś")).toBeInTheDocument();
  });

  it("brak dopasowania to „—” z podpowiedzią „Nie policzono”, nigdy 0", () => {
    renderTable({ variant: "process", rows: processRows });
    const cell = within(rowOf("Ewa Pawlak")).getByTitle("Nie policzono");
    expect(cell).toHaveTextContent("—");
    expect(within(rowOf("Ewa Pawlak")).queryByText("0")).not.toBeInTheDocument();
  });

  it("tylko do odczytu: bez checkboxów i bez „Usuń z rekrutacji”", async () => {
    renderTable({
      variant: "process",
      rows: processRows,
      readOnly: true,
      onSelectionChange: vi.fn(),
      selectedKeys: new Set(),
    });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Akcje: Ewa Pawlak" }));
    expect(await screen.findByRole("menuitem", { name: "Pełny profil" })).toHaveAttribute(
      "href",
      "/candidates/2?from=job&jobId=42",
    );
    expect(screen.queryByRole("menuitem", { name: "Usuń z rekrutacji" })).not.toBeInTheDocument();
  });

  it("menu wiersza nie aktywuje wiersza; usunięcie wymaga potwierdzenia i odświeża OBA klucze tablicy", async () => {
    mocks.removeFromRecruitment.mockResolvedValue({});
    const onActiveChange = vi.fn();
    const onRemoved = vi.fn();
    const { invalidate } = renderTable({ variant: "process", rows: processRows, onActiveChange, onRemoved });
    await userEvent.click(screen.getByRole("button", { name: "Akcje: Ewa Pawlak" }));
    expect(onActiveChange).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("menuitem", { name: "Usuń z rekrutacji" }));
    const dialog = await screen.findByRole("dialog");
    expect(mocks.removeFromRecruitment).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Usuń z rekrutacji" }));
    await waitFor(() => expect(mocks.removeFromRecruitment).toHaveBeenCalledWith(2, 42));
    await waitFor(() => expect(onRemoved).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map(([arg]) => JSON.stringify(arg?.queryKey));
    expect(keys).toContain(JSON.stringify(["kanban", "42"]));
    expect(keys).toContain(JSON.stringify(["kanban", 42]));
  });

  it("skróty klawiatury: E → zmiana etapu, N → notatka (dla aktywnego wiersza)", () => {
    const onRequestStageChange = vi.fn();
    const onRequestNote = vi.fn();
    renderTable({
      variant: "process",
      rows: processRows,
      activeKey: processRows[0].key,
      onRequestStageChange,
      onRequestNote,
    });
    const grid = screen.getByRole("grid", { name: "Osoby w rekrutacji" });
    fireEvent.keyDown(grid, { key: "e" });
    fireEvent.keyDown(grid, { key: "n" });
    expect(onRequestStageChange).toHaveBeenCalledWith(processRows[0]);
    expect(onRequestNote).toHaveBeenCalledWith(processRows[0]);
  });

  it("tylko do odczytu: „E” milczy, „N” nadal otwiera notatki", () => {
    const onRequestStageChange = vi.fn();
    const onRequestNote = vi.fn();
    renderTable({
      variant: "process",
      rows: processRows,
      readOnly: true,
      activeKey: processRows[0].key,
      onRequestStageChange,
      onRequestNote,
    });
    const grid = screen.getByRole("grid");
    fireEvent.keyDown(grid, { key: "e" });
    fireEvent.keyDown(grid, { key: "n" });
    expect(onRequestStageChange).not.toHaveBeenCalled();
    expect(onRequestNote).toHaveBeenCalled();
  });

  it("grupy: nagłówki z licznikiem, „Bez ruchu…” zwinięta na starcie", async () => {
    renderTable({
      variant: "process",
      rows: processRows,
      groups: [
        { key: "mine", label: "Wymaga mojego ruchu", rowKeys: ["c:1"] },
        { key: "stale", label: "Bez ruchu ponad 14 dni", rowKeys: ["c:2"] },
      ],
    });
    expect(screen.getByRole("button", { name: /Wymaga mojego ruchu/ })).toHaveAttribute("aria-expanded", "true");
    const stale = screen.getByRole("button", { name: /Bez ruchu ponad 14 dni/ });
    expect(stale).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Ewa Pawlak")).not.toBeInTheDocument();
    await userEvent.click(stale);
    expect(screen.getByText("Ewa Pawlak")).toBeInTheDocument();
  });

  it("sortowanie nagłówkiem zgłasza klucz tabeli osób; trzeci klik wraca do domyślnego (null)", async () => {
    const onSortChange = vi.fn();
    renderTable({ variant: "process", rows: processRows, sort: { key: "fit", dir: "desc" }, onSortChange });
    await userEvent.click(screen.getByRole("button", { name: /Kandydat/ }));
    expect(onSortChange).toHaveBeenLastCalledWith({ key: "name", dir: "asc" });
    await userEvent.click(screen.getByRole("button", { name: /Dop\./ }));
    expect(onSortChange).toHaveBeenLastCalledWith(null);
  });
});

describe("PeopleTable — propozycje", () => {
  it("kolumny propozycji: kilka źródeł naraz, „dlaczego pasuje”, znaczniki", () => {
    renderTable({ variant: "proposal", rows: proposalRows });
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Kandydat", "Źródło", "Dlaczego pasuje", "Stawka", "Dostępność", "Dop.",
    ]);
    const lukasz = within(rowOf("Łukasz Pietrzak"));
    expect(lukasz.getByText("Nowe CV")).toBeInTheDocument();
    expect(lukasz.getByText("Podobne projekty")).toBeInTheDocument();
    expect(lukasz.getByText(/Kafka Streams/)).toBeInTheDocument();
    expect(lukasz.getByText("nowa")).toBeInTheDocument();
    const kamil = within(rowOf("Kamil Borkowski"));
    expect(kamil.getByText("Cała baza")).toBeInTheDocument();
    expect(kamil.getByText("wcześniej pominięta")).toBeInTheDocument();
    expect(kamil.getByTitle("Nie policzono")).toBeInTheDocument();
  });
});
