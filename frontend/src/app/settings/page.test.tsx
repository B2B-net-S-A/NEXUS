import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./page";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  get: vi.fn(),
}));

vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/components/settings/Microsoft365Card", () => ({
  default: () => null,
}));
vi.mock("@/components/settings/TeamsNotificationsCard", () => ({
  default: () => null,
}));
vi.mock("@/components/settings/TraffitSyncCard", () => ({
  TraffitSyncCard: () => null,
}));
vi.mock("@/components/settings/EmailTemplatesCard", () => ({
  default: () => null,
}));
vi.mock("@/lib/onboarding-storage", () => ({
  clearOnboardingCompleted: vi.fn(),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector?: (state: unknown) => unknown) => {
    const state = { user: mocks.user, hydrated: true };
    return selector ? selector(state) : state;
  },
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    patch: vi.fn(),
  },
}));

function renderAdvancedSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Zaawansowane" }));
}

describe("SettingsPage — linki zależne od Insights", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockImplementation(async (url: string) => ({
      data: url.includes("transcripts") ? [] : {},
    }));
  });

  it("pokazuje Scoring Delivery Leadowi już przy Insights read", () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "read", pipeline: "read" },
    };

    renderAdvancedSettings();

    expect(
      screen.getByRole("link", { name: /Profile wag scoringu/ }),
    ).toBeInTheDocument();
  });

  it("ukrywa Scoring, gdy polityka odbiera Insights", () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "none", pipeline: "read" },
    };

    renderAdvancedSettings();

    expect(
      screen.queryByRole("link", { name: /Profile wag scoringu/ }),
    ).not.toBeInTheDocument();
  });

  it("pokazuje LinkedIn Metrics roli Finance z Insights read", () => {
    mocks.user = {
      role: "finance",
      roles: ["finance"],
      effective_section_access: { insights: "read", finance: "write" },
    };

    renderAdvancedSettings();

    expect(
      screen.getByRole("link", { name: /Aktywność LinkedIn/ }),
    ).toBeInTheDocument();
  });

  it("ukrywa LinkedIn Metrics roli Finance bez Insights read", () => {
    mocks.user = {
      role: "finance",
      roles: ["finance"],
      effective_section_access: { insights: "none", finance: "write" },
    };

    renderAdvancedSettings();

    expect(
      screen.queryByRole("link", { name: /Aktywność LinkedIn/ }),
    ).not.toBeInTheDocument();
  });
});
