import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { useAuthStore, type User } from "@/store/auth";
import { AdminUsersTab } from "./AdminUsersTab";
import type { AdminUser } from "./types";

vi.mock("@/lib/api/hr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr")>()),
  useHrProgram: () => true,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  adminApi: {
    listUsers: vi.fn(),
    resetPassword: vi.fn(),
    sendResetLink: vi.fn(),
  },
}));

import { adminApi } from "@/lib/api";

const ACCOUNT: AdminUser = {
  id: 90,
  name: "Celina Wzorcowa",
  email: "konto90@example.com",
  role: "recruiter",
  roles: ["recruiter"],
  is_active: true,
  can_delete_clients: false,
  extra_permissions: [],
  activity_count: 0,
  last_activity: null,
  created_at: "2026-01-05T09:00:00",
};

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

function refusal(detail: string) {
  return { response: { status: 422, data: { detail } } };
}

async function openResetFor(name: string) {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AdminUsersTab embedded />
      </ToastProvider>
    </QueryClientProvider>,
  );
  const row = await screen.findByRole("row", { name: new RegExp(name) });
  await user.click(within(row).getByRole("button", { name: `Więcej: ${name}` }));
  await user.click(await screen.findByRole("menuitem", { name: "Resetuj hasło" }));
  await screen.findByRole("heading", { name: "Reset hasła" });
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: ADMIN, realUser: null, hydrated: true });
  vi.mocked(adminApi.listUsers).mockResolvedValue({ data: [ACCOUNT] } as never);
});

describe("AdminUsersTab — nieudany reset hasła", () => {
  it("odmowa ręcznego hasła: komunikat w oknie, okno i wpisane hasło zostają", async () => {
    vi.mocked(adminApi.resetPassword).mockRejectedValue(
      refusal("Hasło jest zbyt podobne do adresu e-mail."),
    );
    const user = await openResetFor("Celina Wzorcowa");

    await user.type(screen.getByPlaceholderText("Nowe hasło (min. 8 znaków)"), "Tymczasowe123");
    await user.click(screen.getByRole("button", { name: "Resetuj hasło" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Hasło jest zbyt podobne do adresu e-mail.",
    );
    expect(adminApi.resetPassword).toHaveBeenCalledWith(90, "Tymczasowe123");
    expect(screen.getByRole("heading", { name: "Reset hasła" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Nowe hasło (min. 8 znaków)")).toHaveValue(
      "Tymczasowe123",
    );
  });

  it("nieudana wysyłka linku: komunikat w oknie, okno zostaje", async () => {
    vi.mocked(adminApi.sendResetLink).mockRejectedValue(
      refusal("Nie udało się wysłać wiadomości."),
    );
    const user = await openResetFor("Celina Wzorcowa");

    await user.click(screen.getByRole("button", { name: "Wyślij link mailem" }));
    await user.click(screen.getByRole("button", { name: "Wyślij link" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wysłać wiadomości.",
    );
    expect(adminApi.sendResetLink).toHaveBeenCalledWith(90);
    expect(screen.getByRole("heading", { name: "Reset hasła" })).toBeInTheDocument();
  });
});
