import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { SettlementsStartCard } from "../SettlementsStartCard";
import { useAuthStore } from "@/store/auth";

function renderAs(roles: string[]) {
  useAuthStore.setState({
    user: { id: 5, role: roles[0], roles },
    realUser: null,
    hydrated: true,
  } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SettlementsStartCard />
    </QueryClientProvider>,
  );
}

const START = {
  module_enabled: true,
  portal_state: "internal",
  back_office: true,
  mailbox: { configured: true, last_run_at: null, last_status: null, last_error: null },
  rule_clients: [],
  active_panels: 0,
};

const startCalls = () =>
  get.mock.calls.filter(([url]) => String(url).endsWith("/settlements/start"));

afterEach(() => {
  get.mockReset();
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

// `GET /api/finance/settlements/start` jest tylko dla admina (`AdminUser`),
// a karta stoi w zakładce Przychody, którą otwierają Finanse.
describe("Karta „Start rozliczeń” pyta API tylko jako admin", () => {
  it("konto Finansów nie woła `/start` (inaczej 403 w konsoli)", async () => {
    get.mockResolvedValue({ data: START });
    renderAs(["finance"]);
    await new Promise((r) => setTimeout(r, 50));
    expect(startCalls()).toHaveLength(0);
  });

  it("admin woła `/start`", async () => {
    get.mockResolvedValue({ data: START });
    renderAs(["admin"]);
    await waitFor(() => expect(startCalls()).toHaveLength(1));
  });
});
