import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  SidebarMoreFlyout,
  SidebarMoreInline,
  isMoreActive,
  moreBadgeTotal,
} from "@/components/v2/shell/SidebarMore";
import { TooltipProvider } from "@/components/ui/tooltip";
import { visibleMoreGroups, type NavEntry } from "@/lib/nav-registry";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const recruiter = { role: "recruiter" as const, roles: ["recruiter" as const] };
const groups = visibleMoreGroups(recruiter, { contactQueueEnabled: true });

function Harness({
  pathname = "/jobs",
  collapsed = false,
}: {
  pathname?: string;
  collapsed?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider>
      <SidebarMoreFlyout
        groups={groups}
        user={recruiter as never}
        collapsed={collapsed}
        open={open}
        onOpenChange={setOpen}
        badgeCounts={{ applicationSubmissions: 4, candidates: 9 }}
        isActive={(entry: NavEntry) => pathname.startsWith(entry.href)}
      />
    </TooltipProvider>
  );
}

describe("„Więcej” — logika", () => {
  it("sumuje WYŁĄCZNIE liczniki pozycji schowanych w panelu", () => {
    // `candidates` należy do pozycji szyny — nie wchodzi do sumy.
    expect(
      moreBadgeTotal(groups, { applicationSubmissions: 4, candidates: 9 }),
    ).toBe(4);
    expect(moreBadgeTotal(groups, {})).toBe(0);
  });

  it("strona spod „Więcej” zapala przycisk, strona z szyny — nie", () => {
    const at = (path: string) => (entry: NavEntry) => path.startsWith(entry.href);
    expect(isMoreActive(groups, at("/settings/ai"))).toBe(true);
    expect(isMoreActive(groups, at("/jobs/12"))).toBe(false);
  });
});

describe("„Więcej” — panel obok szyny", () => {
  it("Enter otwiera panel z grupami, Esc zamyka i oddaje fokus przyciskowi", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Więcej (4 nowych)" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    trigger.focus();
    await user.keyboard("{Enter}");

    const panel = await screen.findByRole("dialog", {
      name: "Więcej — pozostałe moduły",
    });
    expect(
      within(panel)
        .getAllByRole("heading", { level: 2 })
        .map((h) => h.textContent),
    ).toEqual([
      "Codzienna praca",
      "Dokumenty",
      "Baza i źródła",
      "Wiedza i raporty",
      "System",
    ]);
    expect(within(panel).getByRole("link", { name: /Zgłoszenia/ })).toHaveTextContent("4");
    // Fokus siedzi W panelu (pułapka fokusu trybu modalnego).
    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true));

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(trigger).toHaveFocus();
  });

  it("spacja też otwiera, strzałki chodzą po linkach, klik w link zamyka panel", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("button", { name: /Więcej/ }).focus();
    await user.keyboard(" ");
    const panel = await screen.findByRole("dialog");
    const links = within(panel).getAllByRole("link");

    links[0].focus();
    await user.keyboard("{ArrowDown}");
    expect(links[1]).toHaveFocus();
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(links[links.length - 1]).toHaveFocus();

    await user.click(within(panel).getByRole("link", { name: "Pomoc" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("bieżąca strona spod „Więcej” oznacza pozycję `aria-current` i zapala przycisk", async () => {
    const user = userEvent.setup();
    render(<Harness pathname="/settings" />);
    const trigger = screen.getByRole("button", { name: /Więcej/ });
    expect(trigger.className).toContain("text-primary");
    await user.click(trigger);
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByRole("link", { name: "Ustawienia" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("przycisk ma tę samą wysokość co pozycje szyny w obu stanach (UAT B57)", () => {
    const { rerender } = render(<Harness />);
    expect(screen.getByRole("button", { name: /Więcej/ }).className).toMatch(/\bh-9\b/);
    rerender(<Harness collapsed />);
    const collapsed = screen.getByRole("button", { name: /Więcej/ });
    expect(collapsed.className).toMatch(/\bh-9\b/);
    expect(collapsed.className).toMatch(/\bw-9\b/);
  });

  it("bez pozycji do schowania przycisk się nie renderuje", () => {
    render(
      <TooltipProvider>
        <SidebarMoreFlyout
          groups={[]}
          user={recruiter as never}
          collapsed={false}
          open={false}
          onOpenChange={() => undefined}
          badgeCounts={{}}
          isActive={() => false}
        />
      </TooltipProvider>,
    );
    expect(screen.queryByRole("button", { name: /Więcej/ })).toBeNull();
  });
});

describe("„Więcej” — szuflada mobilna", () => {
  it("renderuje grupy w linii, bez zagnieżdżonej nakładki", () => {
    const onNavigate = vi.fn();
    render(
      <TooltipProvider>
        <SidebarMoreInline
          groups={groups}
          user={recruiter as never}
          badgeCounts={{}}
          isActive={() => false}
          onNavigate={onNavigate}
          sectionSlotClassName="h-7 flex items-end"
          itemSpacingClassName="space-y-0.5"
        />
      </TooltipProvider>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /Więcej/ })).toBeNull();
    expect(screen.getByText("Dokumenty")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Generator CV" })).toHaveAttribute(
      "href",
      "/cv-generator",
    );
  });
});
