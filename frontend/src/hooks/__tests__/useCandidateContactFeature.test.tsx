import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCandidateContactFeature } from "@/hooks/useCandidateContactFeature";
import { candidateContactApi } from "@/lib/candidate-contact";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useCandidateContactFeature", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stays fail-closed until the backend confirms the feature is enabled", async () => {
    vi.spyOn(candidateContactApi, "status").mockResolvedValue({
      enabled: false,
      assignment_enabled: false,
      traffit_intake_enabled: false,
    });

    const { result } = renderHook(() => useCandidateContactFeature(), {
      wrapper,
    });

    expect(result.current.enabled).toBe(false);
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.enabled).toBe(false);
    expect(candidateContactApi.status).toHaveBeenCalledOnce();
  });

  it("uses a deterministic preview override without calling the API", () => {
    const statusSpy = vi.spyOn(candidateContactApi, "status");

    const { result } = renderHook(
      () =>
        useCandidateContactFeature({
          enabledOverride: true,
        }),
      { wrapper },
    );

    expect(result.current.enabled).toBe(true);
    expect(result.current.status?.enabled).toBe(true);
    expect(result.current.isPending).toBe(false);
    expect(statusSpy).not.toHaveBeenCalled();
  });
});
