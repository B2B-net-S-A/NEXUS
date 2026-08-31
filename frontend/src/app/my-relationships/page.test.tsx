import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MyRelationshipsPage from "./page";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  user: { role: "finance", roles: ["finance"] },
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user }),
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

vi.mock("@/components/KeyRelationshipDialog", () => ({
  KeyRelationshipDialog: () => <div>Edytor relacji</div>,
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MyRelationshipsPage />
    </QueryClientProvider>,
  );
}

describe("MyRelationshipsPage — Finance read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({
      data: [
        {
          contact_id: 9,
          name: "Anna Kowalska",
          position: "Hiring Manager",
          email: "anna@example.com",
          phone: "+48 500 000 000",
          client_id: 3,
          client_name: "Klient Testowy",
          is_decision_maker: true,
          relationship_strength: "champion",
          relationship_notes: "Kluczowa relacja",
          last_personal_touchpoint_at: null,
          last_contacted_at: null,
          days_since_personal_touchpoint: null,
        },
      ],
    });
  });

  it("pokazuje relacje z całej organizacji bez akcji aktualizacji", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Kluczowe relacje w organizacji",
      }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Anna Kowalska")).toBeInTheDocument();
    expect(screen.getByText("Klient Testowy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aktualizuj" })).not.toBeInTheDocument();
    expect(screen.queryByText("Edytor relacji")).not.toBeInTheDocument();
  });
});
