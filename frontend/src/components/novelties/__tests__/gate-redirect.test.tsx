import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Zgłoszenie 23.11.2026: osoba z porcją do przeklikania klikała menu i dostawała
// pusty ekran. Przekierowanie bramki leciało tylko przy zmianie `blocked`, więc
// gdy pierwsze `router.replace` przepadło (kolejny klik w menu w trakcie), dalsze
// przejścia między zablokowanymi ekranami nie przekierowywały już nigdzie.

const mocks = vi.hoisted(() => {
  const replace = vi.fn();
  return {
    pathname: "/jobs",
    replace,
    // Jak w Next: ten sam obiekt routera przy każdym renderze.
    router: { replace },
    daily: { enforced: true, items: [] as { id: string }[] },
    start: { enforced: false, items: [] as { id: string }[], redirect: "/start" },
  };
});

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => mocks.router,
}));
vi.mock("@/lib/novelties/api", () => ({
  useDailyStatus: () => mocks.daily,
  useStartStatus: () => mocks.start,
}));
vi.mock("@/lib/poligon/mode", () => ({ isPoligonActive: () => false }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { user: object; hydrated: boolean }) => unknown) =>
    selector({ user: { role: "talent_community_manager" }, hydrated: true }),
  isBoardOnly: () => false,
}));

import { useDailyNoveltyGate } from "../useDailyNoveltyGate";
import { useStartGate } from "../useStartGate";

beforeEach(() => {
  mocks.pathname = "/jobs";
  mocks.replace.mockClear();
  mocks.daily = { enforced: true, items: [] };
  mocks.start = { enforced: false, items: [], redirect: "/start" };
});

describe("bramka porannej porcji", () => {
  it("przekierowuje przy każdym przejściu na zablokowany ekran", () => {
    const { result, rerender } = renderHook(() => useDailyNoveltyGate());
    expect(result.current).toBe(true);
    expect(mocks.replace).toHaveBeenLastCalledWith("/nowosci-dnia");

    // Pierwsze przekierowanie przepadło, osoba klika „Kandydaci”.
    mocks.pathname = "/candidates";
    rerender();
    expect(result.current).toBe(true);
    expect(mocks.replace).toHaveBeenCalledTimes(2);
  });

  it("na liście porcji nie przekierowuje", () => {
    mocks.pathname = "/nowosci-dnia";
    const { result } = renderHook(() => useDailyNoveltyGate());
    expect(result.current).toBe(false);
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});

describe("bramka Startu", () => {
  it("przekierowuje przy każdym przejściu na zablokowany ekran", () => {
    mocks.daily = { enforced: false, items: [] };
    mocks.start = { enforced: true, items: [], redirect: "/start" };
    const { result, rerender } = renderHook(() => useStartGate());
    expect(result.current).toBe(true);
    expect(mocks.replace).toHaveBeenLastCalledWith("/start");

    mocks.pathname = "/candidates";
    rerender();
    expect(mocks.replace).toHaveBeenCalledTimes(2);
  });
});
