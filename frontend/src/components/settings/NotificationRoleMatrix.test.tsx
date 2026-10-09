import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationRoleMatrix } from "@/components/settings/NotificationRoleMatrix";
import { api } from "@/lib/api";
import { roleView } from "./__tests__/notification-role-fixtures";

vi.mock("@/lib/api", () => ({ api: { get: vi.fn(), put: vi.fn() } }));

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, hydrated: true }),
  hasRole: (user: { roles?: string[] } | null, ...roles: string[]) =>
    !!user && roles.some((role) => user.roles?.includes(role)),
}));

const ADMIN = {
  role: "admin",
  roles: ["admin"],
  effective_section_access: { system_admin: "write" },
};

function renderMatrix() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <NotificationRoleMatrix />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

function column(name: RegExp) {
  return screen.getByRole("columnheader", { name });
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.put).mockReset();
  vi.mocked(api.get).mockResolvedValue({ data: roleView() } as never);
  mocks.user = ADMIN;
});

describe("NotificationRoleMatrix — kto co dostaje", () => {
  it("pokazuje role z liczbą kont i średnią na osobę; kategoria obowiązkowa nie ma przełącznika", async () => {
    renderMatrix();
    const admin = await screen.findByRole("columnheader", { name: /Admin/ });
    expect(admin).toHaveTextContent("2 konta");
    expect(admin).toHaveTextContent("20 na osobę");
    expect(column(/Rekruter/)).toHaveTextContent("12 na osobę");

    const mandatory = screen.getByRole("row", { name: /Wzmianki/ });
    expect(within(mandatory).queryByRole("switch")).toBeNull();
    expect(within(mandatory).getAllByText("zawsze")).toHaveLength(2);

    expect(screen.getByRole("switch", { name: "Ruchy w rekrutacjach — Rekruter" })).toBeChecked();
    expect(screen.getByText(/Ostatnia zmiana: .* · Aniela Administrująca/)).toBeInTheDocument();
    expect(screen.getByText("Zmiany: 0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zapisz zmiany/ })).toBeDisabled();
  });

  it("zmiana trafia do szkicu, a zapis po potwierdzeniu wysyła tylko zmienione komórki z wersją", async () => {
    const saved = roleView({ revision: 8 }, { pipeline: ["recruiter"] });
    vi.mocked(api.put).mockResolvedValue({ data: saved } as never);
    const user = renderMatrix();

    await user.click(
      await screen.findByRole("switch", { name: "Ruchy w rekrutacjach — Rekruter" }),
    );
    expect(screen.getByText("Zmiany: 1")).toBeInTheDocument();
    // Średnia po zmianie i przekreślona wartość zapisana.
    expect(column(/Rekruter/)).toHaveTextContent("2 na osobę");
    expect(column(/Rekruter/)).toHaveTextContent("było 12");
    expect(api.put).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /Zapisz zmiany/ }));
    const dialog = await screen.findByRole("dialog", {
      name: "Potwierdź zmianę powiadomień ról",
    });
    expect(dialog).toHaveTextContent("Rekruter (4 konta)");
    expect(dialog).toHaveTextContent("Przestanie dostawać:");
    expect(within(dialog).getByText("Ruchy w rekrutacjach")).toBeInTheDocument();
    expect(api.put).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Potwierdź i zapisz" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/settings/notification-roles", {
        revision: 7,
        changes: [{ role: "recruiter", group: "pipeline", muted: true }],
      }),
    );
    expect(await screen.findByText("Zmiany: 0 · Zapisano.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      screen.getByRole("switch", { name: "Ruchy w rekrutacjach — Rekruter" }),
    ).not.toBeChecked();
    // Własny zapis nie jest zgłaszany jako cudza zmiana.
    expect(screen.queryByText("Wczytano nowszą wersję ustawień")).toBeNull();
  });

  it("przełącznik kategorii zmienia wszystkie jej grupy; wiersze grup widać po rozwinięciu", async () => {
    const user = renderMatrix();
    await user.click(
      await screen.findByRole("switch", { name: "Kontrakty i zamówienia — Admin" }),
    );
    expect(screen.getByText("Zmiany: 2")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Koniec umowy — Admin" })).toBeNull();

    await user.click(screen.getByRole("button", { name: /Rozwiń \(2\)/ }));
    expect(screen.getByRole("switch", { name: "Koniec umowy — Admin" })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Koniec zamówienia — Admin" })).not.toBeChecked();
    expect(screen.getByRole("switch", { name: "Koniec umowy — Rekruter" })).toBeChecked();

    // Jedna grupa z powrotem = stan mieszany, przełącznik kategorii zostaje wyłączony.
    await user.click(screen.getByRole("switch", { name: "Koniec umowy — Admin" }));
    expect(screen.getByText("Zmiany: 1")).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "Kontrakty i zamówienia — Admin" }),
    ).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: /Cofnij/ }));
    expect(screen.getByText("Zmiany: 0")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Koniec zamówienia — Admin" })).toBeChecked();
  });

  it("409 „ktoś zapisał wcześniej”: komunikat z serwera, ponowne wczytanie i brak szkicu", async () => {
    vi.mocked(api.put).mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: "stale_notification_roles",
            message: "Ktoś zmienił te ustawienia w międzyczasie. Wczytaj je ponownie i powtórz zmianę.",
          },
        },
      },
    });
    const user = renderMatrix();
    await user.click(
      await screen.findByRole("switch", { name: "Ruchy w rekrutacjach — Admin" }),
    );
    await user.click(screen.getByRole("button", { name: /Zapisz zmiany/ }));
    await user.click(await screen.findByRole("button", { name: "Potwierdź i zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ktoś zmienił te ustawienia w międzyczasie. Wczytaj je ponownie i powtórz zmianę.",
    );
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("Zmiany: 0")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Ruchy w rekrutacjach — Admin" })).toBeChecked();
  });

  it("inny błąd zapisu zostawia szkic i mówi, że nic się nie zapisało", async () => {
    vi.mocked(api.put).mockRejectedValue(new Error("network unavailable"));
    const user = renderMatrix();
    await user.click(
      await screen.findByRole("switch", { name: "Ruchy w rekrutacjach — Admin" }),
    );
    await user.click(screen.getByRole("button", { name: /Zapisz zmiany/ }));
    await user.click(await screen.findByRole("button", { name: "Potwierdź i zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Zmiany nie zostały zapisane");
    expect(screen.getByText("Zmiany: 1")).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it.each([403, 500])("błąd GET %s nie pokazuje pustej tabeli", async (status) => {
    vi.mocked(api.get).mockRejectedValue({ response: { status } });
    renderMatrix();
    await screen.findByText(status === 403 ? "Brak uprawnień" : "Nie udało się pobrać danych");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("odpowiedź bez ról to awaria, nie pusta tabela", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: roleView({ roles: [] }) } as never);
    renderMatrix();
    await screen.findByText("Nie udało się pobrać danych");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("dostęp tylko do odczytu: przełączniki i zapis są wyłączone", async () => {
    mocks.user = { ...ADMIN, effective_section_access: { system_admin: "read" } };
    renderMatrix();
    expect(await screen.findByText("Masz dostęp tylko do odczytu.")).toBeInTheDocument();
    for (const toggle of screen.getAllByRole("switch")) expect(toggle).toBeDisabled();
  });

  it("konto bez roli administratora nie pyta o tabelę", () => {
    mocks.user = { role: "recruiter", roles: ["recruiter"], effective_section_access: { system_admin: "write" } };
    renderMatrix();
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
