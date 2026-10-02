import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobOwnershipPanel } from "@/components/v2/jobs/JobOwnershipPanel";
import type { Permission } from "@/lib/permissions";
import { useAuthStore, type User } from "@/store/auth";
import { permissionSnapshot } from "@/test/fixtures/permission-snapshot";

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

function renderPanel(
  primaryOwner: {
    id: number;
    name: string;
    email: string;
    role: "recruiter";
    is_active?: boolean;
  } | null = null,
  canEdit?: boolean,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <JobOwnershipPanel
        jobId={11}
        jobTitle="Backend Engineer"
        primaryOwner={primaryOwner}
        collaborators={[]}
        canEdit={canEdit}
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
      screen.getByRole("button", { name: "Przejmij rekrutację" }),
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
      screen.queryByRole("button", { name: "Przejmij rekrutację" }),
    ).not.toBeInTheDocument();
  });

  it("suppresses write actions during impersonation", () => {
    useAuthStore.setState({ realUser: deliveryLead });
    renderPanel();

    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Przejmij rekrutację" }),
    ).not.toBeInTheDocument();
  });
});

// Zmiana prowadzącego idzie za uprawnieniem „Rekrutacje: zakładanie, zamykanie,
// wysyłka CV do klienta” (domyślnie Delivery Lead i administrator), nie za rolą.
describe("JobOwnershipPanel — „Zmień” prowadzącego za uprawnieniem", () => {
  const change = () => screen.queryByRole("button", { name: "Zmień" });
  const claim = () => screen.queryByRole("button", { name: "Przejmij rekrutację" });

  function account(role: User["role"], granted?: Permission[]): User {
    return {
      ...deliveryLead,
      id: 20,
      name: role,
      role,
      roles: [role],
      // Bez `granted` liczą się domyślne uprawnienia roli.
      ...(granted ? { effective_action_access: permissionSnapshot(...granted) } : {}),
    };
  }

  it.each(["delivery_lead", "admin"] as const)(
    "%s ma uprawnienie domyślnie i zmienia prowadzącego",
    (role) => {
      useAuthStore.setState({ user: account(role) });
      renderPanel();
      expect(change()).toBeInTheDocument();
    },
  );

  it("rekruter z nadanym uprawnieniem zmienia prowadzącego", () => {
    useAuthStore.setState({ user: account("recruiter", ["recruitment_manage"]) });
    renderPanel();
    expect(change()).toBeInTheDocument();
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie zmienia prowadzącego, ale nadal może przejąć rekrutację", () => {
    useAuthStore.setState({
      user: account("delivery_lead", ["delivery_view", "clients_edit"]),
    });
    renderPanel();
    expect(change()).not.toBeInTheDocument();
    // Przejęcie rekrutacji bez prowadzącego to osobna reguła (każda rola wewnętrzna).
    expect(claim()).toBeInTheDocument();
  });

  it.each(["recruiter", "head_of_recruitment", "tac"] as const)(
    "%s bez uprawnienia nie zmienia prowadzącego — ranga roli go nie daje",
    (role) => {
      useAuthStore.setState({ user: account(role) });
      renderPanel();
      expect(change()).not.toBeInTheDocument();
    },
  );

  it("uprawnienie bez zapisu w rekrutacjach albo w podglądzie jako inny użytkownik nie wystarcza", () => {
    useAuthStore.setState({
      user: {
        ...account("recruiter", ["recruitment_manage"]),
        effective_section_access: { pipeline: "read" },
      },
    });
    const first = renderPanel();
    expect(change()).not.toBeInTheDocument();
    first.unmount();

    useAuthStore.setState({
      user: account("recruiter", ["recruitment_manage"]),
      realUser: account("admin"),
    });
    renderPanel();
    expect(change()).not.toBeInTheDocument();
  });
});

describe("JobOwnershipPanel — nieaktywny prowadzący (R9-V2-2)", () => {
  const owner = { id: 3, name: "Była Rekruterka", email: "b@example.com", role: "recruiter" as const };

  it("prowadzący z nieaktywnym kontem = rekrutację da się przejąć", () => {
    renderPanel({ ...owner, is_active: false });
    expect(
      screen.getByRole("button", { name: "Przejmij rekrutację" }),
    ).toBeInTheDocument();
  });

  it("aktywny prowadzący — bez przycisku przejęcia", () => {
    renderPanel({ ...owner, is_active: true });
    expect(
      screen.queryByRole("button", { name: "Przejmij rekrutację" }),
    ).not.toBeInTheDocument();
  });
});

describe("JobOwnershipPanel — współpracowników dopisuje każdy, kto redaguje (29.09.2026)", () => {
  const recruiter = {
    ...deliveryLead,
    id: 9,
    name: "Rekruter spoza zespołu",
    role: "recruiter",
    roles: ["recruiter"],
  } satisfies User;
  const owner = { id: 3, name: "Prowadząca", email: "p@example.com", role: "recruiter" as const };

  it("rekruter spoza zespołu z prawem edycji widzi „Dodaj”", () => {
    useAuthStore.setState({ user: recruiter });
    renderPanel(owner, true);
    expect(screen.getByRole("button", { name: "Dodaj" })).toBeInTheDocument();
    // Zmiana prowadzącego wymaga osobnego uprawnienia — sama edycja go nie daje.
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
  });

  it("bez prawa edycji — bez „Dodaj”", () => {
    useAuthStore.setState({ user: recruiter });
    renderPanel(owner, false);
    expect(screen.queryByRole("button", { name: "Dodaj" })).not.toBeInTheDocument();
  });
});
