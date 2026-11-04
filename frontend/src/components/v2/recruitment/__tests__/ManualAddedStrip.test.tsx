import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  remove: vi.fn(),
  alsoFits: vi.fn(),
  bulkAdd: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  candidatesApi: { removeFromRecruitment: (...a: unknown[]) => mocks.remove(...a) },
}));
vi.mock("@/lib/also-fits-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/also-fits-api")>();
  return { ...actual, alsoFitsApi: { get: (...a: unknown[]) => mocks.alsoFits(...a) } };
});
vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...a: unknown[]) => mocks.bulkAdd(...a) },
}));

import { ManualAddedStrip } from "../ManualAddedStrip";

const EWA = { candidateId: 1, fullName: "Ewa Marczak" };
const PIOTR = { candidateId: 2, fullName: "Piotr Lis" };

function mount(props: Partial<React.ComponentProps<typeof ManualAddedStrip>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const onUndone = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ManualAddedStrip
        jobId={7}
        people={[EWA, PIOTR]}
        undoExpired={new Set()}
        readOnly={false}
        onUndone={onUndone}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onUndone, invalidate };
}

function row(name: string): HTMLElement {
  const item = screen.getByText(name).closest("li");
  if (!item) throw new Error(`Brak wiersza: ${name}`);
  return item;
}

beforeEach(() => {
  mocks.alsoFits.mockResolvedValue({ candidate_id: 0, from_job_id: 7, status: "ok", jobs: [] });
});
afterEach(() => vi.clearAllMocks());

describe("ManualAddedStrip — „Dodani teraz” w „Szukaj ręcznie”", () => {
  it("nikt nie dodany — pasek się nie pokazuje", () => {
    mount({ people: [] });
    expect(screen.queryByText(/Dodani teraz/)).not.toBeInTheDocument();
    expect(mocks.alsoFits).not.toHaveBeenCalled();
  });

  it("pokazuje dodanych (najnowsi u góry) z „Dodano do „Nowych”” i „Cofnij”", () => {
    mount();
    const strip = screen.getByRole("region", { name: "Dodani teraz" });
    expect(within(strip).getByText("Dodani teraz (2)")).toBeInTheDocument();
    const names = within(strip)
      .getAllByRole("listitem")
      .map((li) => li.getAttribute("data-candidate-id"));
    expect(names).toEqual(["2", "1"]);
    expect(within(row("Ewa Marczak")).getByText(/Dodano do „Nowych” · rezerwacja 12 h/)).toBeInTheDocument();
    expect(within(row("Ewa Marczak")).getByRole("button", { name: "Cofnij dodanie: Ewa Marczak" })).toBeEnabled();
  });

  it("„Cofnij” usuwa z rekrutacji szybkim cofnięciem, odświeża Tablicę i listy, potem zdejmuje wiersz", async () => {
    mocks.remove.mockResolvedValue({});
    const { onUndone, invalidate } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Cofnij dodanie: Ewa Marczak" }));
    expect(within(row("Ewa Marczak")).getByRole("button", { name: "Cofnij dodanie: Ewa Marczak" })).toHaveTextContent(
      "Cofam…",
    );
    await waitFor(() => expect(onUndone).toHaveBeenCalledWith(1));
    expect(mocks.remove).toHaveBeenCalledWith(1, 7, { quickUndo: true });
    const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    // Te same klucze co „Cofnij” w pozostałych zakładkach okna, plus lista
    // „Szukaj ręcznie” — osoba wraca do wyników.
    for (const key of [
      ["kanban", "7"],
      ["kanban", 7],
      ["pipeline-scores"],
      ["job-proposals", 7],
      ["jobs"],
      ["jobs-v2"],
      ["candidates-v2"],
    ]) {
      expect(keys).toContain(JSON.stringify(key));
    }
  });

  it("błąd cofnięcia: komunikat serwera przy wierszu, wiersz zostaje, „Cofnij” znów działa", async () => {
    mocks.remove.mockRejectedValue({
      response: { status: 409, data: { detail: "Minęło 15 minut — usuń osobę z panelu osoby." } },
    });
    const { onUndone } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Cofnij dodanie: Ewa Marczak" }));
    const alert = await within(row("Ewa Marczak")).findByRole("alert");
    expect(alert).toHaveTextContent("Minęło 15 minut — usuń osobę z panelu osoby.");
    expect(onUndone).not.toHaveBeenCalled();
    expect(within(row("Ewa Marczak")).getByRole("button", { name: "Cofnij dodanie: Ewa Marczak" })).toBeEnabled();
  });

  it("pod wierszem blok „Pasuje też do” z „+ Dodaj”", async () => {
    mocks.alsoFits.mockImplementation(async (candidateId: number) => ({
      candidate_id: candidateId,
      from_job_id: 7,
      status: "ok",
      jobs:
        candidateId === 1
          ? [
              {
                job_id: 21,
                title: "Angular Developer",
                client_name: "Ubezpieczenia Demo",
                score: 84,
                matching_must: ["Angular"],
                gap_must: [],
              },
            ]
          : [],
    }));
    mount();
    const block = await within(row("Ewa Marczak")).findByTestId("also-fits-block");
    expect(within(block).getByText("Pasuje też do 1 innej rekrutacji")).toBeInTheDocument();
    expect(
      within(block).getByRole("button", { name: "Dodaj Ewa Marczak też do: Angular Developer" }),
    ).toBeEnabled();
    expect(mocks.alsoFits).toHaveBeenCalledWith(1, 7);
    expect(mocks.alsoFits).toHaveBeenCalledWith(2, 7);
  });

  it("po 15 minutach „Cofnij” znika", () => {
    mount({ undoExpired: new Set([1]) });
    expect(within(row("Ewa Marczak")).queryByRole("button", { name: /Cofnij/ })).not.toBeInTheDocument();
    expect(within(row("Ewa Marczak")).getByText(/Dodano do „Nowych”/)).toBeInTheDocument();
    expect(within(row("Piotr Lis")).getByRole("button", { name: "Cofnij dodanie: Piotr Lis" })).toBeEnabled();
  });

  it("tylko podgląd — bez „Cofnij” i bez „Pasuje też do”", () => {
    mount({ readOnly: true });
    expect(screen.getByText("Dodani teraz (2)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Cofnij/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId("also-fits-block")).not.toBeInTheDocument();
    expect(mocks.alsoFits).not.toHaveBeenCalled();
  });

  it("po wielu dodaniach pokazuje 3 najnowsze, resztę po „Pokaż wszystkich” — lista zostaje w zasięgu wzroku", () => {
    const people = [1, 2, 3, 4, 5].map((id) => ({ candidateId: id, fullName: `Osoba Testowa ${id}` }));
    mount({ people });
    const strip = screen.getByRole("region", { name: "Dodani teraz" });
    expect(within(strip).getAllByRole("listitem").map((li) => li.getAttribute("data-candidate-id"))).toEqual(["5", "4", "3"]);
    fireEvent.click(within(strip).getByRole("button", { name: "Pokaż wszystkich (5)" }));
    expect(within(strip).getAllByRole("listitem")).toHaveLength(5);
    fireEvent.click(within(strip).getByRole("button", { name: "Zwiń" }));
    expect(within(strip).getAllByRole("listitem")).toHaveLength(3);
  });
});

