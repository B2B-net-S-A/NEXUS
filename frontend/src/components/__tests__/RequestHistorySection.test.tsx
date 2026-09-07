import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  forJob: vi.fn(),
  addCandidate: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  requestHistoryApi: {
    forJob: (...args: unknown[]) => mocks.forJob(...args),
    addCandidate: (...args: unknown[]) => mocks.addCandidate(...args),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast }),
}));

vi.mock("@/components/AppShell", () => ({
  AddJobModal: () => <div role="dialog">Kopiowanie requestu</div>,
}));

import { RequestHistorySection } from "@/components/RequestHistorySection";

const RESPONSE = {
  closed: [
    {
      job_id: 12,
      title: "Senior Java Developer",
      status: "closed",
      is_in_progress: false,
      similarity: 0.95,
      similarity_source: "sql_same_client",
      champion_candidate_id: 42,
      champion_name: "Anna Nowak",
      champions_count: 1,
      candidates_count: 3,
      train_name: null,
      same_train: false,
      seniority: "senior",
      outcome: "filled",
      close_reason: null,
      tth_days: 20,
      fee_rate: null,
      fee_currency: null,
      rate_unit: null,
      tac_name: null,
      delivery_lead_name: null,
      closed_at: "2026-08-01T00:00:00Z",
    },
  ],
  in_progress: [],
};

function renderSection(readOnly: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RequestHistorySection jobId={7} clientId={3} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("RequestHistorySection read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.forJob.mockResolvedValue({ data: RESPONSE });
    mocks.addCandidate.mockResolvedValue({ data: {} });
  });

  it("zachowuje historię i odczytowe filtry, ale ukrywa kopiowanie i dodanie championa", async () => {
    renderSection(true);

    expect(await screen.findByText("Senior Java Developer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Otwórz" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Skopiuj jako template" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Dodaj championa" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("request-history-cross-client"));
    await waitFor(() => expect(mocks.forJob).toHaveBeenCalledTimes(2));
    expect(mocks.addCandidate).not.toHaveBeenCalled();
  });

  it("pozostawia akcje dla użytkownika z zapisem", async () => {
    renderSection(false);

    expect(
      await screen.findByRole("button", { name: "Skopiuj jako template" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj championa" }));

    await waitFor(() =>
      expect(mocks.addCandidate).toHaveBeenCalledWith(7, {
        candidate_id: 42,
        source_job_id: 12,
      }),
    );
  });
});

// ── Krok 03 „Pozyskiwanie" (SourcingHub, PR 2/7) — prop `compact` ───────────

const MULTI_RESPONSE = {
  closed: [
    { ...RESPONSE.closed[0], job_id: 12, title: "Najbliższy (95%)", similarity: 0.95 },
    {
      ...RESPONSE.closed[0],
      job_id: 13,
      title: "Bez kandydatów (90%)",
      similarity: 0.9,
      candidates_count: 0,
      champion_candidate_id: null,
      champion_name: null,
    },
    { ...RESPONSE.closed[0], job_id: 14, title: "Trzeci (80%)", similarity: 0.8 },
  ],
  in_progress: [
    {
      ...RESPONSE.closed[0],
      job_id: 15,
      title: "W toku, ale dalej (60%)",
      similarity: 0.6,
      status: "published",
      is_in_progress: true,
    },
  ],
};

describe("RequestHistorySection compact (rama źródeł, krok 03)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.forJob.mockResolvedValue({ data: MULTI_RESPONSE });
    mocks.addCandidate.mockResolvedValue({ data: {} });
  });

  function renderCompact(onCandidatesToSource = vi.fn()) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RequestHistorySection
          jobId={7}
          clientId={3}
          readOnly={false}
          compact
          maxItems={3}
          onCandidatesToSource={onCandidatesToSource}
        />
      </QueryClientProvider>,
    );
    return { onCandidatesToSource };
  }

  it("pokazuje TYLKO 3 najbliższe requesty (closed + in_progress połączone po similarity), bez zakładek", async () => {
    renderCompact();

    expect(await screen.findByText("Najbliższy (95%)")).toBeInTheDocument();
    expect(screen.getByText("Bez kandydatów (90%)")).toBeInTheDocument();
    expect(screen.getByText("Trzeci (80%)")).toBeInTheDocument();
    // Czwarty (60%, in_progress) odpada — zmieściły się tylko 3 najbliższe.
    expect(screen.queryByText("W toku, ale dalej (60%)")).not.toBeInTheDocument();
    // Bucket tabs pełnego widoku ("Zamknięte (N)" / "W toku (N)") nie ma w compact.
    expect(screen.queryByText(/^Zamknięte \(/)).not.toBeInTheDocument();
    // Kompaktowy nagłówek liczy CAŁY zbiór, nie tylko widoczne 3.
    expect(screen.getByText("Zamknięte 3 · W toku 1")).toBeInTheDocument();
  });

  it("„N kandydatów → źródło” pojawia się tylko gdy candidates_count > 0 i woła onCandidatesToSource z właściwym wpisem", async () => {
    const { onCandidatesToSource } = renderCompact();

    const noCandidatesTitle = await screen.findByText("Bez kandydatów (90%)");
    // Request bez kandydatów nie dostaje przycisku — nie ma czego przekierować.
    const noCandidatesRow = noCandidatesTitle.closest("li") as HTMLElement;
    expect(
      within(noCandidatesRow).queryByRole("button", { name: /kandydatów → źródło/ }),
    ).not.toBeInTheDocument();

    const sourceButtons = screen.getAllByRole("button", {
      name: /3 kandydatów → źródło/,
    });
    expect(sourceButtons).toHaveLength(2); // "Najbliższy" i "Trzeci" mają candidates_count=3

    fireEvent.click(sourceButtons[0]);
    expect(onCandidatesToSource).toHaveBeenCalledWith(
      expect.objectContaining({ job_id: 12, title: "Najbliższy (95%)" }),
    );
  });

  it("„N kandydatów → źródło” zostaje widoczny nawet w readOnly — to nawigacja, nie mutacja", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const onCandidatesToSource = vi.fn();
    render(
      <QueryClientProvider client={queryClient}>
        <RequestHistorySection
          jobId={7}
          clientId={3}
          readOnly
          compact
          onCandidatesToSource={onCandidatesToSource}
        />
      </QueryClientProvider>,
    );

    expect(
      (await screen.findAllByRole("button", { name: /kandydatów → źródło/ })).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", { name: "Skopiuj jako template" }),
    ).not.toBeInTheDocument();
  });
});
