import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConflictRegistryRow } from "@/lib/api";

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

import { ConflictsRegistryTab } from "./ConflictsRegistryTab";

const TYPE_LABELS = {
  blacklist: "Czarna lista klienta",
  current_employment: "Obecne zatrudnienie",
  nda: "NDA / cooling-off",
  competitor: "Klient konkurencyjny",
};

function row(overrides: Partial<ConflictRegistryRow> = {}): ConflictRegistryRow {
  return {
    id: 1,
    candidate_id: 7,
    candidate_name: "Jan Kowalski",
    client_id: 3,
    client_name: "Bank Testowy",
    type: "nda",
    type_label: "NDA / cooling-off",
    reason: "Projekt u konkurencji",
    active: true,
    state: "active",
    expires_at: "2099-10-01T21:59:59Z",
    created_by: 1,
    created_by_name: "Anna Rekruter",
    created_at: "2026-09-01T10:00:00Z",
    deactivated_at: null,
    deactivated_by: null,
    deactivated_by_name: null,
    deactivation_reason: null,
    ...overrides,
  };
}

function page(items: ConflictRegistryRow[], total = items.length) {
  return { data: { items, total, limit: 50, offset: 0, type_labels: TYPE_LABELS } };
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ConflictsRegistryTab />
    </QueryClientProvider>,
  );
}

describe("ConflictsRegistryTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.registry.mockResolvedValue(page([row()]));
  });

  it("lists who has a conflict with which client, with a candidate link and expiry", async () => {
    renderTab();
    const tr = await screen.findByTestId("conflict-registry-row-1");
    expect(within(tr).getByRole("link", { name: "Jan Kowalski" })).toHaveAttribute(
      "href",
      "/candidates/7",
    );
    expect(within(tr).getByText("Bank Testowy")).toBeInTheDocument();
    expect(within(tr).getByText("NDA / cooling-off")).toBeInTheDocument();
    expect(within(tr).getByText("wygasa 01.10.2099")).toBeInTheDocument();
    expect(mocks.registry).toHaveBeenCalledWith({
      type: undefined,
      state: "active",
      expiring_within_days: undefined,
      q: undefined,
      limit: 50,
      offset: 0,
    });
  });

  it("filters: type, search on submit, 'Wygasają w 30 dni' chip, status", async () => {
    renderTab();
    await screen.findByTestId("conflict-registry-row-1");

    fireEvent.change(screen.getByLabelText("Typ konfliktu"), { target: { value: "blacklist" } });
    await waitFor(() =>
      expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({ type: "blacklist" })),
    );

    fireEvent.change(screen.getByLabelText("Szukaj w konfliktach"), {
      target: { value: "  Łódź " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Szukaj" }));
    await waitFor(() =>
      expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({ q: "Łódź" })),
    );

    const chip = screen.getByRole("button", { name: "Wygasają w 30 dni" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await waitFor(() =>
      expect(mocks.registry).toHaveBeenLastCalledWith(
        expect.objectContaining({ expiring_within_days: 30, state: "active" }),
      ),
    );

    const status = screen.getByLabelText("Status konfliktu");
    expect(
      Array.from(status.querySelectorAll("option")).map((o) => o.textContent),
    ).toEqual(["Aktywne", "Wygasłe", "Nieaktywne", "Wszystkie"]);
    fireEvent.change(status, { target: { value: "expired" } });
    await waitFor(() =>
      expect(mocks.registry).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "expired", expiring_within_days: undefined }),
      ),
    );
    expect(screen.getByRole("button", { name: "Wygasają w 30 dni" })).toBeDisabled();
    fireEvent.change(status, { target: { value: "all" } });
    await waitFor(() =>
      expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({ state: "all" })),
    );
  });

  it("shows deactivation who/when/why for inactive rows", async () => {
    mocks.registry.mockResolvedValue(
      page([
        row({
          active: false,
          state: "inactive",
          deactivated_at: "2026-09-10T08:00:00Z",
          deactivated_by_name: "Piotr DL",
          deactivation_reason: "Klient się zgodził",
        }),
      ]),
    );
    renderTab();
    const tr = await screen.findByTestId("conflict-registry-row-1");
    expect(within(tr).getByText("Nieaktywny")).toBeInTheDocument();
    expect(
      within(tr).getByText(/Dezaktywowano 10\.09\.2026 · Piotr DL — Klient się zgodził/),
    ).toBeInTheDocument();
  });

  it("paginates by 50", async () => {
    mocks.registry.mockResolvedValue(page([row()], 120));
    renderTab();
    expect(await screen.findByText(/120 konfliktów · strona 1 z 3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Następna" }));
    await waitFor(() =>
      expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })),
    );
  });

  it("an error is not an empty registry", async () => {
    mocks.registry.mockRejectedValue(httpError(500));
    renderTab();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma żadnych aktywnych konfliktów/)).not.toBeInTheDocument();
  });

  it("403 says missing permissions", async () => {
    mocks.registry.mockRejectedValue(httpError(403));
    renderTab();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
  });

  it("a real empty result says so", async () => {
    mocks.registry.mockResolvedValue(page([]));
    renderTab();
    expect(await screen.findByText("Nie ma żadnych aktywnych konfliktów.")).toBeInTheDocument();
  });
});
