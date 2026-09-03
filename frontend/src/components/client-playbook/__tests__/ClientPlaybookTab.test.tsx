import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientPlaybookTab } from "@/components/client-playbook/ClientPlaybookTab";
import { makeClientPlaybook } from "@/test/fixtures/client-playbook";
import { makeCvRule } from "@/test/fixtures/cv-rule";

/**
 * Zakładka „Zasady współpracy" w profilu klienta: karta ↔ formularz w miejscu.
 * Edycję otwiera wyłącznie rola z `client_playbook.manage`; zapis wraca do
 * karty (formularz woła `onSaved`), „Zamknij edycję" wraca bez zapisu.
 */

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    put: mocks.put,
    post: mocks.post,
    delete: mocks.delete,
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, realUser: null, hydrated: true }),
  getUserRoles: (user: { role?: string; roles?: string[] } | null) =>
    user ? Array.from(new Set([user.role, ...(user.roles ?? [])])) : [],
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

const DL_USER = { id: 7, role: "delivery_lead", roles: ["delivery_lead"] };
const RECRUITER_USER = { id: 8, role: "recruiter", roles: ["recruiter"] };
const SLA_LABEL = "SLA: dni robocze na pierwszego kandydata";

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClientPlaybookTab clientId={1} />
    </QueryClientProvider>,
  );
}

describe("ClientPlaybookTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = DL_USER;
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/api/clients/1/playbook") return { data: makeClientPlaybook() };
      if (url === "/api/clients/1/cv-rule") return { data: makeCvRule() };
      if (url === "/api/clients/1/playbook/history") return { data: [] };
      throw new Error(`unexpected GET ${url}`);
    });
    mocks.put.mockImplementation(async (_url: string, body: Record<string, unknown>) => ({
      data: makeClientPlaybook({ ...(body as object), version: 4 }),
    }));
  });

  it("DL: „Edytuj kartę” otwiera formularz w miejscu, „Zamknij edycję” wraca do karty", async () => {
    renderTab();
    fireEvent.click(await screen.findByTestId("client-playbook-edit"));

    expect(await screen.findByLabelText(SLA_LABEL)).toBeInTheDocument();
    expect(screen.getByTestId("client-playbook-editing")).toBeInTheDocument();
    expect(screen.queryByTestId("client-playbook-card")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Zamknij edycję/ }));
    expect(await screen.findByTestId("client-playbook-card")).toBeInTheDocument();
    expect(screen.queryByTestId("client-playbook-editing")).not.toBeInTheDocument();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("DL: zapis w formularzu wraca do karty", async () => {
    renderTab();
    fireEvent.click(await screen.findByTestId("client-playbook-edit"));
    await screen.findByLabelText(SLA_LABEL);

    fireEvent.click(screen.getByRole("button", { name: "Zapisz kartę" }));

    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/api/clients/1/playbook", expect.anything()));
    expect(await screen.findByTestId("client-playbook-card")).toBeInTheDocument();
    expect(screen.queryByTestId("client-playbook-editing")).not.toBeInTheDocument();
  });

  it("recruiter: brak przycisku edycji, karta widoczna", async () => {
    mocks.user = RECRUITER_USER;
    renderTab();

    expect(await screen.findByTestId("client-playbook-card")).toBeInTheDocument();
    expect(screen.getByText("Karta klienta — Nordea Bank Abp")).toBeInTheDocument();
    expect(screen.queryByTestId("client-playbook-edit")).not.toBeInTheDocument();
  });
});
