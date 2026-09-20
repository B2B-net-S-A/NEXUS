import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { useCloudTalkEnabled } from "@/hooks/useCloudTalkEnabled";

vi.mock("@/lib/api", () => ({ default: { get: vi.fn() } }));

const apiGet = vi.mocked(api.get);

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useCloudTalkEnabled", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("is true only after the backend confirms the flag", async () => {
    apiGet.mockResolvedValue({ data: { enabled: true } } as never);
    const { result } = renderHook(() => useCloudTalkEnabled(), { wrapper });
    expect(result.current).toBe(false);
    await waitFor(() => expect(result.current).toBe(true));
    expect(apiGet).toHaveBeenCalledWith(
      "/api/calls/cloudtalk-status",
      expect.anything(),
    );
  });

  it("fails closed on an error and on a disabled flag", async () => {
    apiGet.mockRejectedValue(new Error("offline"));
    const failed = renderHook(() => useCloudTalkEnabled(), { wrapper });
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(failed.result.current).toBe(false);

    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: { enabled: false } } as never);
    const disabled = renderHook(() => useCloudTalkEnabled(), { wrapper });
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(disabled.result.current).toBe(false);
  });

  it("does not ask when disabled by the caller", () => {
    renderHook(() => useCloudTalkEnabled({ enabled: false }), { wrapper });
    expect(apiGet).not.toHaveBeenCalled();
  });
});
