import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type {
  SectionPermissionsResponse,
  UserSectionPermissionsResponse,
} from "@/lib/section-access";
import { PermissionsTab } from "./PermissionsTab";

vi.mock("@/lib/api", () => ({
  adminApi: {
    getSectionPermissions: vi.fn(),
    searchUserSectionPermissions: vi.fn(),
    updateRoleSectionPermissions: vi.fn(),
    updateUserSectionPermissions: vi.fn(),
  },
  extractErrorMsg: () => "Nie udało się zapisać.",
}));

import { adminApi } from "@/lib/api";

const allWrite = {
  sourcing: "write",
  pipeline: "write",
  delivery: "write",
  insights: "write",
  finance: "write",
  system_admin: "write",
} as const;

const recruiterPermissions = {
  sourcing: "write",
  pipeline: "write",
  delivery: "none",
  insights: "read",
  finance: "none",
  system_admin: "none",
} as const;

const policy: SectionPermissionsResponse = {
  revision: 12,
  roles: [
    { role: "admin", permissions: allWrite, locked: true },
    { role: "recruiter", permissions: recruiterPermissions },
  ],
};

const users: UserSectionPermissionsResponse = {
  revision: 12,
  users: [
    {
      user_id: 42,
      name: "Jan Kowalski",
      email: "jan@example.com",
      role: "recruiter",
      roles: ["recruiter"],
      overrides: {},
      effective_permissions: recruiterPermissions,
    },
  ],
  total: 1,
};

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <PermissionsTab />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient };
}

describe("PermissionsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminApi.getSectionPermissions).mockResolvedValue({
      data: policy,
    } as never);
    vi.mocked(adminApi.searchUserSectionPermissions).mockResolvedValue({
      data: users,
    } as never);
    vi.mocked(adminApi.updateRoleSectionPermissions).mockResolvedValue({
      data: { revision: 13, changed: true, invalidated_users: 1 },
    } as never);
    vi.mocked(adminApi.updateUserSectionPermissions).mockResolvedValue({
      data: { revision: 13, changed: true, invalidated_users: 1 },
    } as never);
  });

  it("zapisuje zbiorczy diff roli dopiero po potwierdzeniu", async () => {
    const user = userEvent.setup();
    renderTab();

    const deliverySelectors = await screen.findAllByLabelText(
      "Rekruter: Delivery",
    );
    fireEvent.change(deliverySelectors[0], { target: { value: "read" } });

    expect(adminApi.updateRoleSectionPermissions).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(
      screen.getByRole("heading", {
        name: "Potwierdź zmianę uprawnień ról",
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Potwierdź i zapisz" }),
    );

    await waitFor(() =>
      expect(adminApi.updateRoleSectionPermissions).toHaveBeenCalledWith(12, [
        { role: "recruiter", section: "delivery", access: "read" },
      ]),
    );
  });

  it("blokuje edycję administratora i sekcji administracji technicznej", async () => {
    renderTab();

    const adminDelivery = await screen.findAllByLabelText(
      "Administrator: Delivery",
    );
    const recruiterSystem = screen.getAllByLabelText(
      "Rekruter: Administracja techniczna",
    );
    const recruiterDelivery = screen.getAllByLabelText("Rekruter: Delivery");

    expect(adminDelivery.every((control) => control.hasAttribute("disabled"))).toBe(
      true,
    );
    expect(
      recruiterSystem.every((control) => control.hasAttribute("disabled")),
    ).toBe(true);
    expect(
      recruiterDelivery.every((control) => !control.hasAttribute("disabled")),
    ).toBe(true);
  });

  it("nadaje i usuwa indywidualny wyjątek z bieżącą rewizją", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("tab", { name: "Wyjątki użytkowników" }),
    );
    const selector = await screen.findByLabelText("Jan Kowalski: Delivery");
    fireEvent.change(selector, { target: { value: "write" } });
    await user.click(screen.getByRole("button", { name: "Zapisz wyjątek" }));
    await user.click(
      screen.getByRole("button", { name: "Potwierdź i zapisz" }),
    );

    await waitFor(() =>
      expect(adminApi.updateUserSectionPermissions).toHaveBeenCalledWith(
        42,
        12,
        [{ section: "delivery", access: "write" }],
      ),
    );
  });

  it("po 409 odświeża snapshot i nie udaje, że zapis się udał", async () => {
    vi.mocked(adminApi.updateRoleSectionPermissions).mockRejectedValueOnce({
      response: { status: 409 },
    });
    const user = userEvent.setup();
    renderTab();

    const deliverySelectors = await screen.findAllByLabelText(
      "Rekruter: Delivery",
    );
    fireEvent.change(deliverySelectors[0], { target: { value: "read" } });
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await user.click(
      screen.getByRole("button", { name: "Potwierdź i zapisz" }),
    );

    expect(
      await screen.findByText("Wczytano nowszą wersję zasad"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(adminApi.getSectionPermissions).toHaveBeenCalledTimes(2),
    );
  });

  it("nie przenosi starego draftu na nowszą rewizję z odświeżenia", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderTab();

    const deliverySelectors = await screen.findAllByLabelText(
      "Rekruter: Delivery",
    );
    fireEvent.change(deliverySelectors[0], { target: { value: "read" } });
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(
      screen.getByRole("heading", {
        name: "Potwierdź zmianę uprawnień ról",
      }),
    ).toBeInTheDocument();

    act(() => {
      queryClient.setQueryData<SectionPermissionsResponse>(
        ["admin-section-permissions"],
        { ...policy, revision: 13 },
      );
    });

    expect(
      await screen.findByText("Wczytano nowszą wersję zasad"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: "Potwierdź zmianę uprawnień ról",
      }),
    ).not.toBeInTheDocument();
    expect(adminApi.updateRoleSectionPermissions).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeDisabled();
  });

  it("zamyka nieaktualny modal wyjątku po zmianie rewizji listy", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderTab();

    await user.click(
      await screen.findByRole("tab", { name: "Wyjątki użytkowników" }),
    );
    fireEvent.change(await screen.findByLabelText("Jan Kowalski: Delivery"), {
      target: { value: "write" },
    });
    await user.click(screen.getByRole("button", { name: "Zapisz wyjątek" }));
    expect(
      screen.getByRole("heading", { name: "Potwierdź indywidualny wyjątek" }),
    ).toBeInTheDocument();

    act(() => {
      queryClient.setQueryData<UserSectionPermissionsResponse>(
        ["admin-user-section-permissions", ""],
        { ...users, revision: 13 },
      );
    });

    expect(
      await screen.findByText("Wczytano nowszą wersję zasad"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        name: "Potwierdź indywidualny wyjątek",
      }),
    ).not.toBeInTheDocument();
    expect(adminApi.updateUserSectionPermissions).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Zapisz wyjątek" })).toBeDisabled();
  });
});
