/**
 * Licznik porcji w pasku stoi na każdej stronie. Do 18.11.2026 odpytywał
 * `GET /api/review-batch/me` co 120 s (literał), w szczycie 698 wywołań
 * w 82 min. Teraz interwał to stała z `lib/polling.ts`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchTopbarButton } from "@/components/v2/review-batch/ReviewBatchTopbarButton";
import { REVIEW_BATCH_STATUS_POLL_MS } from "@/lib/polling";

const getMock = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  const api = { get: (...args: unknown[]) => getMock(...args) };
  return { ...actual, api, default: api };
});
vi.mock("@/lib/section-access", async (original) => ({
  ...(await original<typeof import("@/lib/section-access")>()),
  hasSectionAccess: () => true,
}));

const status = {
  enabled: true,
  applies: true,
  minimum: 10,
  done_today: 3,
  pending: 7,
  required: 10,
  remaining: 7,
  met: false,
  jobs: [],
  team_jobs: [],
};

function renderButton() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReviewBatchTopbarButton />
    </QueryClientProvider>,
  );
}

describe("ReviewBatchTopbarButton — odpytywanie", () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockResolvedValue({ data: status });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("nie pyta co 2 min, tylko co REVIEW_BATCH_STATUS_POLL_MS", async () => {
    const view = renderButton();
    await vi.advanceTimersByTimeAsync(0);
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock).toHaveBeenCalledWith("/api/review-batch/me");
    expect(view.getByTestId("review-batch-topbar").textContent).toContain("3/10");

    await vi.advanceTimersByTimeAsync(120_000);
    expect(getMock).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(REVIEW_BATCH_STATUS_POLL_MS - 120_000);
    expect(getMock).toHaveBeenCalledTimes(2);
  });
});
