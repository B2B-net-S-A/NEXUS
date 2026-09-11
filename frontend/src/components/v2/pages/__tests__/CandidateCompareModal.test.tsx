import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const matchScores = vi.fn();

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    matchScores: (...args: unknown[]) => matchScores(...args),
  },
}));

import { CandidateCompareModal } from "@/components/v2/pages/CandidateCompareModal";

const httpError = (status: number) =>
  Object.assign(new Error(`HTTP ${status}`), { response: { status } });

const measured = {
  scores: { "1": 81, "2": 64 },
  breakdowns: {
    "1": { total: 81, measurement: "measured", matching_must: ["java"], gap_must: [] },
    "2": { total: 64, measurement: "measured", matching_must: [], gap_must: ["java"] },
  },
  profile_key: "0:default",
};

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const pair = () => [
  { id: 1, name: "Anna Przykładowa" },
  { id: 2, name: "Jan Testowy" },
];

describe("CandidateCompareModal", () => {
  beforeEach(() => {
    matchScores.mockReset();
  });

  it("compares the measured candidates side by side", async () => {
    matchScores.mockResolvedValue(measured);
    const client = new QueryClient();
    render(<CandidateCompareModal jobId={9} candidates={pair()} onClose={() => {}} />, {
      wrapper: wrapper(client),
    });

    expect(await screen.findByText("81")).toBeInTheDocument();
    expect(screen.getByText("java")).toBeInTheDocument();
    const [jobId, ids, options] = matchScores.mock.calls[0];
    expect([jobId, ids]).toEqual([9, [1, 2]]);
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });

  it("a failed measurement is an error with 'Ponów', never 'Brak kryteriów'", async () => {
    matchScores.mockRejectedValueOnce(httpError(500)).mockResolvedValueOnce(measured);
    render(<CandidateCompareModal jobId={9} candidates={pair()} onClose={() => {}} />, {
      wrapper: wrapper(new QueryClient()),
    });

    expect(await screen.findByText("Nie udało się policzyć dopasowania.")).toBeInTheDocument();
    expect(screen.queryByText(/Brak kryteriów do porównania/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Ponów/ }));

    expect(await screen.findByText("81")).toBeInTheDocument();
    expect(matchScores).toHaveBeenCalledTimes(2);
  });

  it("no access is said as such, without a retry that cannot help", async () => {
    matchScores.mockRejectedValue(httpError(403));
    render(<CandidateCompareModal jobId={9} candidates={pair()} onClose={() => {}} />, {
      wrapper: wrapper(new QueryClient()),
    });

    expect(
      await screen.findByText("Brak dostępu do oceny dopasowania dla tej rekrutacji."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ponów/ })).not.toBeInTheDocument();
    expect(matchScores).toHaveBeenCalledTimes(1);
  });

  it("the parent re-rendering with a new array of the same ids does not re-measure", async () => {
    matchScores.mockResolvedValue(measured);
    const client = new QueryClient();
    const { rerender } = render(
      <CandidateCompareModal jobId={9} candidates={pair()} onClose={() => {}} />,
      { wrapper: wrapper(client) },
    );
    await screen.findByText("81");

    for (let i = 0; i < 3; i += 1) {
      rerender(<CandidateCompareModal jobId={9} candidates={pair()} onClose={() => {}} />);
    }
    await waitFor(() => expect(screen.getByText("81")).toBeInTheDocument());

    expect(matchScores).toHaveBeenCalledTimes(1);
  });

  it("closing the modal cancels the measurement in flight", async () => {
    matchScores.mockImplementation(() => new Promise(() => {}));
    const { unmount } = render(
      <CandidateCompareModal jobId={9} candidates={pair()} onClose={() => {}} />,
      { wrapper: wrapper(new QueryClient()) },
    );
    await waitFor(() => expect(matchScores).toHaveBeenCalledTimes(1));
    const { signal } = matchScores.mock.calls[0][2] as { signal: AbortSignal };

    unmount();

    await waitFor(() => expect(signal.aborted).toBe(true));
  });
});
