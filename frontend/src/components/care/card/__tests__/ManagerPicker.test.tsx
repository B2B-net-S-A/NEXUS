/**
 * „Wskaż menedżera” w karcie konsultanta: propozycje struktury u klienta czytają
 * tylko role z D11 (opiekun, DL, TCM, Head of Recruitment, admin). Finanse
 * nie pytają serwera — wcześniej dostawały 403 w konsoli (Tester 23.11.2026).
 * Dane zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

import { ManagerPicker } from "../ManagerPicker";
import { useAuthStore, type User } from "@/store/auth";

function account(role: string): User {
  return { id: 7, email: "osoba@example.com", name: "Ola Próbna", role, roles: [role] } as unknown as User;
}

function renderPicker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ManagerPicker contractId={11} clientId={3} />
    </QueryClientProvider>,
  );
}

const structureCalls = () =>
  mocks.get.mock.calls.filter(([url]) => String(url).includes("/structure-proposals"));

beforeEach(() => {
  mocks.get.mockReset();
  mocks.get.mockResolvedValue({ data: { can_apply_managers: false, managers: [], people: [] } });
});

describe("ManagerPicker", () => {
  it("Finanse nie pytają o propozycje struktury (D11)", async () => {
    useAuthStore.setState({ user: account("finance"), hydrated: true });
    renderPicker();
    expect(await screen.findByText(/wskażesz w oknie rozmowy/)).toBeInTheDocument();
    expect(structureCalls()).toHaveLength(0);
  });

  it("Delivery Lead pyta o propozycje klienta", async () => {
    useAuthStore.setState({ user: account("delivery_lead"), hydrated: true });
    renderPicker();
    await waitFor(() => expect(structureCalls()).toHaveLength(1));
    expect(structureCalls()[0][0]).toBe("/api/care/clients/3/structure-proposals");
  });
});
