/**
 * Pusta kolejka nie znaczy „porcja przejrzana”: rekruter, który na całej porcji
 * wcisnął „Do screeningu”, nadal ma blokadę 423 i musi widzieć, co domknąć.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchScreen } from "@/components/v2/review-batch/ReviewBatchScreen";
import type { ReviewBatchStatus } from "@/lib/api/reviewBatch";

const api = vi.hoisted(() => ({
  status: {} as Record<string, unknown>,
  queue: {} as Record<string, unknown>,
}));

vi.mock("@tanstack/react-query", async (original) => ({
  ...(await original<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({}),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));
vi.mock("@/components/v2/review-batch/ReviewBatchCard", () => ({
  ReviewBatchCard: () => <div data-testid="review-batch-card" />,
}));
vi.mock("@/lib/api/reviewBatch", () => ({
  addMoreFromNexus: vi.fn(),
  invalidateReviewBatch: vi.fn(),
  useReviewBatchStatus: () => api.status,
  useReviewBatchQueue: () => api.queue,
}));

const blocked: ReviewBatchStatus = {
  enabled: true,
  applies: true,
  minimum: 10,
  done_today: 0,
  pending: 0,
  required: 10,
  remaining: 10,
  met: false,
  blocks: true,
  open_screenings: 2,
  open_today_screenings: [
    { job_id: 11, job_title: "Java Developer", candidate_id: 101, name: "Jan Testowy" },
    { job_id: 12, job_title: "Analityk", candidate_id: 102, name: "Ewa Próbna" },
  ],
  jobs: [],
  team_jobs: [{ job_id: 11, title: "Java Developer", pending: 0, p0: false }],
};

function given(status: Partial<ReviewBatchStatus>, queue: Record<string, unknown> = {}) {
  api.status = { isPending: false, isError: false, data: { ...blocked, ...status } };
  api.queue = { data: { items: [] }, isLoading: false, isError: false, isSuccess: true, ...queue };
}

describe("ReviewBatchScreen przy pustej kolejce", () => {
  beforeEach(() => given({}));

  it("przy niezrobionym minimum pokazuje dzisiejsze screeningi z linkami do Tablicy", () => {
    render(<ReviewBatchScreen />);
    expect(screen.queryByText(/Porcja przejrzana/)).toBeNull();
    expect(screen.getByRole("link", { name: /Jan Testowy/ }).getAttribute("href")).toBe(
      "/jobs/11?candidate=101",
    );
    expect(screen.getByRole("link", { name: /Ewa Próbna/ }).getAttribute("href")).toBe(
      "/jobs/12?candidate=102",
    );
    expect(screen.getByTestId("review-batch-open-today").textContent).toMatch(/brakuje 10 decyzji/);
  });

  it("wskazuje dobranie kolejnych osób, gdy jest z czego dobrać", () => {
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-open-today").textContent).toMatch(/Dodaj .* kolejnych/);
  });

  it("nie obiecuje dobrania, gdy żadna rekrutacja nie jest przejrzana do końca", () => {
    given({ team_jobs: [] });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-open-today").textContent).not.toMatch(/kolejnych/);
  });

  it("bez listy i bez minimum nie twierdzi, że porcja jest przejrzana", () => {
    given({ open_today_screenings: [], team_jobs: [] });
    render(<ReviewBatchScreen />);
    expect(screen.queryByText(/Porcja przejrzana/)).toBeNull();
    expect(screen.getByTestId("review-batch-empty").textContent).toMatch(/minimum/i);
  });

  it("po zrobionym minimum zostaje „Porcja przejrzana”", () => {
    given({ met: true, done_today: 10, remaining: 0, open_today_screenings: [] });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-empty").textContent).toMatch(/Porcja przejrzana/);
  });

  it("w przerwie między ponowieniami zapytania nie pokazuje pustego stanu", () => {
    given({}, { data: undefined, isLoading: false, isError: false, isSuccess: false });
    render(<ReviewBatchScreen />);
    expect(screen.queryByTestId("review-batch-open-today")).toBeNull();
    expect(screen.queryByTestId("review-batch-empty")).toBeNull();
    expect(screen.getByText("Ładowanie osób…")).toBeTruthy();
  });

  it("awaria kolejki nie wygląda jak pusta porcja", () => {
    given({}, { data: undefined, isError: true, isSuccess: false, error: new Error("x") });
    render(<ReviewBatchScreen />);
    expect(screen.getByRole("alert").textContent).toMatch(/Nie udało się/);
    expect(screen.queryByTestId("review-batch-open-today")).toBeNull();
  });
});
