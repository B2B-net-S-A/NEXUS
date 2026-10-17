import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

// Liczniki „Ludzi” liczą się od nowa tylko po mutacjach modułu HR
// (`HR_COUNTS_MUTATION_KEY`), nie po każdym zapisie w aplikacji (audyt 17.10.2026).

const get = vi.hoisted(() => vi.fn(async () => ({ data: { approvals: 1, cases: null } })));
vi.mock("@/lib/api", () => ({ __esModule: true, api: { get } }));

import { HR_COUNTS_MUTATION_KEY, useHrCounts } from "@/lib/api/hr";

// Zapis trwa chwilę (jak żądanie) — licznik widzi stan „w toku”, potem koniec.
const slow = () => new Promise<string>((resolve) => setTimeout(() => resolve("ok"), 15));

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(
    () => ({
      counts: useHrCounts(),
      hr: useMutation({
        mutationKey: [...HR_COUNTS_MUTATION_KEY, "test"],
        mutationFn: slow,
      }),
      other: useMutation({ mutationKey: ["candidates", "save"], mutationFn: slow }),
    }),
    { wrapper },
  );
}

describe("odświeżanie liczników „Ludzi”", () => {
  it("decyzja HR odświeża licznik, zapis spoza HR — nie", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.counts.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.other.mutateAsync();
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(get).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.hr.mutateAsync();
    });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });
});
