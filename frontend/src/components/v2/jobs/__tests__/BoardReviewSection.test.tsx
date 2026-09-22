import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const addMock = vi.fn();
const inboxMock = vi.fn();
const dismissMock = vi.fn();

vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...a: unknown[]) => addMock(...a) },
}));
vi.mock("@/lib/job-proposals-api", async (orig) => {
  const actual = await orig<typeof import("@/lib/job-proposals-api")>();
  return {
    ...actual,
    jobProposalsApi: {
      inbox: (...a: unknown[]) => inboxMock(...a),
      dismiss: (...a: unknown[]) => dismissMock(...a),
    },
  };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { BoardReviewSection } from "@/components/v2/jobs/BoardReviewSection";

function item(id: number, sources: string[], extra: Record<string, unknown> = {}) {
  return {
    candidate: {
      id,
      name: "Osoba",
      lastname: String(id),
      title: "Java Developer",
      city: null,
      availability_status: null,
      availability_date: null,
      expected_rate_hourly: null,
      expected_rate_redacted: false,
    },
    sources,
    score: 88,
    evidence: null,
    first_seen_at: null,
    last_seen_at: null,
    is_new: false,
    status: "proposed",
    run_id: null,
    eligibility: null,
    ...extra,
  };
}

function renderSection(readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BoardReviewSection jobId={5} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  inboxMock.mockResolvedValue({
    items: [
      item(1, ["reassign"], {
        reassign_from: {
          job_id: 9,
          title: "Kotlin Developer",
          reference_number: "#4588",
          client_name: "mBank",
          stage: "cv_sent",
          sent_at: "2026-08-26",
        },
      }),
      item(2, ["full_base"]),
    ],
    total: 14,
  });
  addMock.mockResolvedValue({ added: [1], skipped: [], total_added: 1, total_skipped: 0 });
  dismissMock.mockResolvedValue({ dismissed: true });
});

describe("Tablica — kolumna „Do przejrzenia”", () => {
  it("przepięcie mówi, gdzie osoba była u klienta; ✓ dodaje do Screening", async () => {
    renderSection();
    expect(await screen.findByText("↻ Przepięcie")).toBeInTheDocument();
    expect(
      screen.getByText("Wysłany do klienta: mBank · Kotlin Developer · 26.08.2026"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj Osoba 1 do Screening" }));
    await waitFor(() =>
      expect(addMock).toHaveBeenCalledWith(5, {
        candidate_ids: [1],
        source: "proposal_inbox",
        initial_stage_legacy: "screening",
        run_id: null,
      }),
    );
  });

  it("✕ pomija z właściwym źródłem, a nadmiar prowadzi do pełnej listy", async () => {
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Pomiń Osoba 2" }));
    await waitFor(() => expect(dismissMock).toHaveBeenCalledWith(5, 2, "full_base"));
    expect(screen.getByRole("link", { name: "Przejrzyj wszystkich 14 →" })).toHaveAttribute(
      "href",
      "/jobs/5?tab=people&seg=proposals",
    );
  });

  it("tylko do odczytu — bez przycisków akcji", async () => {
    renderSection(true);
    await screen.findByText("↻ Przepięcie");
    expect(screen.queryByRole("button", { name: /Screening/ })).not.toBeInTheDocument();
  });
});
