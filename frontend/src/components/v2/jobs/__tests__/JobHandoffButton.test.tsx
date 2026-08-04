import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobHandoffButton } from "@/components/v2/jobs/JobHandoffButton";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  handoff: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  jobsApi: { handoff: (...args: unknown[]) => mocks.handoff(...args) },
}));

function renderButton() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <JobHandoffButton jobId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockResolvedValue({
    data: [{ id: 5, name: "Rec One", email: "r@example.com" }],
  });
});

describe("JobHandoffButton", () => {
  it("assigns the chosen recruiter and starts the search", async () => {
    mocks.handoff.mockResolvedValue({ data: { status: "handed_off" } });

    renderButton();
    fireEvent.click(screen.getByTestId("handoff-open"));
    await screen.findByText("Rec One");
    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    await waitFor(() => expect(mocks.handoff).toHaveBeenCalledWith(7, 5));
    expect(await screen.findByTestId("handoff-done")).toBeInTheDocument();
  });

  it("shows readiness blockers on a 422 instead of starting the search", async () => {
    mocks.handoff.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            message: "Rekrutacja nie jest gotowa.",
            blockers: ["Dodaj co najmniej 2 pytania screeningowe w Profilu Championa."],
          },
        },
      },
    });

    renderButton();
    fireEvent.click(screen.getByTestId("handoff-open"));
    await screen.findByText("Rec One");
    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    expect(await screen.findByTestId("handoff-blockers")).toHaveTextContent(
      "pytania screeningowe",
    );
    expect(screen.queryByTestId("handoff-done")).not.toBeInTheDocument();
  });
});
