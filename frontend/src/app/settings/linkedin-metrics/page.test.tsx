import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminLinkedInMetricsPage from "./page";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  get: vi.fn(),
  post: vi.fn(),
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
  default: {
    get: mocks.get,
    post: mocks.post,
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
      <AdminLinkedInMetricsPage />
    </QueryClientProvider>,
  );
}

describe("AdminLinkedInMetricsPage — Insights RBAC", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/linkedin-metrics/users") {
        return {
          data: [{ id: 7, name: "Test Sourcer", role: "sourcer" }],
        };
      }
      if (url === "/api/linkedin-metrics/batch") return { data: [] };
      throw new Error(`unexpected GET ${url}`);
    });
    mocks.post.mockResolvedValue({ data: { saved: 1 } });
  });

  it("pozwala uprawnionej roli z Insights read wejść wyłącznie w tryb podglądu", async () => {
    mocks.user = {
      role: "head_of_recruitment",
      roles: ["head_of_recruitment"],
      effective_section_access: { insights: "read" },
    };

    renderPage();

    expect(await screen.findByText("Test Sourcer")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn metrics · podgląd")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Zapisz wszystkie" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).not.toHaveLength(0);
    expect(screen.getAllByRole("spinbutton").every((input) => input.hasAttribute("disabled"))).toBe(
      true,
    );
  });

  it("pokazuje edycję dopiero dla istniejącej roli z Insights write", async () => {
    mocks.user = {
      role: "head_of_recruitment",
      roles: ["head_of_recruitment"],
      effective_section_access: { insights: "write" },
    };

    renderPage();

    expect(await screen.findByText("Test Sourcer")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zapisz wszystkie" }),
    ).toBeInTheDocument();
    expect(screen.getByText("LinkedIn metrics · edycja")).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton").some((input) => !input.hasAttribute("disabled"))).toBe(
      true,
    );
  });

  it("odcina nawet właściwą rolę, jeśli indywidualna polityka odbiera Insights", async () => {
    mocks.user = {
      role: "finance",
      roles: ["finance"],
      effective_section_access: { insights: "none" },
    };

    renderPage();

    expect(screen.getByText("Brak dostępu")).toBeInTheDocument();
    await waitFor(() => expect(mocks.get).not.toHaveBeenCalled());
  });
});
