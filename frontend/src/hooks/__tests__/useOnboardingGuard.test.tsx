import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOnboardingGuard } from "@/hooks/useOnboardingGuard";
import { useAuthStore, type User } from "@/store/auth";

const nav = vi.hoisted(() => ({ replace: vi.fn(), pathname: "/" as string | null }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => nav.pathname,
}));

function user(overrides: Partial<User>): User {
  return {
    id: 1,
    email: "u@example.com",
    name: "U",
    role: "recruiter",
    roles: ["recruiter"],
    profile_completed: false,
    force_password_change: false,
    ...overrides,
  } as User;
}

function setAuth(u: User | null, hydrated = true) {
  useAuthStore.setState({ user: u, hydrated });
}

beforeEach(() => {
  nav.replace.mockReset();
  nav.pathname = "/candidates";
});

describe("useOnboardingGuard", () => {
  it("nic nie robi przed hydracją store'u", () => {
    setAuth(user({}), false);
    const { result } = renderHook(() => useOnboardingGuard());
    expect(result.current.needsOnboarding).toBe(false);
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("przekierowuje rekrutera bez ukończonego profilu na /onboarding", () => {
    setAuth(user({}));
    const { result } = renderHook(() => useOnboardingGuard());
    expect(result.current.needsOnboarding).toBe(true);
    expect(nav.replace).toHaveBeenCalledWith("/onboarding");
  });

  it.each([
    ["ukończony profil", user({ profile_completed: true })],
    ["admin", user({ role: "admin", roles: ["admin", "recruiter"] })],
    ["rola bez onboardingu", user({ role: "sourcer", roles: ["sourcer"] })],
    ["wymuszona zmiana hasła", user({ force_password_change: true })],
    ["brak użytkownika", null],
  ])("nie przekierowuje: %s", (_label, u) => {
    setAuth(u);
    const { result } = renderHook(() => useOnboardingGuard());
    expect(result.current.needsOnboarding).toBe(false);
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it.each(["/login", "/onboarding", "/onboarding/step-2", "/share/abc", "/apply/tok", "/403"])(
    "ścieżka wyłączona %s: sygnalizuje potrzebę, ale nie przekierowuje",
    (path) => {
      nav.pathname = path;
      setAuth(user({ role: "delivery_lead", roles: ["delivery_lead"] }));
      const { result } = renderHook(() => useOnboardingGuard());
      expect(result.current.needsOnboarding).toBe(true);
      expect(nav.replace).not.toHaveBeenCalled();
    },
  );

  it("prefiksy bez ukośnika nie łapią podobnych ścieżek (/login-help)", () => {
    nav.pathname = "/login-help";
    setAuth(user({}));
    renderHook(() => useOnboardingGuard());
    expect(nav.replace).toHaveBeenCalledWith("/onboarding");
  });

  it("przekierowuje po zakończeniu hydracji", () => {
    setAuth(user({}), false);
    const { rerender } = renderHook(() => useOnboardingGuard());
    expect(nav.replace).not.toHaveBeenCalled();
    setAuth(user({}), true);
    rerender();
    expect(nav.replace).toHaveBeenCalledWith("/onboarding");
  });
});
