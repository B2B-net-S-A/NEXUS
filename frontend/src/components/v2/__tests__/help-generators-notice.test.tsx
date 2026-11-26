import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { helpTabsFor } from "@/components/v2/pages/HelpPageV2";
import {
  HELP_GENERATOR_LINKS,
  HelpGeneratorsNotice,
} from "@/components/v2/pages/HelpGeneratorsNotice";

const visibleIds = vi.hoisted(() => ({ current: [] as string[] }));

vi.mock("@/lib/nav-registry", () => ({
  visibleNavEntries: () => visibleIds.current.map((id) => ({ id })),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: { user: unknown }) => unknown) =>
    select({ user: { role: "recruiter", roles: ["recruiter"] } }),
  hasRole: () => false,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

describe("Pomoc bez wzorów Word (26.11.2026)", () => {
  beforeEach(() => {
    visibleIds.current = [];
  });

  it("Materiały widzi tylko admin", () => {
    expect(helpTabsFor(true).map((t) => t.value)).toEqual(["procedures", "materials", "clients"]);
    expect(helpTabsFor(false).map((t) => t.value)).toEqual(["procedures", "clients"]);
  });

  it("pokazuje każdy generator, do którego prowadzi menu", () => {
    visibleIds.current = ["b2b-generator", "pre-contracts", "jobs"];
    render(<HelpGeneratorsNotice />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(HELP_GENERATOR_LINKS.length);
    expect(screen.getByRole("link", { name: /Umowa B2B/ })).toHaveAttribute(
      "href",
      "/contracts/b2b-generator",
    );
  });

  it("chowa odnośnik, którego menu tej osobie nie daje", () => {
    visibleIds.current = ["jobs"];
    render(<HelpGeneratorsNotice />);
    expect(screen.queryByRole("link", { name: /Umowa B2B/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Umowa przedwstępna/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Profil Championa/ })).toHaveAttribute("href", "/jobs");
  });

  it("bez żadnego odnośnika nie rysuje paska", () => {
    const { container } = render(<HelpGeneratorsNotice />);
    expect(container).toBeEmptyDOMElement();
  });
});
