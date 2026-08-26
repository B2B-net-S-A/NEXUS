import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContractsClientPicker } from "@/components/contracts/ContractsClientPicker";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => getMock(...args) },
}));

describe("ContractsClientPicker — canonical client label", () => {
  it("replaces a stale clientName from the URL with the Clients module name", async () => {
    getMock.mockResolvedValue({
      data: [{ id: 42, name: "Nordea Bank Abp S.A. Oddział w Polsce" }],
    });
    const onChange = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ContractsClientPicker
          value={{ id: 42, name: "Nordea" }}
          onChange={onChange}
        />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        id: 42,
        name: "Nordea Bank Abp S.A. Oddział w Polsce",
      }),
    );
  });
});
