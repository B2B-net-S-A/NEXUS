import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttentionCell, useClientAttention } from "@/components/clients/ClientAttention";

const mocks = vi.hoisted(() => ({ calendar: vi.fn(), relationships: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => mocks.relationships(...args) },
}));

vi.mock("@/lib/api/client-reports", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client-reports")>()),
  getCalendar: (...args: unknown[]) => mocks.calendar(...args),
}));

function Cell() {
  const attention = useClientAttention();
  return <AttentionCell items={attention.byClient.get(10) ?? []} failed={attention.failed} />;
}

function renderCell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Cell />
    </QueryClientProvider>,
  );
}

describe("„Wymaga uwagi” przy awarii zapytania (audyt 24.11.2026)", () => {
  beforeEach(() => {
    mocks.calendar.mockReset();
    mocks.relationships.mockReset();
  });

  it("500 z kalendarza raportów to znacznik „Nie udało się wczytać”, nie „—”", async () => {
    mocks.calendar.mockRejectedValue({ response: { status: 500 } });
    mocks.relationships.mockResolvedValue({ data: [] });
    renderCell();
    expect(await screen.findByText("Nie udało się wczytać")).toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("500 z relacji też", async () => {
    mocks.calendar.mockResolvedValue({ items: [] });
    mocks.relationships.mockRejectedValue({ response: { status: 500 } });
    renderCell();
    expect(await screen.findByText("Nie udało się wczytać")).toBeInTheDocument();
  });

  it("oba zapytania udane i nic nie czeka = „—”", async () => {
    mocks.calendar.mockResolvedValue({ items: [] });
    mocks.relationships.mockResolvedValue({ data: [] });
    renderCell();
    await waitFor(() => expect(mocks.relationships).toHaveBeenCalled());
    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.queryByText("Nie udało się wczytać")).not.toBeInTheDocument();
  });
});
