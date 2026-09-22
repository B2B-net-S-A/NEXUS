import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const tasksProps = vi.fn();
let currentUser: Record<string, unknown> | null = null;

vi.mock("@/components/v2/dashboard/MyTasksDashboard", () => ({
  MyTasksDashboard: (props: Record<string, unknown>) => {
    tasksProps(props);
    return null;
  },
}));
vi.mock("@/store/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/store/auth")>();
  return {
    ...actual,
    useAuthStore: (selector: (s: { user: unknown }) => unknown) =>
      selector({ user: currentUser }),
  };
});

import { TileContent } from "@/components/v2/dashboard/custom/TileContent";
import type { DashboardTile } from "@/lib/api/userDashboard";

const tile = { id: "t1", type: "my_tasks", x: 0, y: 0, w: 6, h: 4, config: {} } as unknown as DashboardTile;

function userWith(role: string, preset: string) {
  return {
    id: 1,
    email: "x@example.com",
    name: "X",
    role,
    roles: [role],
    is_active: true,
    available_dashboard_presets: [preset],
    default_dashboard_preset: preset,
  };
}

describe("TileContent — „Moje zadania” (FE-N06)", () => {
  beforeEach(() => tasksProps.mockClear());

  it("Delivery Lead dostaje same powiadomienia rekrutacyjne", () => {
    currentUser = userWith("delivery_lead", "delivery-lead");
    render(<TileContent tile={tile} />);
    expect(tasksProps).toHaveBeenCalledWith(
      expect.objectContaining({ recruitmentNotificationsOnly: true }),
    );
  });

  it("rekruter — wszystkie powiadomienia", () => {
    currentUser = userWith("recruiter", "my-work");
    render(<TileContent tile={tile} />);
    expect(tasksProps).toHaveBeenCalledWith(
      expect.objectContaining({ recruitmentNotificationsOnly: false }),
    );
  });
});
