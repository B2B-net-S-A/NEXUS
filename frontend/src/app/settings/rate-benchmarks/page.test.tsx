import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RateBenchmarksPage from "./page";

const mocks = vi.hoisted(() => ({
  user: { role: "finance", roles: ["finance"] },
  list: vi.fn(),
  create: vi.fn(),
  delete: vi.fn(),
  importCsv: vi.fn(),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, hydrated: true }),
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

vi.mock("@/lib/api", () => ({
  rateBenchmarksApi: {
    list: mocks.list,
    create: mocks.create,
    delete: mocks.delete,
    importCsv: mocks.importCsv,
  },
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RateBenchmarksPage />
    </QueryClientProvider>,
  );
}

describe("RateBenchmarksPage — Finance read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: [
        {
          id: 1,
          role: "Java Developer",
          seniority: "senior",
          currency: "PLN",
          rate_unit: "daily",
          market_min: 1000,
          market_median: 1200,
          market_max: 1400,
          location: "Warszawa",
          source: "Raport testowy",
          source_date: "2026-08-01",
          notes: null,
        },
      ],
    });
  });

  it("pokazuje min, medianę i max, ale ukrywa import/dodawanie/usuwanie", async () => {
    const { container } = renderPage();

    expect(await screen.findByText("Java Developer")).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0]?000/)).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0]?200/)).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0]?400/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Import CSV/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Dodaj$/i })).not.toBeInTheDocument();
    expect(container.querySelector('input[type="file"]')).not.toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
    expect(mocks.importCsv).not.toHaveBeenCalled();
  });
});
