import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const suggestions = vi.fn();
const send = vi.fn();
vi.mock("@/lib/dl-match-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/dl-match-api")>()),
  dlMatchApi: {
    suggestions: (...a: unknown[]) => suggestions(...a),
    send: (...a: unknown[]) => send(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { DlMatchDialog } from "../DlMatchDialog";
import { sendAlsoUnit } from "@/components/v2/jobs/PipelineCandidateDock";

describe("„Wyślij też do…” — stawka idzie w jednostce i walucie z tej rekrutacji", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    suggestions.mockResolvedValue({
      candidate_id: 21,
      from_job_id: 31,
      status: "ok",
      jobs: [
        { job_id: 41, title: "Java B", client_name: null, client_reference: "ZOB-41", score: 80,
          matching_must: [], gap_must: [], linked: true, destination: "cv_sent", sendable: true },
      ],
      already_in: [],
    });
    send.mockResolvedValue({ candidate_id: 21, from_job_id: 31, results: [] });
  });

  it("stawka dzienna w EUR nie zamienia się w PLN za godzinę", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DlMatchDialog
          open
          onOpenChange={() => undefined}
          candidateId={21}
          candidateName="Anna Nowak"
          jobId={31}
          jobLabel="Java A"
          defaultRate="1200"
          rateUnit="daily"
          currency="EUR"
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/Stawki w EUR\/MD/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Wyślij do 1 rekrutacji" }));
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith({
        candidate_id: 21,
        from_job_id: 31,
        targets: [{ job_id: 41, client_rate_value: 1200, client_rate_unit: "daily", client_rate_currency: "EUR" }],
      }),
    );
  });

  it("jednostka karty bez znanej wartości to stawka godzinowa", () => {
    expect(sendAlsoUnit("daily")).toBe("daily");
    expect(sendAlsoUnit("monthly")).toBe("monthly");
    expect(sendAlsoUnit(null)).toBe("hourly");
    expect(sendAlsoUnit("weird")).toBe("hourly");
  });
});
