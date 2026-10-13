import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  add: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: { search: mocks.search },
  proposalsBulkApi: { add: mocks.add },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

// Debounce bez zegara — zapytanie idzie od razu.
vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: string) => value,
}));

import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";

const NDA = {
  reason_code: "client_nda",
  reason: "Konflikt: NDA z klientem",
  assignment_allowed: true,
  visibility: "warn",
  severity: "warning",
  secondary: [],
};
const VETO = {
  reason_code: "rejected_by_hiring_manager",
  reason: "Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie",
  assignment_allowed: false,
  visibility: "warn",
  severity: "hard",
  secondary: [],
};

function item(id: number, eligibility: unknown = null) {
  return {
    id,
    name: "Kandydat",
    lastname: `Nr${id}`,
    location: null,
    source: null,
    competence_category: null,
    is_champion: false,
    eligibility,
  };
}

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AddCandidatesQuickModal open onClose={vi.fn()} jobId={9} jobTitle="Java" />
    </QueryClientProvider>,
  );
}

describe("AddCandidatesQuickModal — eligibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search.mockResolvedValue({
      items: [item(1, NDA), item(2, VETO), item(3)],
      total: 3,
    });
    mocks.add.mockResolvedValue({
      added: [1, 3],
      skipped: [],
      warnings: [{ candidate_id: 1, reason: "client_nda" }],
      total_added: 2,
      total_skipped: 0,
    });
  });

  it("shows a warning chip for a client conflict and lets the row be selected", async () => {
    renderModal();
    const chip = await screen.findByTestId("add-candidate-eligibility-1");
    expect(chip).toHaveTextContent("Konflikt: NDA z klientem");
    expect(chip.className).toContain("warning");
    expect(screen.getByTestId("add-candidate-row-1")).toBeEnabled();
    expect(mocks.search).toHaveBeenCalledWith(
      expect.objectContaining({ exclude_in_job_id: 9 }),
    );
  });

  it("searches names literally via the shared v2 text rule", async () => {
    renderModal();
    await screen.findByTestId("add-candidate-row-1");
    fireEvent.change(screen.getByPlaceholderText("Wpisz imię i nazwisko..."), {
      target: { value: "TestPipelineD" },
    });
    await waitFor(() =>
      expect(mocks.search).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "TestPipelineD",
          semantics_version: 2,
          text_mode: "auto",
        }),
      ),
    );
  });

  it("a hiring-manager veto disables the row with the reason as title", async () => {
    renderModal();
    const row = await screen.findByTestId("add-candidate-row-2");
    expect(row).toBeDisabled();
    expect(row).toHaveAttribute("title", VETO.reason);
    expect(screen.getByTestId("add-candidate-eligibility-2").className).toContain("destructive");
  });

  it("'Zaznacz wszystkich' skips vetoed candidates and adds the rest", async () => {
    renderModal();
    await screen.findByTestId("add-candidate-row-1");
    fireEvent.click(screen.getByRole("button", { name: "Zaznacz wszystkich" }));
    expect(screen.getByText("Zaznaczono 2 kandydatów")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odznacz wszystkich" })).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("add-candidates-confirm"));
    await waitFor(() => expect(mocks.add).toHaveBeenCalledTimes(1));
    const [jobId, payload] = mocks.add.mock.calls[0];
    expect(jobId).toBe(9);
    expect([...payload.candidate_ids].sort()).toEqual([1, 3]);
  });

  it("pokazuje znacznik „Pracuje u nas”, a po zaznaczeniu ramkę — bez blokady", async () => {
    const working = {
      phase: "working",
      source: "contract",
      elsewhere: true,
      clients: [
        {
          client_id: 4,
          client_name: "Bank Przykładowy",
          contract_id: 40,
          phase: "working",
          order_end_date: "2026-12-31",
          delivery_lead_name: "Karol Wzorcowy",
        },
      ],
    };
    const atThisClient = {
      reason_code: "client_current_employment",
      reason: "Kandydat obecnie pracuje u tego klienta",
      assignment_allowed: true,
      visibility: "warn",
      severity: "warning",
      secondary: [],
    };
    mocks.search.mockResolvedValue({
      items: [
        { ...item(1), employment_marker: working },
        {
          ...item(2, atThisClient),
          employment_marker: { ...working, elsewhere: false },
        },
        item(3),
      ],
      total: 3,
    });
    renderModal();

    const row = await screen.findByTestId("add-candidate-row-1");
    expect(row).toHaveTextContent("Pracuje u nas · Bank Przykładowy · do 31.12.2026");
    expect(row).toBeEnabled();
    // Klient tej rekrutacji: jeden znacznik zamiast znacznika i plakietki.
    expect(screen.getByTestId("add-candidate-row-2")).toHaveTextContent("Pracuje u tego klienta");
    expect(screen.queryByTestId("add-candidate-eligibility-2")).toBeNull();
    expect(screen.queryByRole("note")).toBeNull();

    fireEvent.click(row);
    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent("Kandydat Nr1 pracuje u nas · Bank Przykładowy");
    expect(notice).toHaveTextContent("Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy");
    expect(notice).toHaveTextContent("Dodanie jest możliwe.");
    expect(screen.getByTestId("add-candidates-confirm")).toBeEnabled();

    fireEvent.click(row);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("a failed search is an error, not 'no results'", async () => {
    mocks.search.mockRejectedValue(new Error("down"));
    renderModal();
    expect(await screen.findByText("Błąd wyszukiwania. Spróbuj ponownie.")).toBeInTheDocument();
    expect(screen.queryByText("Wpisz imię lub nazwisko kandydata")).not.toBeInTheDocument();
  });
});

describe("AddCandidatesQuickModal — rama dialogu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search.mockResolvedValue({ items: [item(1)], total: 1 });
  });

  it("jest dostępnym dialogiem z tytułem, a Escape go zamyka", async () => {
    const onClose = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AddCandidatesQuickModal open onClose={onClose} jobId={9} jobTitle="Java" />
      </QueryClientProvider>,
    );

    const dialog = await screen.findByRole("dialog", { name: "Dodaj kandydatów do pipeline" });
    expect(dialog).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
