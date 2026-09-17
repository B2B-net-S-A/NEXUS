import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ registry: vi.fn() }));

vi.mock("@/lib/api", () => ({
  phase5Api: { conflicts: { registry: mocks.registry } },
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { ClientConflictsSection } from "@/components/client-profile/ClientConflictsSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ClientConflictsSection clientId={3} />
    </QueryClientProvider>,
  );
}

const ROW = {
  id: 5,
  candidate_id: 7,
  candidate_name: "Jan Kowalski",
  client_id: 3,
  client_name: "Bank Testowy",
  type: "blacklist",
  type_label: "Czarna lista klienta",
  reason: "Nie wracamy",
  active: true,
  state: "active",
  expires_at: "2099-01-01T00:00:00Z",
  created_by: null,
  created_by_name: null,
  created_at: null,
  deactivated_at: null,
  deactivated_by: null,
  deactivated_by_name: null,
  deactivation_reason: null,
};

describe("ClientConflictsSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks the registry for this client's active conflicts and links candidates", async () => {
    mocks.registry.mockResolvedValue({
      data: { items: [ROW], total: 1, limit: 100, offset: 0, type_labels: {} },
    });
    renderSection();
    const item = await screen.findByTestId("client-conflict-5");
    expect(within(item).getByRole("link", { name: "Jan Kowalski" })).toHaveAttribute(
      "href",
      "/candidates/7",
    );
    expect(within(item).getByText("Czarna lista klienta")).toBeInTheDocument();
    expect(within(item).getByText("wygasa 01.01.2099")).toBeInTheDocument();
    expect(mocks.registry).toHaveBeenCalledWith(
      expect.objectContaining({ client_id: 3, state: "active" }),
    );
    // Sekcja jest tylko do odczytu — bez formularza i dezaktywacji.
    expect(screen.queryByRole("button", { name: /Dezaktywuj|Dodaj/ })).not.toBeInTheDocument();
  });

  it("says when the list is truncated", async () => {
    mocks.registry.mockResolvedValue({
      data: { items: [ROW], total: 140, limit: 100, offset: 0, type_labels: {} },
    });
    renderSection();
    expect(await screen.findByText(/Pokazano 1 z 140/)).toBeInTheDocument();
  });

  it("an error is not 'no conflicts'", async () => {
    mocks.registry.mockRejectedValue(
      Object.assign(new Error("HTTP 500"), { response: { status: 500 } }),
    );
    renderSection();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Żaden kandydat nie ma/)).not.toBeInTheDocument();
  });

  it("a real empty result says so", async () => {
    mocks.registry.mockResolvedValue({
      data: { items: [], total: 0, limit: 100, offset: 0, type_labels: {} },
    });
    renderSection();
    expect(
      await screen.findByText("Żaden kandydat nie ma aktywnego konfliktu z tym klientem."),
    ).toBeInTheDocument();
  });
});
