import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  SIDEBAR_VERTICAL_LAYOUT,
  SidebarMoreFlyout,
  SidebarMoreInline,
  SidebarNavGroup,
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
// Żadna pozycja „Więcej” nie ma dziś licznika (Zgłoszenia zdjęte z menu
// 22.09.2026), więc test sumy dokłada jedną syntetyczną pozycję z licznikiem.
const baseGroups = visibleMoreGroups(recruiter, { contactQueueEnabled: true });
const groups = baseGroups.map((group, index) =>
  index === 0
    ? {
        ...group,
        items: [
          ...group.items,
          {
            ...group.items[0],
            id: "badge-probe",
            href: "/badge-probe",
            label: "Pozycja z licznikiem",
            badgeKey: "applicationSubmissions" as const,
          },
        ],
      }
    : group,
);

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
      "System",
    ]);
    expect(within(panel).getByRole("link", { name: /Pozycja z licznikiem/ })).toHaveTextContent("4");
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
        />
      </TooltipProvider>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /Więcej/ })).toBeNull();
    expect(screen.getByRole("group", { name: "Dokumenty" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Generator CV" })).toHaveAttribute(
      "href",
      "/cv-generator",
    );
  });
});

describe("grupa szyny — nagłówek w stałym slocie (UAT B57)", () => {
  function renderGroup(collapsed: boolean) {
    return render(
      <SidebarNavGroup id="work" title="Praca" collapsed={collapsed}>
        <span>Rekrutacje</span>
      </SidebarNavGroup>,
    );
  }

  it("rozwinięta: widoczny nagłówek, grupa ma nazwę dostępną", () => {
    const { container } = renderGroup(false);
    const group = screen.getByRole("group", { name: "Praca" });
    expect(within(group).getByText("Praca").className).not.toContain("sr-only");
    expect(within(group).getByText("Praca").className).toContain("uppercase");
    expect(container.querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it("zwinięta: kreska aria-hidden, tekst tylko dla czytnika — nazwa grupy zostaje", () => {
    const { container } = renderGroup(true);
    const group = screen.getByRole("group", { name: "Praca" });
    expect(within(group).getByText("Praca").className).toBe("sr-only");
    const divider = container.querySelector('[aria-hidden="true"]');
    expect(divider).not.toBeNull();
    expect(divider!.className).toContain("border-sidebar-border");
  });

  it("slot nagłówka i odstęp grupy mają TE SAME klasy w obu stanach", () => {
    const slotClasses = (collapsed: boolean) => {
      const { container, unmount } = renderGroup(collapsed);
      const slot = container.querySelector("[data-nav-group-slot]")!;
      const group = container.querySelector('[role="group"]')!;
      const result = [slot.className, group.className, slot.nextElementSibling!.className];
      unmount();
      return result;
    };
    expect(slotClasses(true)).toEqual(slotClasses(false));
    expect(slotClasses(false)).toEqual([
      SIDEBAR_VERTICAL_LAYOUT.sectionSlot,
      SIDEBAR_VERTICAL_LAYOUT.groupSpacing,
      SIDEBAR_VERTICAL_LAYOUT.itemSpacing,
    ]);
    expect(SIDEBAR_VERTICAL_LAYOUT.sectionSlot).toMatch(/\bh-\d+\b/);
  });
});
