import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCanonicalClientRedirect } from "@/hooks/useCanonicalClientRedirect";

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: navigation.replace,
  }),
}));

describe("useCanonicalClientRedirect", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
  });

  it("replaces a stale merged-client route with the canonical client id", () => {
    renderHook(() => useCanonicalClientRedirect("41", 7));

    expect(navigation.replace).toHaveBeenCalledOnce();
    expect(navigation.replace).toHaveBeenCalledWith("/clients/7");
  });

  it("does not navigate for an already canonical or unresolved response", () => {
    const { rerender } = renderHook(
      ({ canonicalId }) => useCanonicalClientRedirect("7", canonicalId),
      { initialProps: { canonicalId: undefined as number | undefined } },
    );

    rerender({ canonicalId: 7 });

    expect(navigation.replace).not.toHaveBeenCalled();
  });
});
