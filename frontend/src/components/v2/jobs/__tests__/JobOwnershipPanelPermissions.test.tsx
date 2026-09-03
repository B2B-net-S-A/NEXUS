import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import { useAuthStore, type User } from "@/store/auth";

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/v2/jobs/OwnerBadge", () => ({
  OwnerBadge: ({ user }: { user: { name: string } | null }) => (
    <span>{user?.name ?? "Brak"}</span>
  ),
}));
vi.mock("@/components/v2/modals/ReassignOwnerV2", () => ({
  ReassignOwnerV2: () => null,
}));

const deliveryLead = {
  id: 7,
  name: "Delivery Lead",
  email: "dl@example.com",
  role: "delivery_lead",
  roles: ["delivery_lead"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
} satisfies User;

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <JobOwnershipPanel
        jobId={11}
        jobTitle="Backend Engineer"
        primaryOwner={null}
        collaborators={[]}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useAuthStore.setState({
    user: deliveryLead,
    realUser: null,
    token: "token",
    hydrated: true,
  });
});

describe("JobOwnershipPanel section access", () => {
  it("shows write actions only in a direct Pipeline write session", () => {
    const first = renderPanel();
    expect(screen.getByRole("button", { name: "Zmień" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Claim this job" }),
    ).toBeInTheDocument();

    first.unmount();
    useAuthStore.setState({
      user: {
        ...deliveryLead,
        effective_section_access: { pipeline: "read" },
      },
    });
    renderPanel();
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Claim this job" }),
    ).not.toBeInTheDocument();
  });

  it("suppresses write actions during impersonation", () => {
    useAuthStore.setState({ realUser: deliveryLead });
    renderPanel();

    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Claim this job" }),
    ).not.toBeInTheDocument();
  });
});
