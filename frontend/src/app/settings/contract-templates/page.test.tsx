import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContractTemplatesPage from "./page";

const mocks = vi.hoisted(() => ({
  user: { role: "admin", roles: ["admin"] } as Record<string, unknown>,
  get: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, hydrated: true }),
  hasRole: (user: { role?: string; roles?: string[] } | null, ...roles: string[]) =>
    !!user && roles.some((role) => new Set([user.role, ...(user.roles ?? [])]).has(role)),
}));
vi.mock("@/components/RequireRole", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: vi.fn(), confirmDialog: null }),
}));
vi.mock("@/lib/api", () => ({
  default: { get: mocks.get, patch: mocks.patch, delete: mocks.del, post: vi.fn(), put: vi.fn() },
}));

const TEMPLATES = [
  { id: 1, name: "Umowa B2B (PL)", contract_type: "b2b", content_jinja: "", is_default: true },
  { id: 2, name: "Umowa B2B (EN)", contract_type: "b2b", content_jinja: "", is_default: false },
];

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ContractTemplatesPage />
    </QueryClientProvider>,
  );
}

describe("Wzory umów — domyślny wzór (20.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = { role: "admin", roles: ["admin"] };
    mocks.get.mockResolvedValue({ data: TEMPLATES });
    mocks.patch.mockResolvedValue({ data: { ...TEMPLATES[1], is_default: true } });
  });

  it("domyślny ma znacznik, pozostałe — „Ustaw jako domyślny” (PATCH tylko flagi)", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("Domyślny", { selector: "span" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ustaw jako domyślny" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/contract-templates/2", { is_default: true }),
    );
  });

  it("Finanse widzą znacznik, ale bez przycisku zmiany", async () => {
    mocks.user = { role: "finance", roles: ["finance"] };
    renderPage();
    expect(await screen.findByText("Domyślny", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ustaw jako domyślny" })).not.toBeInTheDocument();
  });

  it("awaria pobrania to błąd z ponowieniem, nie „Brak szablonów”", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.queryByText(/Brak szablonów/)).not.toBeInTheDocument();
  });
});
