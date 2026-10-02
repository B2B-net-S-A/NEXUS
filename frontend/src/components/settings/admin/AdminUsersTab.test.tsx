import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { useAuthStore, type User } from "@/store/auth";
import { AdminUsersTab, impersonationProfile } from "./AdminUsersTab";
import {
  permissionsSnapshot,
  userPermissionsResponse,
} from "./__tests__/permission-fixtures";
import type { AdminUser } from "./types";

const address = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(address.search),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  adminApi: {
    listUsers: vi.fn(),
    startImpersonation: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    getSectionPermissions: vi.fn(),
    getUserPermissions: vi.fn(),
    updateRoleSectionPermissions: vi.fn(),
    updateUserSectionPermissions: vi.fn(),
  },
}));

import { adminApi } from "@/lib/api";

function account(extra: Partial<AdminUser> & Pick<AdminUser, "id" | "name" | "role">): AdminUser {
  return {
    email: `konto${extra.id}@example.com`,
    roles: [extra.role],
    is_active: true,
    can_delete_clients: false,
    extra_permissions: [],
    activity_count: 0,
    last_activity: null,
    created_at: "2026-01-05T09:00:00",
    ...extra,
  };
}

const USERS: AdminUser[] = [
  account({
    id: 90,
    name: "Celina Wzorcowa",
    role: "talent_community_manager",
    extra_permissions: ["contracts_orders_edit"],
  }),
  account({
    id: 91,
    name: "Borys Przykładowy",
    role: "recruiter",
    extra_permissions: ["delivery_view", "amounts_view"],
  }),
  account({
    id: 92,
    name: "Daria Testowa",
    role: "sourcer",
    extra_permissions: [
      "delivery_view",
      "clients_edit",
      "contracts_orders_edit",
      "contract_status",
      "recruitment_manage",
    ],
  }),
  account({ id: 93, name: "Emil Fikcyjny", role: "finance" }),
];

const ADMIN = {
  id: 1,
  email: "admin@example.com",
  name: "Aniela Administrująca",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
} as User;

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AdminUsersTab embedded />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** Odmowa serwera w kształcie axiosa — `extractErrorMsg` czyta tylko taki. */
function refusal(status: number, detail: Record<string, unknown>) {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data: { detail },
  } as AxiosResponse);
}

async function openEditFor(name: string) {
  const user = userEvent.setup();
  renderTab();
  const row = await screen.findByRole("row", { name: new RegExp(name) });
  await user.click(within(row).getByRole("button", { name: "Edytuj" }));
  const group = await screen.findByRole("group", { name: "Dodatkowe uprawnienia" });
  await waitFor(() =>
    expect(within(group).queryByRole("status")).not.toBeInTheDocument(),
  );
  return { user, group };
}

const impersonate = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  address.search = "";
  useAuthStore.setState({ user: ADMIN, realUser: null, hydrated: true, impersonate });
  vi.mocked(adminApi.listUsers).mockResolvedValue({ data: USERS } as never);
  vi.mocked(adminApi.getSectionPermissions).mockResolvedValue({
    data: permissionsSnapshot(),
  } as never);
  vi.mocked(adminApi.getUserPermissions).mockResolvedValue({
    data: userPermissionsResponse({ grants: ["contracts_orders_edit"] }),
  } as never);
  vi.mocked(adminApi.updateUser).mockResolvedValue({ data: {} } as never);
  vi.mocked(adminApi.updateUserSectionPermissions).mockResolvedValue({
    data: { revision: 13, changed: true, invalidated_users: 1 },
  } as never);
});

describe("AdminUsersTab — Osoby i role", () => {
  it("ma dwie zakładki: Użytkownicy i Uprawnienia", async () => {
    renderTab();
    await screen.findByRole("row", { name: /Celina Wzorcowa/ });

    expect(screen.getByRole("button", { name: "Użytkownicy" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Uprawnienia" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    for (const gone of ["System", "Log aktywności", "Import CV", "Narzędzia"]) {
      expect(screen.queryByRole("button", { name: gone })).not.toBeInTheDocument();
    }
  });

  it("stary albo nieznany `?sub=` otwiera Użytkowników zamiast wywracać ekran", async () => {
    address.search = "sub=user-overrides";
    renderTab();

    expect(await screen.findByRole("row", { name: /Celina Wzorcowa/ })).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("`?sub=permissions` otwiera przełączniki ról", async () => {
    address.search = "sub=permissions";
    renderTab();

    expect(await screen.findAllByRole("switch")).toHaveLength(9);
    expect(adminApi.listUsers).not.toHaveBeenCalled();
  });

  it("plakietka dodatkowych uprawnień: liczba po polsku i nazwy w podpowiedzi", async () => {
    renderTab();

    const one = within(await screen.findByRole("row", { name: /Celina Wzorcowa/ })).getByText(
      "+1 uprawnienie",
    );
    expect(one).toHaveAttribute("title", "Kontrakty i zamówienia: tworzenie i edycja");
    expect(
      within(screen.getByRole("row", { name: /Borys Przykładowy/ })).getByText("+2 uprawnienia"),
    ).toHaveAttribute(
      "title",
      "Klienci, kontrakty i zamówienia: podgląd, Stawki i kwoty: podgląd",
    );
    expect(
      within(screen.getByRole("row", { name: /Daria Testowa/ })).getByText("+5 uprawnień"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("row", { name: /Emil Fikcyjny/ })).queryByText(/uprawnie/),
    ).not.toBeInTheDocument();
  });

  it("zapis: najpierw konto, potem uprawnienia tej osoby", async () => {
    const { user, group } = await openEditFor("Celina Wzorcowa");

    await user.click(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Edytuj użytkownika" }),
      ).not.toBeInTheDocument(),
    );
    expect(adminApi.updateUser).toHaveBeenCalledWith(90, {
      name: "Celina Wzorcowa",
      role: "talent_community_manager",
      roles: ["talent_community_manager"],
      can_delete_clients: false,
    });
    expect(adminApi.updateUserSectionPermissions).toHaveBeenCalledWith(
      90,
      12,
      [],
      [{ action: "clients_edit", access: "manage" }],
    );
    expect(
      vi.mocked(adminApi.updateUser).mock.invocationCallOrder[0],
    ).toBeLessThan(
      vi.mocked(adminApi.updateUserSectionPermissions).mock.invocationCallOrder[0],
    );
  });

  it("bez zmiany uprawnień zapisuje wyłącznie konto", async () => {
    const { user } = await openEditFor("Celina Wzorcowa");

    await user.click(screen.getByRole("checkbox", { name: "Może usuwać klientów" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Edytuj użytkownika" }),
      ).not.toBeInTheDocument(),
    );
    expect(adminApi.updateUser).toHaveBeenCalledWith(
      90,
      expect.objectContaining({ can_delete_clients: true }),
    );
    expect(adminApi.updateUserSectionPermissions).not.toHaveBeenCalled();
  });

  it("gdy uprawnienia się nie zapiszą, okno zostaje i mówi, która połowa przeszła", async () => {
    vi.mocked(adminApi.updateUserSectionPermissions).mockRejectedValueOnce(
      refusal(409, {
        code: "permission_storage_rejected",
        message: "Baza nie przyjęła zmiany uprawnień. Zgłoś to administratorowi systemu.",
      }),
    );
    const { user, group } = await openEditFor("Celina Wzorcowa");

    await user.click(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dane konta zostały zapisane, ale uprawnień nie udało się zapisać. Baza nie przyjęła zmiany uprawnień. Zgłoś to administratorowi systemu.",
    );
    expect(screen.getByRole("heading", { name: "Edytuj użytkownika" })).toBeInTheDocument();
    expect(adminApi.updateUser).toHaveBeenCalledTimes(1);
    // To nie jest „nowsza wersja zasad” — zaznaczenie zostaje do ponowienia.
    expect(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    ).toBeChecked();
    expect(screen.getByRole("alert")).not.toHaveTextContent("zmienił zasady");
  });

  it("po 409 „ktoś zapisał wcześniej” wczytuje uprawnienia od nowa i prosi o powtórzenie", async () => {
    vi.mocked(adminApi.updateUserSectionPermissions).mockRejectedValueOnce(
      refusal(409, {
        code: "stale_section_policy",
        expected_revision: 12,
        current_revision: 13,
      }),
    );
    const { user, group } = await openEditFor("Celina Wzorcowa");
    vi.mocked(adminApi.getUserPermissions).mockResolvedValue({
      data: userPermissionsResponse({ grants: ["contracts_orders_edit"] }, 13),
    } as never);

    await user.click(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dane konta zostały zapisane, ale uprawnienia nie: ktoś zmienił zasady w międzyczasie. Wczytaliśmy aktualną wersję — zaznacz uprawnienia jeszcze raz i zapisz.",
    );
    await waitFor(() => expect(adminApi.getUserPermissions).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
      ).not.toBeChecked(),
    );
    expect(screen.getByRole("heading", { name: "Edytuj użytkownika" })).toBeInTheDocument();
  });

  it("odmowa zapisu konta nie wysyła uprawnień", async () => {
    vi.mocked(adminApi.updateUser).mockRejectedValueOnce(
      refusal(422, { message: "Nie można łączyć roli Finanse z inną rolą." }),
    );
    const { user, group } = await openEditFor("Celina Wzorcowa");

    await user.click(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie można łączyć roli Finanse z inną rolą.",
    );
    expect(adminApi.updateUserSectionPermissions).not.toHaveBeenCalled();
  });

  it("zakładanie konta nie pyta o uprawnienia i nie wysyła ich", async () => {
    vi.mocked(adminApi.createUser).mockResolvedValue({ data: {} } as never);
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("row", { name: /Celina Wzorcowa/ });

    await user.click(screen.getByRole("button", { name: "Dodaj użytkownika" }));
    expect(
      screen.queryByRole("group", { name: "Dodatkowe uprawnienia" }),
    ).not.toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Jan Kowalski"), "Gaja Nowa");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() => expect(adminApi.createUser).toHaveBeenCalledTimes(1));
    expect(vi.mocked(adminApi.createUser).mock.calls[0][0]).not.toHaveProperty(
      "permissions",
    );
    expect(adminApi.getUserPermissions).not.toHaveBeenCalled();
    expect(adminApi.updateUserSectionPermissions).not.toHaveBeenCalled();
  });

  it("niezapisane przełączniki: zmiana zakładki pyta w oknie aplikacji", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    address.search = "sub=permissions";
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Użytkownicy" }));

    let dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Masz niezapisane zmiany uprawnień. Odrzucić je i przejść dalej?",
    );
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(
      screen.getByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    ).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Użytkownicy" }));
    dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Odrzuć zmiany" }));

    expect(await screen.findByRole("row", { name: /Celina Wzorcowa/ })).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(nativeConfirm).not.toHaveBeenCalled();
    nativeConfirm.mockRestore();
  });

  it("bez zmian zakładka przełącza się od razu", async () => {
    address.search = "sub=permissions";
    const user = userEvent.setup();
    renderTab();
    await screen.findAllByRole("switch");

    await user.click(screen.getByRole("button", { name: "Użytkownicy" }));

    expect(await screen.findByRole("row", { name: /Celina Wzorcowa/ })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("podgląd jako użytkownik", () => {
  const profile = {
    id: 90,
    email: "konto90@example.com",
    name: "Celina Wzorcowa",
    role: "talent_community_manager",
    roles: ["talent_community_manager"],
    profile_completed: false,
    profile_completed_at: null,
    force_password_change: true,
    force_password_change_at: "2026-09-30T10:00:00",
    can_delete_clients: true,
    delivery_client_scope: "assigned",
    capabilities: ["view_team_kpi"],
    effective_section_access: { delivery: "write", finance: "none" },
    effective_action_access: {
      b2b_contract_generator: "manage",
      delivery_view: "manage",
      contracts_orders_edit: "manage",
      amounts_view: "none",
    },
  } as unknown as User;

  it("przekazuje odpowiedź serwera w całości — z uprawnieniami konta", async () => {
    vi.mocked(adminApi.startImpersonation).mockResolvedValue({ data: profile } as never);
    const user = userEvent.setup();
    renderTab();

    const row = await screen.findByRole("row", { name: /Celina Wzorcowa/ });
    await user.click(
      within(row).getByRole("button", { name: "Podgląd jako ten użytkownik" }),
    );

    await waitFor(() => expect(impersonate).toHaveBeenCalledTimes(1));
    expect(adminApi.startImpersonation).toHaveBeenCalledWith(90);
    expect(impersonate).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 90,
        effective_action_access: profile.effective_action_access,
        effective_section_access: profile.effective_section_access,
        can_delete_clients: true,
        delivery_client_scope: "assigned",
        capabilities: ["view_team_kpi"],
      }),
    );
  });

  it("podgląd nie przechodzi cudzego onboardingu ani wymuszonej zmiany hasła", () => {
    expect(impersonationProfile(profile)).toMatchObject({
      profile_completed: true,
      force_password_change: false,
      force_password_change_at: null,
      allowed_sections: [],
    });
  });

  it("uzupełnia listę ról, gdy odpowiedź jej nie niesie", () => {
    const { roles: _roles, ...withoutRoles } = profile;
    expect(impersonationProfile(withoutRoles as User).roles).toEqual([
      "talent_community_manager",
    ]);
  });
});
