import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pathname: "/wtyczka/prywatnosc",
  get: vi.fn(),
  auth: {
    token: "expired-session-in-local-storage",
    realUser: null,
    hydrated: true,
    user: null,
    hydrate: vi.fn(),
    syncUser: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useSelectedLayoutSegment: () => "wtyczka",
}));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get } }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: typeof mocks.auth) => unknown) => selector(mocks.auth),
  isTraineeOnly: () => false,
}));
vi.mock("@/hooks/useCapability", () => ({ useCapabilities: () => ({}) }));
vi.mock("@/hooks/useOnboardingGuard", () => ({ useOnboardingGuard: () => ({ needsOnboarding: false }) }));
vi.mock("@/components/KeyboardShortcuts", () => ({
  useKeyboardShortcuts: () => ({ showHelp: false, setShowHelp: vi.fn() }),
  ShortcutsModal: () => null,
}));
vi.mock("@/store/my-people", () => ({ useMyPeoplePanel: () => vi.fn() }));
vi.mock("../SidebarV2", () => ({ SidebarV2: () => <nav>Private sidebar</nav> }));
vi.mock("../TopbarV2", () => ({ TopbarV2: () => null }));
vi.mock("../ImpersonationBanner", () => ({ ImpersonationBanner: () => null }));
vi.mock("../NotificationsRealtime", () => ({ NotificationsRealtime: () => null }));
vi.mock("../CommandPaletteV2", () => ({ CommandPaletteV2: () => null }));
vi.mock("../KidsBackdrop", () => ({ KidsBackdrop: () => null }));
vi.mock("@/components/jarvis/JarvisRoot", () => ({ JarvisRoot: () => null }));
vi.mock("@/components/v2/my-people/MyPeopleLauncher", () => ({ MyPeopleRoot: () => null }));
vi.mock("@/components/ui/sheet", () => ({ Sheet: () => null, SheetContent: () => null, SheetTitle: () => null }));
vi.mock("@/components/trainee/TraineeShell", () => ({ TraineeShell: () => null }));

import { AppShellV2 } from "../AppShellV2";

describe("public extension privacy page", () => {
  it("renders without the private shell or stale-session profile request", () => {
    render(<AppShellV2><h1>Polityka prywatności</h1></AppShellV2>);

    expect(screen.getByRole("heading", { name: "Polityka prywatności" })).toBeVisible();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    // A rejected /auth/me would trigger the API interceptor's login redirect.
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
