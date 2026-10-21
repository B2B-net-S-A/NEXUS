import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ScoringWeightsPage from "./page";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
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
  scoringWeightsApi: {
    list: mocks.list,
    create: mocks.create,
    update: mocks.update,
    remove: mocks.remove,
  },
}));

const PROFILE = {
  id: 11,
  name: "Profil testowy",
  user_id: null,
  client_id: null,
  weights: {
    semantic: 35,
    skills: 30,
    salary: 12,
    location: 8,
    availability: 5,
    champion_fit: 10,
  },
  active: true,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ScoringWeightsPage />
    </QueryClientProvider>,
  );
}

describe("ScoringWeightsPage — Insights RBAC", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: [PROFILE] });
  });

  it("Delivery Lead z Insights read widzi profile bez akcji zapisu", async () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "read" },
    };

    renderPage();

    expect(await screen.findByText("Profil testowy")).toBeInTheDocument();
    expect(screen.getByText(/Tryb podglądu/)).toBeInTheDocument();
    expect(
      screen.queryByTestId("add-scoring-weight-profile"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edytuj" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń")).not.toBeInTheDocument();
  });

  it("admin z samym Insights read również nie dostaje mutacji UI", async () => {
    mocks.user = {
      role: "admin",
      roles: ["admin"],
      effective_section_access: { insights: "read" },
    };

    renderPage();

    expect(await screen.findByText("Profil testowy")).toBeInTheDocument();
    expect(
      screen.queryByTestId("add-scoring-weight-profile"),
    ).not.toBeInTheDocument();
  });

  it("mutacje pokazuje tylko adminowi z Insights write", async () => {
    mocks.user = {
      role: "admin",
      roles: ["admin"],
      effective_section_access: { insights: "write" },
    };

    renderPage();

    expect(await screen.findByText("Profil testowy")).toBeInTheDocument();
    expect(screen.getByTestId("add-scoring-weight-profile")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edytuj" })).toBeInTheDocument();
    expect(screen.getByTitle("Usuń")).toBeInTheDocument();
  });

  it("nie odpala odczytu bez Insights read", async () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "none" },
    };

    renderPage();

    expect(screen.getByText("Brak dostępu do profili wag scoringu.")).toBeInTheDocument();
    await waitFor(() => expect(mocks.list).not.toHaveBeenCalled());
  });

  it("„Dop.” po ludzku i z udziałem, jaki liczy silnik — bez nazw pól z kodu (21.10.2026)", async () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "read" },
    };
    renderPage();

    const section = await screen.findByRole("region", {
      name: "Z czego składa się „Dop.” — dla wszystkich rekrutacji",
    });
    const rows = Array.from(section.querySelectorAll("li")).map((li) => [
      li.querySelector("p")?.textContent,
      li.querySelector("span.tabular-nums")?.textContent,
    ]);
    // 60/10/15/5/0 z 90 (bez wyniku screeningu) — jak base_fit_profile w backendzie.
    expect(rows).toEqual([
      ["Podobieństwo CV do rekrutacji", "67%"],
      ["Umiejętności", "11%"],
      ["Lokalizacja i tryb pracy", "6%"],
      ["Stawka", "17%"],
      ["Dostępność", "0%"],
    ]);
    expect(section).toHaveTextContent("wynik screeningu nie wchodzi do „Dop.”");
    expect(screen.queryByText(/semantic|boost|tunowanie/)).toBeNull();
  });
});
