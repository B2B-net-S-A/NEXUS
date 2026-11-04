import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidateEmailTemplates } from "../CandidateEmailTemplates";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.get, post: mocks.post, delete: mocks.delete },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 1, role: "admin" } }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    Boolean(user?.role && roles.includes(user.role)),
}));

function renderTemplates() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CandidateEmailTemplates />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CandidateEmailTemplates — awaria listy to nie pusta lista (21.10.2026)", () => {
  it("przy błędzie pobrania mówi o nim i nie proponuje domyślnych szablonów", async () => {
    mocks.get.mockRejectedValue({ response: { status: 500, data: {} } });
    renderTemplates();

    expect(await screen.findByText("Nie udało się pobrać szablonów maili.")).toBeInTheDocument();
    expect(screen.queryByText("Brak szablonów")).not.toBeInTheDocument();
    expect(screen.queryByText("Dodaj domyślne →")).not.toBeInTheDocument();
    expect(screen.queryByText("Dodaj domyślne szablony")).not.toBeInTheDocument();

    mocks.get.mockResolvedValue({ data: [] });
    await userEvent.setup().click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    await waitFor(() => expect(screen.getByText("Brak szablonów")).toBeInTheDocument());
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  it("pusta lista z serwera dalej proponuje domyślne szablony", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    renderTemplates();

    expect(await screen.findByText("Brak szablonów")).toBeInTheDocument();
    expect(screen.getByText("Dodaj domyślne →")).toBeInTheDocument();
  });
});
