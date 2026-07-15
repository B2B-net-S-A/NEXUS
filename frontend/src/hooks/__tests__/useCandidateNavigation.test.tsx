import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { DEFAULT_FILTERS } from "@/lib/url-filters";
import { useCandidateNavigation } from "@/hooks/useCandidateNavigation";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
}));

const apiGet = vi.mocked(api.get);

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useCandidateNavigation", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("uses J/K and ignores shortcuts while typing", () => {
    const onNavigate = vi.fn();
    const { rerender } = renderHook(
      ({ position }) =>
        useCandidateNavigation({
          mode: "embedded",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position,
          pageItems: [{ id: 10 }, { id: 11 }],
          total: 2,
          pageNumber: 1,
          pageSize: 20,
          onNavigate,
        }),
      { wrapper, initialProps: { position: 1 } },
    );

    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "j" })));
    expect(onNavigate).toHaveBeenCalledWith({ candidateId: 11, position: 2 });

    rerender({ position: 2 });
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "K" })));
    expect(onNavigate).toHaveBeenLastCalledWith({ candidateId: 10, position: 1 });

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "j" })));
    expect(onNavigate).toHaveBeenCalledTimes(2);
    input.remove();
  });

  it("fetches adjacent pages without expensive include flags and exposes errors", async () => {
    apiGet.mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(
      () =>
        useCandidateNavigation({
          mode: "embedded",
          enabled: true,
          filters: DEFAULT_FILTERS,
          position: 1,
          pageItems: [{ id: 10 }],
          total: 2,
          pageNumber: 1,
          pageSize: 1,
          onNavigate: vi.fn(),
        }),
      { wrapper },
    );

    act(() => result.current.goNext());
    await waitFor(() =>
      expect(result.current.error).toBe(
        "Nie udało się pobrać kolejnego kandydata",
      ),
    );

    expect(apiGet).toHaveBeenCalledTimes(1);
    const config = apiGet.mock.calls[0]?.[1] as { params?: Record<string, unknown> };
    expect(config.params).not.toHaveProperty("include_match_stats");
    expect(config.params).not.toHaveProperty("include_active_recruitments");
    expect(config.params).not.toHaveProperty("include_last_activity");
  });
});
