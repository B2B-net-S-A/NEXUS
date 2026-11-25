import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EmailTemplatesCard from "../EmailTemplatesCard";

const mocks = vi.hoisted(() => ({ list: vi.fn(), delete: vi.fn() }));

vi.mock("@/lib/api", () => ({
  userEmailTemplatesApi: { list: mocks.list, delete: mocks.delete },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: { id: 1, role: "recruiter" } }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    Boolean(user?.role && roles.includes(user.role)),
}));

const EMPTY = /Brak szablonów/;

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <EmailTemplatesCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("EmailTemplatesCard — awaria listy to nie pusta lista (audyt r3, 24.11.2026)", () => {
  it("przy błędzie pobrania mówi o nim i daje ponowienie zamiast „Brak szablonów”", async () => {
    mocks.list.mockRejectedValue({
      response: { status: 500, data: { detail: "Baza chwilowo niedostępna." } },
    });
    renderCard();

    expect(await screen.findByText("Baza chwilowo niedostępna.")).toBeInTheDocument();
    expect(screen.queryByText(EMPTY)).not.toBeInTheDocument();

    mocks.list.mockResolvedValue({ data: [] });
    await userEvent.setup().click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    await waitFor(() => expect(screen.getByText(EMPTY)).toBeInTheDocument());
    expect(mocks.list).toHaveBeenCalledTimes(2);
  });

  it("pusta lista z serwera pokazuje „Brak szablonów”", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    renderCard();

    expect(await screen.findByText(EMPTY)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Spróbuj ponownie/ })).not.toBeInTheDocument();
  });
});
