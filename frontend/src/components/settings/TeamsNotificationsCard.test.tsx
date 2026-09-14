import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  list: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  teamsChannelsApi: {
    list: mocks.list,
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    test: vi.fn(),
  },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user }),
  hasRole: (user: { roles?: string[] } | null, ...roles: string[]) =>
    !!user && roles.some((role) => (user.roles ?? []).includes(role)),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import TeamsNotificationsCard from "./TeamsNotificationsCard";

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TeamsNotificationsCard />
    </QueryClientProvider>,
  );
}

// UAT A-B03: rola bez prawa widziała „Brak skonfigurowanych kanałów"
// i formularz, choć API zwracało 403.
describe("TeamsNotificationsCard — dostęp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue([]);
  });

  it("rola nie-admin dostaje odmowę zamiast pustej listy i formularza", () => {
    mocks.user = { role: "recruiter", roles: ["recruiter"] };
    renderCard();

    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(
      screen.queryByText(/Brak skonfigurowanych kanałów/),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj kanał/ })).toBeNull();
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it("admin widzi pusty stan i formularz", async () => {
    mocks.user = { role: "admin", roles: ["admin"] };
    renderCard();

    expect(
      await screen.findByText(/Brak skonfigurowanych kanałów/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dodaj kanał/ })).toBeInTheDocument();
  });
});
