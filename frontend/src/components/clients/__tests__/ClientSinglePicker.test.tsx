import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
}));

import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";

function renderPicker(selectableOnly: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ClientSinglePicker
        value={null}
        onChange={() => {}}
        queryKey={`picker-${selectableOnly}`}
        selectableOnly={selectableOnly}
      />
    </QueryClientProvider>,
  );
}

describe("ClientSinglePicker — wybór klienta", () => {
  beforeEach(() => {
    mocks.apiGet.mockReset();
    mocks.apiGet.mockResolvedValue({ data: [] });
  });

  it("w Rekrutacjach i Kontraktach prosi tylko o Aktywnych i Relacyjnych", async () => {
    renderPicker(true);
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/api/clients-lookup", {
        params: { contract_eligible: true },
      }),
    );
  });

  it("bez trybu wyboru bierze pełną listę (radar, generator CV)", async () => {
    renderPicker(false);
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/api/clients-lookup", undefined),
    );
  });
});
