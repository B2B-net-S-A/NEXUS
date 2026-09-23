import { describe, expect, it, vi } from "vitest";

import { toggleChampionFound } from "@/lib/champion-found-toggle";

describe("toggleChampionFound (REC-05)", () => {
  it("odmowa serwera trafia do toastu, bez odświeżenia", async () => {
    const onError = vi.fn();
    const refresh = vi.fn();
    const ok = await toggleChampionFound({
      jobId: 5,
      found: true,
      save: () =>
        Promise.reject({
          response: { status: 403, data: { detail: "Tylko Delivery Lead rekrutacji." } },
        }),
      refresh,
      onError,
    });
    expect(ok).toBe(false);
    expect(onError).toHaveBeenCalledWith("Tylko Delivery Lead rekrutacji.");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("obiektowy detail nie wywraca komunikatu", async () => {
    const onError = vi.fn();
    await toggleChampionFound({
      jobId: 5,
      found: false,
      save: () => Promise.reject({ response: { status: 409, data: { detail: { code: "X" } } } }),
      refresh: vi.fn(),
      onError,
    });
    expect(typeof onError.mock.calls[0][0]).toBe("string");
  });

  it("sukces odświeża rekrutację", async () => {
    const refresh = vi.fn();
    const save = vi.fn().mockResolvedValue({});
    expect(
      await toggleChampionFound({ jobId: 5, found: true, save, refresh, onError: vi.fn() }),
    ).toBe(true);
    expect(save).toHaveBeenCalledWith(5, true);
    expect(refresh).toHaveBeenCalled();
  });
});
