import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SettingsPage from "./page";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  get: vi.fn(),
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mocks.params,
  usePathname: () => "/settings",
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
vi.mock("@/components/settings/NotificationDeliverySettings", () => ({
  default: () => <div>Konfiguracja wysyłki powiadomień</div>,
}));
vi.mock("@/lib/jarvis/bubble-budget", () => ({
  resetScreenSeen: vi.fn(),
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
  // `hasCapability` (bramka „Szablony maili") czyta role tym helperem.
  getUserRoles: (user: { role?: string; roles?: string[] } | null) =>
    user ? Array.from(new Set([user.role, ...(user.roles ?? [])])) : [],
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: mocks.get,
    patch: vi.fn(),
  },
}));

function renderSettings(query = "") {
  mocks.params = new URLSearchParams(query);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockImplementation(async (url: string) => ({
    data: url.includes("transcripts") ? [] : {},
  }));
});

const ADMIN = {
  role: "admin",
  roles: ["admin"],
  effective_section_access: {
    system_admin: "write", finance: "write", sourcing: "write",
    pipeline: "write", delivery: "write", insights: "read",
  },
};

describe("SettingsPage — strona startowa", () => {
  it("admin widzi pięć obszarów jako kafelki", () => {
    mocks.user = ADMIN;
    renderSettings();
    for (const name of ["Moje konto", "Zespół i dostęp", "Rekrutacja", "Umowy i stawki", "System"]) {
      expect(screen.getByRole("link", { name: new RegExp(name) })).toBeInTheDocument();
    }
  });

  it("rekruter widzi tylko Moje konto", () => {
    mocks.user = { role: "recruiter", roles: ["recruiter"], effective_section_access: { pipeline: "write" } };
    renderSettings();
    expect(screen.getByRole("link", { name: /Moje konto/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Rekrutacja/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /System/ })).not.toBeInTheDocument();
  });

  it("wyszukiwarka pokazuje pasujące pozycje z nazwą obszaru", () => {
    mocks.user = ADMIN;
    renderSettings();
    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj w ustawieniach" }), {
      target: { value: "regula cv" },
    });
    const link = screen.getByRole("link", { name: /Reguły CV klientów/ });
    expect(link).toHaveAttribute("href", "/settings/cv-rules");
    expect(screen.queryByRole("link", { name: /Moje konto/ })).not.toBeInTheDocument();
  });

  it("wyszukiwarka nie znajduje pozycji ukrytych z menu", () => {
    mocks.user = ADMIN;
    renderSettings();
    fireEvent.change(screen.getByRole("searchbox", { name: "Szukaj w ustawieniach" }), {
      target: { value: "konflikty" },
    });
    expect(screen.getByText(/Nic nie pasuje/)).toBeInTheDocument();
  });
});

describe("SettingsPage — obszar i pozycja", () => {
  it("prowadzi z Systemu do wbudowanego panelu powiadomień", () => {
    mocks.user = ADMIN;
    renderSettings("item=notifications");
    expect(screen.getByRole("heading", { level: 1, name: "Powiadomienia" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "System" })).toHaveAttribute("href", "/settings?area=sys");
    expect(screen.getByText("Konfiguracja wysyłki powiadomień")).toBeInTheDocument();
  });
  it("obszar pokazuje listę pozycji i ścieżkę", () => {
    mocks.user = ADMIN;
    renderSettings("area=rec");
    expect(screen.getByRole("heading", { level: 1, name: "Rekrutacja" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Procesy rekrutacyjne/ })).toHaveAttribute(
      "href",
      "/settings?item=stages",
    );
    expect(screen.getByRole("link", { name: "Ustawienia" })).toHaveAttribute("href", "/settings");
  });

  it("Delivery Lead z Insights read widzi Ranking kandydatów", () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "read", pipeline: "write", delivery: "write" },
    };
    renderSettings("area=rec");
    expect(screen.getByRole("link", { name: /Ranking kandydatów/ })).toBeInTheDocument();
  });

  it("bez Insights Ranking kandydatów znika", () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { insights: "none", pipeline: "write", delivery: "write" },
    };
    renderSettings("area=rec");
    expect(screen.queryByRole("link", { name: /Ranking kandydatów/ })).not.toBeInTheDocument();
  });

  it("pozycja ma ścieżkę do obszaru", () => {
    mocks.user = ADMIN;
    renderSettings("item=mail");
    expect(screen.getByRole("heading", { level: 1, name: "Szablony maili" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rekrutacja" })).toHaveAttribute("href", "/settings?area=rec");
  });

  it("pozycja bez dostępu wraca do strony startowej", () => {
    mocks.user = { role: "recruiter", roles: ["recruiter"], effective_section_access: { pipeline: "write" } };
    renderSettings("item=history");
    expect(screen.getByRole("heading", { level: 1, name: "Ustawienia" })).toBeInTheDocument();
  });
});

describe("SettingsPage — stare linki `?tab=`", () => {
  it.each([
    ["integracje", "Outlook i kalendarz"],
    ["szablony", "Szablony maili"],
    ["procesy", "Procesy rekrutacyjne"],
    ["administracja", "Osoby i role"],
    ["historia", "Historia zdarzeń"],
    ["konflikty", "Konflikty"],
    ["pomoc", "Przewodnik i skróty"],
  ])("?tab=%s otwiera „%s”", (tab, title) => {
    mocks.user = ADMIN;
    renderSettings(`tab=${tab}`);
    // Ścieżka zawsze nazywa otwartą pozycję — także gdy nagłówek rysuje komponent.
    expect(screen.getByText(title, { selector: '[aria-current="page"]' })).toBeInTheDocument();
  });
});
