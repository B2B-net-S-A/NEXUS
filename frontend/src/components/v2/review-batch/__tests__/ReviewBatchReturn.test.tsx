/**
 * „Oddaj do Nowych” w „Do domknięcia” (decyzja Artura 24.11.2026): screening
 * z rekrutacji poniżej najwyższego priorytetu osoby wraca do „Nowych” bez
 * odrzucenia, zamiast hurtowego „Inne — odrzucam, żeby móc szukać”.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchScreen } from "@/components/v2/review-batch/ReviewBatchScreen";
import type { ReviewBatchStatus } from "@/lib/api/reviewBatch";

const api = vi.hoisted(() => ({ status: {} as Record<string, unknown> }));
const send = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn() }));
const invalidate = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-query", async (original) => ({
  ...(await original<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({}),
}));
vi.mock("@/hooks/useNoAnswerNote", () => ({
  useNoAnswerNote: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
// Podgląd CV ładuje się przez `dynamic()`: przy obciążonym CI chunk zdążał się
// wczytać w trakcie testu i panel wołał prawdziwe `useQuery` („No QueryClient
// set”, 25.11.2026). Ekran Porcji testujemy bez niego.
vi.mock("@/components/v2/screening-form/CandidatePreviewPane", () => ({
  CandidatePreviewPane: () => <div data-testid="candidate-preview" />,
}));
vi.mock("@/components/v2/review-batch/ReviewBatchCard", () => ({
  ReviewBatchCard: () => <div data-testid="review-batch-card" />,
}));
vi.mock("@/lib/api/plainKnowledge", () => ({ usePlainBrief: () => ({ data: null }) }));
vi.mock("@/lib/api/reviewBatch", () => ({
  addMoreFromNexus: vi.fn(),
  invalidateReviewBatch: invalidate,
  useReviewBatchStatus: () => api.status,
  useReviewBatchQueue: () => ({ data: { items: [] }, isLoading: false, isError: false, isSuccess: true }),
}));

const base: ReviewBatchStatus = {
  enabled: true,
  applies: true,
  minimum: 10,
  done_today: 10,
  pending: 0,
  required: 10,
  remaining: 0,
  met: false,
  blocks: true,
  overdue_screenings: 3,
  // Kolejność z serwera: najpierw niższy priorytet — ekran ma ją odwrócić.
  open_today_screenings: [
    { job_id: 12, job_title: "Spark Developer", candidate_id: 201, name: "Ola Pierwsza", overdue: true },
    { job_id: 11, job_title: "Architekt", candidate_id: 101, name: "Jan Testowy", overdue: true },
    { job_id: 12, job_title: "Spark Developer", candidate_id: 202, name: "Piotr Drugi", overdue: true },
  ],
  jobs: [],
  team_jobs: [
    { job_id: 11, title: "Architekt", pending: 0, p0: true, group: "p0" },
    { job_id: 12, title: "Spark Developer", pending: 0, p0: false, group: "p1" },
  ],
};

function given(status: Partial<ReviewBatchStatus> = {}) {
  api.status = { isPending: false, isError: false, data: { ...base, ...status } };
}

function openCloseTab() {
  render(<ReviewBatchScreen />);
  fireEvent.click(screen.getByRole("tab", { name: /Do domknięcia/ }));
  return screen.getByTestId("review-batch-open-today");
}

describe("„Oddaj do Nowych” w „Do domknięcia”", () => {
  beforeEach(() => {
    given();
    send.mockReset();
    send.mockResolvedValue({ ok: true, data: {} });
    toast.showError.mockReset();
    toast.showSuccess.mockReset();
    invalidate.mockReset();
  });

  it("grupuje po rekrutacji, P0 na górze, a zbiorcze oddanie stoi tylko przy niższym priorytecie", () => {
    const list = openCloseTab();
    const groups = screen.getAllByTestId("review-batch-close-group");
    expect(groups.map((g) => g.textContent)).toEqual([
      expect.stringMatching(/^P0Architekt1 po terminie · 1$/),
      expect.stringMatching(/^P1 PilneSpark Developer2 po terminie · 2Nie jest teraz Twoim P0/),
    ]);
    expect(list.textContent).toMatch(/Architekt.*Jan Testowy.*Spark Developer.*Ola Pierwsza.*Piotr Drugi/);
    expect(within(groups[0]).queryByRole("button", { name: /Oddaj/ })).toBeNull();
    expect(within(groups[1]).getByRole("button", { name: "Oddaj 2 do Nowych" })).toBeTruthy();
  });

  it("zbiorcze oddanie pyta o zgodę i przesuwa każdą osobę do „Nowych”", async () => {
    openCloseTab();
    fireEvent.click(screen.getByRole("button", { name: "Oddaj 2 do Nowych" }));
    expect(send).not.toHaveBeenCalled();
    expect(screen.getByText(/bez odrzucenia/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Oddaj 2" }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls.map(([payload]) => payload)).toEqual([
      { candidate_id: 201, job_id: 12, stage: "new" },
      { candidate_id: 202, job_id: 12, stage: "new" },
    ]);
    await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith("Oddano do „Nowych”: 2. Bez odrzucenia."));
    expect(invalidate).toHaveBeenCalled();
  });

  it("„Anuluj” w oknie niczego nie rusza", async () => {
    openCloseTab();
    fireEvent.click(screen.getByRole("button", { name: "Oddaj 2 do Nowych" }));
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByText(/bez odrzucenia/)).toBeNull());
    expect(send).not.toHaveBeenCalled();
  });

  it("pojedyncza osoba wraca bez okna, także w P0", async () => {
    openCloseTab();
    fireEvent.click(screen.getByRole("button", { name: "Oddaj do Nowych" }));
    await waitFor(() => expect(send).toHaveBeenCalledWith({ candidate_id: 101, job_id: 11, stage: "new" }));
  });

  it("odmowa ruchu nie udaje sukcesu", async () => {
    send.mockResolvedValue({ ok: false, refusal: { kind: "error" } });
    openCloseTab();
    fireEvent.click(screen.getByRole("button", { name: "Oddaj do Nowych" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith("Oddano 0 z 1. Pozostałe zostały w „Do domknięcia”."));
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });

  it("gdy wszystkie screeningi są z najwyższego priorytetu, nie ma zbiorczego oddania", () => {
    given({
      open_today_screenings: [
        { job_id: 11, job_title: "Architekt", candidate_id: 101, name: "Jan Testowy", overdue: true },
      ],
    });
    openCloseTab();
    expect(screen.queryByRole("button", { name: /Oddaj \d+ do Nowych/ })).toBeNull();
  });
});
