/**
 * UAT B41: duże pule talentów pokazywały pierwszych 500 członków z dopiskiem
 * „pokazano 500 z 817" — i żadnej drogi do pozostałych 317. Backend od zawsze
 * miał `limit`/`offset`; widok ich nie przekazywał.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  getCandidates: vi.fn(),
  ccList: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  talentPoolsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    getCandidates: (...args: unknown[]) => mocks.getCandidates(...args),
    removeCandidate: vi.fn(),
    deletePool: vi.fn(),
    create: vi.fn(),
  },
  competenceCategoriesApi: { list: (...args: unknown[]) => mocks.ccList(...args) },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number; role: string } }) => unknown) =>
    selector({ user: { id: 7, role: "admin" } }),
  hasRole: () => true,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import TalentsPage from "@/app/talents/page";

const POOL = {
  id: 3,
  name: "Java",
  description: null,
  candidate_count: 3,
  created_at: "2026-01-01T00:00:00Z",
  criteria: null,
  competence_category_id: null,
  competence_category_slug: null,
  is_personal: false,
  owner_id: null,
  owner_name: null,
};

function member(id: number) {
  return {
    id,
    name: "Jan",
    lastname: `Testowy${id}`,
    email: null,
    location: null,
    competence_category: null,
    skills: [],
    status: "active",
    added_at: "2026-01-01T00:00:00Z",
    source_event: null,
    source_job_id: null,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TalentsPage />
    </QueryClientProvider>,
  );
}

describe('pula talentów — „Pokaż więcej" (UAT B41)', () => {
  beforeEach(() => {
    mocks.list.mockResolvedValue({ data: [POOL] });
    mocks.ccList.mockResolvedValue([]);
    mocks.getCandidates.mockReset();
  });

  it("doładowuje kolejnych członków z offsetem i wysyła limit/offset do API", async () => {
    mocks.getCandidates.mockImplementation(
      async (_poolId: number, params: { offset?: number }) => ({
        data:
          (params?.offset ?? 0) === 0
            ? { candidates: [member(1), member(2)], total: 3, returned: 2, limit: 500, offset: 0 }
            : { candidates: [member(3)], total: 3, returned: 1, limit: 500, offset: 2 },
      }),
    );
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Java/ }));

    expect(await screen.findByText("Jan Testowy1")).toBeInTheDocument();
    expect(screen.getByText("pokazano 2 z 3")).toBeInTheDocument();
    expect(mocks.getCandidates).toHaveBeenCalledWith(3, { limit: 500, offset: 0 });

    await user.click(screen.getByTestId("pool-load-more"));

    expect(await screen.findByText("Jan Testowy3")).toBeInTheDocument();
    expect(mocks.getCandidates).toHaveBeenLastCalledWith(3, { limit: 500, offset: 2 });
    // Pierwsze okno zostaje — doklejamy, nie zastępujemy.
    expect(screen.getByText("Jan Testowy1")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("pool-load-more")).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(/pokazano/)).not.toBeInTheDocument();
  });

  it("nie pokazuje przycisku, gdy wszyscy członkowie są już na liście", async () => {
    mocks.getCandidates.mockResolvedValue({
      data: { candidates: [member(1)], total: 1, returned: 1, limit: 500, offset: 0 },
    });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Java/ }));

    expect(await screen.findByText("Jan Testowy1")).toBeInTheDocument();
    expect(screen.queryByTestId("pool-load-more")).not.toBeInTheDocument();
  });
});
