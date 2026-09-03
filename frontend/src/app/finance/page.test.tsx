import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FinancePage from "@/app/finance/page";
import { useAuthStore, type User } from "@/store/auth";

vi.mock("@/components/RequireSectionAccess", () => ({
  RequireSectionAccess: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/ds/PageHeader", () => ({
  PageHeader: () => null,
}));
vi.mock("@/components/ds", () => ({
  QueryStateNotice: () => null,
}));
vi.mock("@/components/finance/FinanceResultsTab", () => ({
  FinanceResultsTab: ({ canWrite }: { canWrite: boolean }) => (
    <span>{canWrite ? "results-write" : "results-read"}</span>
  ),
}));
vi.mock("@/components/finance/FinanceArchiveTab", () => ({
  FinanceArchiveTab: () => null,
}));
vi.mock("@/components/finance/MdImportWorkspace", () => ({
  MdImportWorkspace: () => <span>md-import</span>,
}));

const financeUser = {
  id: 7,
  name: "Finance",
  email: "finance@example.com",
  role: "finance",
  roles: ["finance"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: {
    sourcing: "write",
    pipeline: "write",
    delivery: "write",
    insights: "read",
    finance: "write",
    system_admin: "none",
  },
} satisfies User;

beforeEach(() => {
  window.history.replaceState(null, "", "/finance");
  useAuthStore.setState({
    user: financeUser,
    token: "token",
    realUser: null,
    hydrated: true,
  });
});

describe("FinancePage permissions", () => {
  it("shows write surfaces for a direct Finance write session", async () => {
    render(<FinancePage />);

    expect(await screen.findByText("results-write")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Import zużycia MD" })).toBeInTheDocument();
  });

  it("is read-only while an administrator impersonates a Finance writer", async () => {
    useAuthStore.setState({
      realUser: { ...financeUser, id: 1, role: "admin", roles: ["admin"] },
    });

    render(<FinancePage />);

    expect(await screen.findByText("results-read")).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Import zużycia MD" }),
    ).not.toBeInTheDocument();
  });
});
