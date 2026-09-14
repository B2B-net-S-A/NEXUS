/**
 * UAT B06: „Szukają projektu" kończyło się na pierwszych 50 osobach —
 * „50 z 2890 konsultantów" i żadnej drogi do reszty poza zgadywaniem filtrów.
 *
 * Test idzie przez react-query i prawdziwy komponent: przycisk „Pokaż
 * kolejnych" ma wysłać `offset` równy liczbie już wczytanych wierszy i DOKLEIĆ
 * następne okno do listy, nie zastąpić nim pierwszego.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  seekingContractors: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  recommendationsApi: {
    seekingContractors: (...args: unknown[]) => mocks.seekingContractors(...args),
  },
}));

vi.mock("@/components/sourcing/ContractorMatchCard", () => ({
  ContractorMatchCard: ({ row }: { row: { candidate: { id: number } } }) => (
    <div data-testid="contractor-card">{row.candidate.id}</div>
  ),
}));
vi.mock("@/components/sourcing/RecommendationFiltersBar", () => ({
  RecommendationFiltersBar: () => <div />,
}));

import {
  nextSeekingOffset,
  SeekingContractorsBoard,
} from "@/components/sourcing/SeekingContractorsBoard";

function row(id: number) {
  return {
    candidate: {
      id,
      name: "Jan",
      lastname: `Testowy-${id}`,
      email: null,
      location: null,
      competence_category: null,
      years_it_experience: null,
      availability_status: "actively_looking",
      champion: false,
      avatar_url: null,
    },
    source: "availability_status" as const,
    contract_end_date: null,
    current_client_id: null,
    top_matches: [],
    below_threshold_count: 0,
  };
}

function page(ids: number[], total: number, offset: number) {
  return {
    horizon_days: 30,
    total,
    returned: ids.length,
    truncated: offset + ids.length < total,
    offset,
    items: ids.map(row),
    meta: { degraded: false, reason: null },
  };
}

function renderBoard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SeekingContractorsBoard />
    </QueryClientProvider>,
  );
}

describe('SeekingContractorsBoard — „Pokaż kolejnych" (UAT B06)', () => {
  beforeEach(() => {
    mocks.seekingContractors.mockReset();
  });

  it("dokleja następne okno z offsetem równym liczbie wczytanych wierszy", async () => {
    mocks.seekingContractors.mockImplementation(
      async (params: { offset?: number }) => ({
        data:
          (params.offset ?? 0) === 0
            ? page([1, 2], 3, 0)
            : page([3], 3, params.offset ?? 0),
      }),
    );
    const user = userEvent.setup({ delay: null });
    renderBoard();

    expect(await screen.findAllByTestId("contractor-card")).toHaveLength(2);
    expect(screen.getByText("2 z 3 konsultantów w horyzoncie 30 dni")).toBeInTheDocument();
    const more = screen.getByTestId("load-more");
    expect(more).toHaveTextContent("Pokaż kolejnych 1");

    await user.click(more);

    await waitFor(() =>
      expect(screen.getAllByTestId("contractor-card")).toHaveLength(3),
    );
    expect(mocks.seekingContractors).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 2, page_size: 50 }),
    );
    // Pierwsze okno zostało — doklejamy, nie zastępujemy.
    expect(screen.getAllByTestId("contractor-card").map((n) => n.textContent)).toEqual([
      "1",
      "2",
      "3",
    ]);
    expect(screen.getByText("3 konsultantów w horyzoncie 30 dni")).toBeInTheDocument();
    expect(screen.queryByTestId("load-more")).not.toBeInTheDocument();
  });

  it("nie pokazuje przycisku, gdy lista nie jest przycięta", async () => {
    mocks.seekingContractors.mockResolvedValue({ data: page([1, 2], 2, 0) });
    renderBoard();

    expect(await screen.findAllByTestId("contractor-card")).toHaveLength(2);
    expect(screen.queryByTestId("load-more")).not.toBeInTheDocument();
  });

  it("starszy backend bez `offset` w odpowiedzi nie dostaje przycisku (ta sama strona w kółko)", () => {
    const legacy = { ...page([1, 2], 50, 0), offset: undefined, truncated: true };
    expect(nextSeekingOffset(legacy, [legacy])).toBeUndefined();
    const current = page([1, 2], 50, 0);
    expect(nextSeekingOffset(current, [current])).toBe(2);
    expect(nextSeekingOffset(page([3], 3, 2), [current, page([3], 3, 2)])).toBeUndefined();
  });
});
