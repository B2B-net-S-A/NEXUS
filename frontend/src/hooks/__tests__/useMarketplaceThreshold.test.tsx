import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMarketplaceThreshold } from "@/hooks/useMarketplaceThreshold";

const mocks = vi.hoisted(() => ({ getPool: vi.fn() }));

vi.mock("@/lib/api", () => ({
  marketplaceApi: { getPool: (...args: unknown[]) => mocks.getPool(...args) },
}));

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  mocks.getPool.mockReset();
});

describe("useMarketplaceThreshold", () => {
  it("do czasu odpowiedzi zwraca próg zapasowy równy domyślnemu backendu (80)", () => {
    mocks.getPool.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useMarketplaceThreshold(), { wrapper: wrapper() });
    expect(result.current).toBe(80);
  });

  it("zwraca próg z backendu, gdy się wczyta", async () => {
    mocks.getPool.mockResolvedValue({ data: { score_threshold: 72 } });
    const { result } = renderHook(() => useMarketplaceThreshold(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current).toBe(72));
  });

  it("próg 0 z backendu nie jest zastępowany zapasowym", async () => {
    mocks.getPool.mockResolvedValue({ data: { score_threshold: 0 } });
    const { result } = renderHook(() => useMarketplaceThreshold(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current).toBe(0));
  });

  it("błąd API → zostaje próg zapasowy, nie optymistyczna liczba", async () => {
    mocks.getPool.mockRejectedValue(new Error("503"));
    const { result } = renderHook(() => useMarketplaceThreshold(), { wrapper: wrapper() });
    await waitFor(() => expect(mocks.getPool).toHaveBeenCalled());
    expect(result.current).toBe(80);
  });
});
