/**
 * „Obsługa kontraktorów”: akcje wiersza idą za uprawnieniami z ekranu Osoby
 * i role, nie za rolą.
 *
 * Do 02.10.2026 jedna bramka (`admin`/`delivery_lead` + zapis Delivery)
 * rządziła i szkicami, i „Zakończ projekt”. To dwa różne uprawnienia:
 * „Kontrakty i zamówienia: tworzenie i edycja” (domyślnie także Finanse)
 * i „Zakończenie współpracy, zmiana statusu kontraktu” (domyślnie także
 * Talent Community Manager, który tej akcji tutaj nie widział).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  stats: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("view=operations&tab=active"),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  contractorsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    stats: (...args: unknown[]) => mocks.stats(...args),
  },
}));

vi.mock("@/components/v2/modals/DraftCompletionModal", () => ({
  DraftCompletionModal: () => null,
}));

import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";
import { useAuthStore } from "@/store/auth";
import {
  permissionSnapshot,
  sectionSnapshot,
} from "@/test/fixtures/permission-snapshot";
import type { Permission } from "@/lib/permissions";

function item(id: number, lastname: string, over: Record<string, unknown>) {
  return {
    contract_id: id,
    candidate: { id: id + 100, name: "Jan", lastname, email: null },
    client_name: "Klient testowy",
    job_title: null,
    status: "active",
    start_date: "2026-08-01",
    end_date: null,
    rate_candidate: null,
    rate_client: null,
    rate_unit: "hourly",
    currency: "PLN",
    margin: null,
    contract_type: "b2b",
    work_mode: null,
    missing_fields: [],
    orders: [{ status: "active", start_date: "2026-01-01", end_date: "2099-12-31" }],
    ...over,
  };
}

function signIn(
  role: string,
  options: { granted?: Permission[]; realUser?: unknown } = {},
) {
  useAuthStore.setState({
    user: {
      id: 9,
      email: `${role}@example.com`,
      name: role,
      role,
      roles: [role],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      capabilities: [],
      analytics_capabilities: [],
      // Bez `granted` profil liczy się z domyślnych uprawnień roli.
      ...(options.granted
        ? {
            effective_action_access: permissionSnapshot(...options.granted),
            effective_section_access: sectionSnapshot(options.granted),
          }
        : {}),
    },
    realUser: options.realUser ?? null,
    hydrated: true,
  } as never);
}

async function renderRows() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContractorsListV2 />
    </QueryClientProvider>,
  );
  const row = (name: string) =>
    screen.getByRole("link", { name }).closest("tr") as HTMLElement;
  await screen.findByRole("link", { name: "Jan Aktywny" });
  return {
    draft: within(row("Jan Szkic")),
    ready: within(row("Jan Gotowy")),
    active: within(row("Jan Aktywny")),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue({
    data: {
      items: [
        item(1, "Szkic", { status: "draft", missing_fields: ["start_date"] }),
        item(2, "Gotowy", { status: "draft" }),
        item(3, "Aktywny", {}),
      ],
      total: 3,
      page: 1,
      page_size: 50,
    },
  });
  mocks.stats.mockResolvedValue({
    data: { draft: 2, drafts_incomplete: 1, active_contracts: 1, active: 1, ending: 0 },
  });
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("ContractorsListV2 — „Uzupełnij” / „Aktywuj” za edycją kontraktów", () => {
  it.each(["delivery_lead", "finance"])(
    "%s ma edycję kontraktów domyślnie i uzupełnia szkice",
    async (role) => {
      signIn(role);
      const rows = await renderRows();

      expect(rows.draft.getByRole("button", { name: "Uzupełnij" })).toBeInTheDocument();
      expect(rows.ready.getByRole("button", { name: /Aktywuj/ })).toBeInTheDocument();
    },
  );

  it("rekruter z nadaną edycją kontraktów uzupełnia szkice", async () => {
    signIn("recruiter", { granted: ["contracts_orders_edit"] });
    const rows = await renderRows();

    expect(rows.draft.getByRole("button", { name: "Uzupełnij" })).toBeInTheDocument();
    expect(rows.ready.getByRole("button", { name: /Aktywuj/ })).toBeInTheDocument();
  });

  it("Delivery Lead z wyłączoną edycją kontraktów nie dostaje akcji szkicu", async () => {
    signIn("delivery_lead", { granted: ["clients_edit", "contract_status"] });
    const rows = await renderRows();

    expect(rows.draft.queryByRole("button", { name: "Uzupełnij" })).not.toBeInTheDocument();
    expect(rows.ready.queryByRole("button", { name: /Aktywuj/ })).not.toBeInTheDocument();
    // Szczegóły zostają dla każdego, kto widzi listę.
    expect(rows.draft.getByRole("link", { name: /Szczegóły/ })).toBeInTheDocument();
  });

  it("Talent Community Manager (bez edycji kontraktów) nie uzupełnia szkiców", async () => {
    signIn("talent_community_manager");
    const rows = await renderRows();

    expect(rows.draft.queryByRole("button", { name: "Uzupełnij" })).not.toBeInTheDocument();
    expect(rows.ready.queryByRole("button", { name: /Aktywuj/ })).not.toBeInTheDocument();
  });

  it("w podglądzie jako inny użytkownik akcje szkicu znikają", async () => {
    signIn("delivery_lead", { realUser: { id: 1, role: "admin", roles: ["admin"] } });
    const rows = await renderRows();

    expect(rows.draft.queryByRole("button", { name: "Uzupełnij" })).not.toBeInTheDocument();
    expect(rows.ready.queryByRole("button", { name: /Aktywuj/ })).not.toBeInTheDocument();
  });
});

describe("ContractorsListV2 — „Zakończ projekt” za zmianą statusu kontraktu", () => {
  it("Delivery Lead kończy projekt aktywnego kontraktora", async () => {
    signIn("delivery_lead");
    const rows = await renderRows();

    expect(rows.active.getByRole("button", { name: "Zakończ projekt" })).toBeInTheDocument();
    // Szkic nie ma czego kończyć.
    expect(rows.draft.queryByRole("button", { name: "Zakończ projekt" })).not.toBeInTheDocument();
  });

  it("Talent Community Manager kończy projekt — to samo uprawnienie co pojedyncze zakończenie", async () => {
    signIn("talent_community_manager");
    const rows = await renderRows();

    expect(rows.active.getByRole("button", { name: "Zakończ projekt" })).toBeInTheDocument();
  });

  it("Finanse edytują kontrakty, ale nie kończą współpracy", async () => {
    signIn("finance");
    const rows = await renderRows();

    expect(rows.active.queryByRole("button", { name: "Zakończ projekt" })).not.toBeInTheDocument();
  });

  it("w podglądzie jako inny użytkownik „Zakończ projekt” znika", async () => {
    signIn("delivery_lead", { realUser: { id: 1, role: "admin", roles: ["admin"] } });
    const rows = await renderRows();

    expect(rows.active.queryByRole("button", { name: "Zakończ projekt" })).not.toBeInTheDocument();
  });
});
