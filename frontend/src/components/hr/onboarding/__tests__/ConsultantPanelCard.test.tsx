/**
 * Panel konsultanta w „Start i sprzęt”: o panel kontraktu pyta tylko operator
 * (`me.consultant_panel_operator` z `/api/hr/config` — Opieka, kierownik back
 * office'u, admin). Delivery Lead i Finanse dostawali wcześniej 403 w konsoli
 * (Tester 23.11.2026). Dane zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PanelProposal } from "@/lib/api/consultant-panel";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn(), put: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: vi.fn(async () => true), confirmDialog: null }),
}));

import { ConsultantPanelCard } from "../ConsultantPanelCard";

const proposal: PanelProposal = {
  contract_id: 42,
  client_id: 3,
  client: "Bank Przykładowy",
  start_date: "2026-12-01",
  can_activate: true,
  suggested_email: "marek.przykladowy@example.com",
  activation: {
    active: false,
    email: null,
    activated_at: null,
    activated_by: null,
    deactivated_at: null,
    last_login_at: null,
    address_changed: false,
  },
  materials: [],
  mail: { enabled: false, subject: "", body: "", issues: [], sent_at: null },
  portal_state: "pilot",
};

function serve(operator: boolean) {
  mocks.get.mockImplementation(async (url: string) =>
    url === "/api/hr/config"
      ? { data: { program: true, modules: {}, open_modules: {}, me: { is_admin: false, consultant_panel_operator: operator } } }
      : { data: proposal },
  );
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsultantPanelCard contractId={42} />
    </QueryClientProvider>,
  );
}

const panelCalls = () =>
  mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/api/consultant-panel/"));

beforeEach(() => mocks.get.mockReset());

describe("ConsultantPanelCard", () => {
  it("bez roli operatora nie pyta o panel i nic nie pokazuje", async () => {
    serve(false);
    renderCard();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/hr/config"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(panelCalls()).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Panel konsultanta" })).toBeNull();
  });

  it("operator widzi stan panelu kontraktu", async () => {
    serve(true);
    renderCard();
    expect(await screen.findByRole("button", { name: "Aktywuj panel…" })).toBeInTheDocument();
    expect(panelCalls().map(([url]) => url)).toEqual(["/api/consultant-panel/contracts/42"]);
  });
});
