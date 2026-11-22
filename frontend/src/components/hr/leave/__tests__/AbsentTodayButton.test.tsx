// „Nieobecni dziś” a konta spoza personelu (sprawa Testera z 19.11.2026):
// konto Rady dostawało 403 na `/api/hr/leave/absent-today`. Front nie pyta,
// gdy wszystkie role konta są w `_NOT_STAFF` z `backend/app/api/hr_leave.py`.

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { canReadAbsences } from "@/lib/api/hr-leave";
import { useAuthStore, type User } from "@/store/auth";

const get = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ api: { get } }));
vi.mock("@/lib/api/hr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr")>()),
  useHrConfig: () => ({ data: { open_modules: { leave: true } } }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { AbsentTodayButton } from "../AbsentTodayButton";

const ABSENT = "/api/hr/leave/absent-today";

function renderAs(role: User["role"], roles?: User["role"][]) {
  act(() => useAuthStore.setState({ user: { id: 1, role, roles: roles ?? [role] } as User }));
  get.mockResolvedValue({
    data: {
      date: "2026-11-19",
      total: 1,
      items: [
        {
          user_id: 2,
          name: "Anna Przykładowa",
          until: "2026-11-20",
          half_day: null,
          substitute_user_id: null,
          substitute_name: null,
          substitute_absent: false,
          i_substitute: false,
          is_me: false,
        },
      ],
    },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AbsentTodayButton />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  get.mockReset();
  act(() => useAuthStore.setState({ user: null }));
});

describe("„Nieobecni dziś” — kto pyta o listę", () => {
  it("rekruter pyta i widzi przycisk z liczbą", async () => {
    renderAs("recruiter");
    expect(await screen.findByRole("button", { name: "Nieobecni dziś: 1 osoba" })).toBeTruthy();
    expect(get).toHaveBeenCalledWith(ABSENT);
  });

  it("Rada nie pyta i nie widzi przycisku", async () => {
    const { container } = renderAs("board");
    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(get).not.toHaveBeenCalledWith(ABSENT);
  });
});

describe("canReadAbsences — lustro `require_hr_absence_reader`", () => {
  const user = (role: string, roles?: string[]) => ({ role, roles: roles ?? [role] });

  it("odmawia kontom wyłącznie spoza personelu i bez konta", () => {
    expect(canReadAbsences(null)).toBe(false);
    expect(canReadAbsences(user("board"))).toBe(false);
    expect(canReadAbsences(user("automation"))).toBe(false);
    expect(canReadAbsences(user("user"))).toBe(false);
    expect(canReadAbsences(user("board", ["board", "automation"]))).toBe(false);
  });

  it("wpuszcza personel, admina i konto z choć jedną rolą personelu", () => {
    expect(canReadAbsences(user("recruiter"))).toBe(true);
    expect(canReadAbsences(user("employee"))).toBe(true);
    expect(canReadAbsences(user("admin"))).toBe(true);
    expect(canReadAbsences(user("board", ["board", "admin"]))).toBe(true);
    expect(canReadAbsences(user("user", ["user", "recruiter"]))).toBe(true);
    // Stare konto bez listy `roles` — liczy się `role`.
    expect(canReadAbsences({ role: "board" })).toBe(false);
  });
});
