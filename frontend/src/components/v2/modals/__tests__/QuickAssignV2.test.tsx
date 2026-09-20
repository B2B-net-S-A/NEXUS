import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  jobsList: vi.fn(),
  forCandidate: vi.fn(),
  assignToJob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  jobsApi: { list: (...args: unknown[]) => mocks.jobsList(...args) },
  recommendationsApi: {
    forCandidate: (...args: unknown[]) => mocks.forCandidate(...args),
    assignToJob: (...args: unknown[]) => mocks.assignToJob(...args),
  },
}));

vi.mock("@/components/v2/RiskBadge", () => ({ RiskBadge: () => null }));

import { QuickAssignV2 } from "@/components/v2/modals/QuickAssignV2";
import { useTabsStore } from "@/store/tabs";

function renderSheet() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <QuickAssignV2 open onOpenChange={vi.fn()} candidateId={5} candidateName="Anna Nowak" />
    </QueryClientProvider>,
  );
}

describe("QuickAssignV2 (C5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTabsStore.setState({
      tabs: [{ id: "job-9", type: "job", entityId: 9, title: "Ostatnia rekrutacja", url: "/jobs/9" }],
      activeTabId: null,
    });
    mocks.apiGet.mockImplementation((url: string) =>
      url === "/api/jobs"
        ? Promise.resolve({ data: { items: [{ id: 3, title: "Rekrutacja z listy" }] } })
        : Promise.resolve({ data: null }),
    );
    mocks.jobsList.mockResolvedValue({ data: { items: [{ id: 1, title: "Moja rekrutacja" }] } });
    mocks.forCandidate.mockResolvedValue({
      data: { matches: [{ job: { id: 4, title: "Sugestia" }, total_score: null }], meta: { mode: "bm25", degraded: true, reason: null } },
    });
    mocks.assignToJob.mockResolvedValue({ data: {} });
  });

  it("otwiera się na „Wszystkie” z sekcjami „Moje otwarte” i „Ostatnio otwierane” nad listą", async () => {
    renderSheet();
    expect(screen.getByRole("tab", { name: /Wszystkie/ })).toHaveAttribute("aria-selected", "true");
    const mine = await screen.findByRole("region", { name: "Moje otwarte" });
    expect(await within(mine).findByText("Moja rekrutacja")).toBeInTheDocument();
    expect(mocks.jobsList).toHaveBeenCalledWith({ mine: true, open_only: true, page_size: 20 });
    expect(within(screen.getByRole("region", { name: "Ostatnio otwierane" })).getByText("Ostatnia rekrutacja")).toBeInTheDocument();
    expect(await screen.findByText("Rekrutacja z listy")).toBeInTheDocument();

    fireEvent.click(within(mine).getByRole("button", { name: "Przypisz" }));
    await waitFor(() => expect(mocks.assignToJob).toHaveBeenCalledWith(5, 1));
  });

  it("po wpisaniu frazy skróty znikają", async () => {
    renderSheet();
    await screen.findByRole("region", { name: "Moje otwarte" });
    fireEvent.change(screen.getByPlaceholderText("Szukaj po tytule rekrutacji…"), { target: { value: "java" } });
    expect(screen.queryByRole("region", { name: "Moje otwarte" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ostatnio otwierane" })).not.toBeInTheDocument();
  });

  it("ranking awaryjny opisany zwykłym językiem, bez „BM25”", async () => {
    renderSheet();
    fireEvent.mouseDown(screen.getByRole("tab", { name: /AI sugestie/ }));
    expect(await screen.findByText("Ranking uproszczony (bez AI).")).toBeInTheDocument();
    expect(screen.queryByText(/BM25/)).not.toBeInTheDocument();
  });
});
