import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { AdminPermissionsSnapshot } from "@/lib/admin-permissions";
import { PermissionsTab } from "./PermissionsTab";
import { permissionsSnapshot } from "./__tests__/permission-fixtures";

vi.mock("@/lib/api", () => ({
  adminApi: {
    getSectionPermissions: vi.fn(),
    updateRoleSectionPermissions: vi.fn(),
  },
}));

import { adminApi } from "@/lib/api";

const policy = permissionsSnapshot();

function renderTab(props: Parameters<typeof PermissionsTab>[0] = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <PermissionsTab {...props} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient };
}

function permissionSwitch(name: string) {
  return screen.getByRole("switch", { name });
}

describe("PermissionsTab — jedna rola, dziewięć przełączników", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminApi.getSectionPermissions).mockResolvedValue({
      data: policy,
    } as never);
    vi.mocked(adminApi.updateRoleSectionPermissions).mockResolvedValue({
      data: { revision: 13, changed: true, invalidated_users: 1 },
    } as never);
  });

  it("pokazuje role do nadania — bez administratora, viewera i praktykanta", async () => {
    renderTab();

    const roles = await screen.findByRole("group", { name: "Rola" });
    expect(
      within(roles)
        .getAllByRole("button")
        .map((chip) => chip.textContent),
    ).toEqual([
      "Finanse",
      "Head of Recruitment",
      "Delivery Lead",
      "Talent Community Manager",
      "Rekruter",
    ]);
    expect(screen.getByRole("button", { name: "Finanse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const sentence = screen.getByText(/Każda rola może pracować z kandydatami/);
    expect(sentence).toHaveTextContent(
      "Finanse · 1 osoba. Każda rola może pracować z kandydatami, prowadzić rekrutacje i generować umowy B2B. Administrator ma wszystkie uprawnienia.",
    );
  });

  it("nie ma już tabeli sekcji, funkcji specjalnych ani wyjątków użytkowników", async () => {
    renderTab();
    await screen.findByRole("group", { name: "Rola" });

    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Funkcje specjalne")).not.toBeInTheDocument();
    expect(screen.queryByText(/Wyjątki użytkowników/)).not.toBeInTheDocument();
  });

  it("rysuje trzy grupy i dziewięć przełączników ze stanem roli", async () => {
    renderTab();
    await screen.findByRole("group", { name: "Rola" });

    for (const [name, switches] of [
      ["Klienci i kontrakty", 5],
      ["Rekrutacje", 1],
      ["Pieniądze", 3],
    ] as const) {
      expect(
        within(screen.getByRole("group", { name })).getAllByRole("switch"),
      ).toHaveLength(switches);
    }
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
    ).toEqual(["Klienci i kontrakty", "Rekrutacje", "Pieniądze"]);
    expect(screen.getAllByRole("switch")).toHaveLength(9);
    expect(
      permissionSwitch("Finanse: Kontrakty i zamówienia: tworzenie i edycja"),
    ).toBeChecked();
    expect(permissionSwitch("Finanse: Moduł Finanse")).toBeChecked();
    expect(permissionSwitch("Finanse: Klienci: dodawanie i edycja")).not.toBeChecked();
    expect(
      permissionSwitch("Finanse: Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta"),
    ).not.toBeChecked();
  });

  it("Delivery Lead: liczba osób i zdanie o swoich klientach", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Delivery Lead" }));

    expect(
      screen.getByText(/Każda rola może pracować z kandydatami/),
    ).toHaveTextContent(
      "Delivery Lead · 7 osób. Każda rola może pracować z kandydatami, prowadzić rekrutacje i generować umowy B2B. Delivery Lead robi wszystko poniżej tylko u swoich klientów.",
    );
    expect(permissionSwitch("Delivery Lead: Klienci: dodawanie i edycja")).toBeChecked();
  });

  it("zapisuje dokładnie przełączone uprawnienie, dopiero po potwierdzeniu", async () => {
    const user = userEvent.setup();
    renderTab();

    const clientsEdit = await screen.findByRole("switch", {
      name: "Finanse: Klienci: dodawanie i edycja",
    });
    expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeDisabled();
    await user.click(clientsEdit);

    expect(clientsEdit).toBeChecked();
    expect(screen.getByText("zmiana · dziś: nie")).toBeInTheDocument();
    expect(screen.getByText("1 zmiana do zapisania")).toBeInTheDocument();
    expect(adminApi.updateRoleSectionPermissions).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByRole("heading", {
        name: "Potwierdź zmianę uprawnień roli Finanse",
      }),
    ).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Rola Finanse dostanie:");
    expect(within(dialog).getByRole("listitem")).toHaveTextContent(
      "Klienci: dodawanie i edycja",
    );
    expect(dialog).toHaveTextContent(
      "Po zapisaniu 1 osoba z rolą Finanse zostanie wylogowana i zaloguje się ponownie.",
    );
    expect(adminApi.updateRoleSectionPermissions).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Potwierdź i zapisz" }));

    await waitFor(() =>
      expect(adminApi.updateRoleSectionPermissions).toHaveBeenCalledWith(
        12,
        [],
        [{ role: "finance", action: "clients_edit", access: "manage" }],
      ),
    );
    expect(adminApi.updateRoleSectionPermissions).toHaveBeenCalledTimes(1);
  });

  it("uprawnienie wymagane przez włączone jest włączone, zablokowane i podpisane", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Rekruter" }));
    const view = permissionSwitch("Rekruter: Stawki i kwoty: podgląd");
    expect(view).not.toBeChecked();
    expect(view).toBeEnabled();

    await user.click(permissionSwitch("Rekruter: Stawki i kwoty: zmiana"));

    expect(view).toBeChecked();
    expect(view).toBeDisabled();
    expect(view).toHaveAccessibleDescription("Wymagane przez: „Stawki i kwoty: zmiana”");
    expect(
      permissionSwitch("Rekruter: Klienci, kontrakty i zamówienia: podgląd"),
    ).toBeDisabled();
    expect(screen.getByText("3 zmiany do zapisania")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Klienci, kontrakty i zamówienia: podgląd — wymagane przez „Stawki i kwoty: zmiana”",
      "Stawki i kwoty: podgląd — wymagane przez „Stawki i kwoty: zmiana”",
      "Stawki i kwoty: zmiana",
    ]);
    expect(dialog).toHaveTextContent(
      "Po zapisaniu 8 osób z rolą Rekruter zostanie wylogowanych i zaloguje się ponownie.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Potwierdź i zapisz" }));

    // Wiersze, które tylko wynikają z włączonego, nie idą do zapisu.
    await waitFor(() =>
      expect(adminApi.updateRoleSectionPermissions).toHaveBeenCalledWith(
        12,
        [],
        [{ role: "recruiter", action: "amounts_edit", access: "manage" }],
      ),
    );
  });

  it("wyłączenie wysyła „none” i mówi, co rola straci", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: "Delivery Lead" }));
    await user.click(
      permissionSwitch(
        "Delivery Lead: Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
      ),
    );
    expect(screen.getByText("zmiana · dziś: tak")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Rola Delivery Lead straci:");
    expect(dialog).toHaveTextContent(
      "Po zapisaniu 7 osób z rolą Delivery Lead zostanie wylogowanych i zaloguje się ponownie.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Potwierdź i zapisz" }));

    await waitFor(() =>
      expect(adminApi.updateRoleSectionPermissions).toHaveBeenCalledWith(
        12,
        [],
        [{ role: "delivery_lead", action: "recruitment_manage", access: "none" }],
      ),
    );
  });

  it("„Cofnij” wraca do stanu z serwera i zgłasza rodzicowi brak zmian", async () => {
    const onDirtyChange = vi.fn();
    const user = userEvent.setup();
    renderTab({ onDirtyChange });

    const status = await screen.findByRole("switch", {
      name: "Finanse: Zakończenie współpracy, zmiana statusu kontraktu",
    });
    expect(screen.getByText("Brak niezapisanych zmian")).toBeInTheDocument();
    await user.click(status);
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);

    await user.click(screen.getByRole("button", { name: /Cofnij/ }));

    expect(status).not.toBeChecked();
    expect(screen.getByText("Brak niezapisanych zmian")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeDisabled();
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  });

  it("zmiana roli z niezapisanymi zmianami pyta w oknie aplikacji", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Rekruter" }));

    let dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Masz niezapisane zmiany uprawnień. Odrzucić je i przejść dalej?",
    );
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Finanse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(permissionSwitch("Finanse: Klienci: dodawanie i edycja")).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Rekruter" }));
    dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Odrzuć zmiany" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Rekruter" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(screen.getByText("Brak niezapisanych zmian")).toBeInTheDocument();
    // Bez zmian przełączenie roli nie pyta o nic.
    await user.click(screen.getByRole("button", { name: "Delivery Lead" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(nativeConfirm).not.toHaveBeenCalled();
    nativeConfirm.mockRestore();
  });

  it("po 409 odświeża zasady i nie udaje, że zapis się udał", async () => {
    vi.mocked(adminApi.updateRoleSectionPermissions).mockRejectedValueOnce({
      response: { status: 409, data: { detail: { code: "stale_section_policy" } } },
    });
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await user.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

    expect(
      await screen.findByText("Wczytano nowszą wersję zasad"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(adminApi.getSectionPermissions).toHaveBeenCalledTimes(2),
    );
    expect(screen.queryByText(/Zapisano uprawnienia/)).not.toBeInTheDocument();
  });

  it("odmowa bazy (też 409) pokazuje zdanie z serwera i zostawia szkic", async () => {
    vi.mocked(adminApi.updateRoleSectionPermissions).mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: "permission_storage_rejected",
            message: "Baza nie przyjęła zmiany uprawnień. Zgłoś to administratorowi systemu.",
          },
        },
      },
    });
    const user = userEvent.setup();
    renderTab();

    const clientsEdit = await screen.findByRole("switch", {
      name: "Finanse: Klienci: dodawanie i edycja",
    });
    await user.click(clientsEdit);
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await user.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

    expect(
      await screen.findByText(
        "Baza nie przyjęła zmiany uprawnień. Zgłoś to administratorowi systemu.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Wczytano nowszą wersję zasad")).not.toBeInTheDocument();
    expect(adminApi.getSectionPermissions).toHaveBeenCalledTimes(1);
    expect(clientsEdit).toBeChecked();
    expect(screen.getByText("1 zmiana do zapisania")).toBeInTheDocument();
  });

  it("odmowa bez zdania z serwera dostaje polski komunikat, nie surowy błąd", async () => {
    vi.mocked(adminApi.updateRoleSectionPermissions).mockRejectedValueOnce({
      response: { status: 500, data: {} },
    });
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await user.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

    expect(await screen.findByText("Nie udało się zapisać uprawnień.")).toBeInTheDocument();
  });

  it("zapis, który nikogo nie wylogował, nie mówi o wylogowaniu", async () => {
    vi.mocked(adminApi.updateRoleSectionPermissions).mockResolvedValueOnce({
      data: { revision: 12, changed: false, invalidated_users: 0 },
    } as never);
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await user.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

    expect(
      await screen.findByText("Zapisano uprawnienia roli Finanse."),
    ).toBeInTheDocument();
  });

  it("po udanym zapisie mówi, ile osób zaloguje się ponownie", async () => {
    vi.mocked(adminApi.updateRoleSectionPermissions).mockResolvedValueOnce({
      data: { revision: 13, changed: true, invalidated_users: 3 },
    } as never);
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await user.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

    expect(
      await screen.findByText(
        "Zapisano uprawnienia roli Finanse. 3 osoby zalogują się ponownie.",
      ),
    ).toBeInTheDocument();
  });

  it("nowa wersja zasad z serwera porzuca lokalny szkic i zamyka potwierdzenie", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(
      screen.getByRole("heading", { name: "Potwierdź zmianę uprawnień roli Finanse" }),
    ).toBeInTheDocument();

    act(() => {
      queryClient.setQueryData<AdminPermissionsSnapshot>(
        ["admin-section-permissions"],
        { ...policy, revision: 13 },
      );
    });

    expect(
      await screen.findByText("Wczytano nowszą wersję zasad"),
    ).toBeInTheDocument();
    // Tu nikt nie zapisywał — komunikat mówi o zmianach, nie o „poprzednim zapisie”.
    expect(screen.getByText(/Twoje zmiany nie zostały zapisane/)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Potwierdź zmianę uprawnień roli Finanse" }),
    ).not.toBeInTheDocument();
    expect(adminApi.updateRoleSectionPermissions).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeDisabled();
    expect(permissionSwitch("Finanse: Klienci: dodawanie i edycja")).not.toBeChecked();
  });

  it("błąd odczytu to komunikat z ponowieniem, nie pusta lista", async () => {
    vi.mocked(adminApi.getSectionPermissions).mockRejectedValueOnce(
      new Error("sieć"),
    );
    const user = userEvent.setup();
    renderTab();

    expect(screen.getByRole("status")).toHaveTextContent("Wczytywanie uprawnień…");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać uprawnień ról.");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: /Spróbuj ponownie/ }));

    expect(await screen.findAllByRole("switch")).toHaveLength(9);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("nieudane odświeżenie w tle zostawia ekran i niezapisane przełączniki", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderTab();

    const clientsEdit = await screen.findByRole("switch", {
      name: "Finanse: Klienci: dodawanie i edycja",
    });
    await user.click(clientsEdit);

    vi.mocked(adminApi.getSectionPermissions).mockRejectedValueOnce(new Error("sieć"));
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: ["admin-section-permissions"] });
    });

    expect(
      await screen.findByText("Nie udało się odświeżyć uprawnień"),
    ).toBeInTheDocument();
    expect(clientsEdit).toBeChecked();
    expect(screen.getByText("1 zmiana do zapisania")).toBeInTheDocument();
  });

  it("po zapisie okno potwierdzenia znika, a przełączniki pokazują stan z serwera", async () => {
    const saved = permissionsSnapshot({ revision: 13 });
    const finance = saved.roles.find((entry) => entry.role === "finance");
    if (finance?.named.clients_edit) {
      finance.named.clients_edit = { granted: true, effective: true, implied_by: [] };
    }
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    vi.mocked(adminApi.getSectionPermissions).mockResolvedValue({ data: saved } as never);
    await user.click(screen.getByRole("button", { name: "Potwierdź i zapisz" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(permissionSwitch("Finanse: Klienci: dodawanie i edycja")).toBeChecked();
    expect(screen.getByText("Brak niezapisanych zmian")).toBeInTheDocument();
    expect(screen.queryByText("Wczytano nowszą wersję zasad")).not.toBeInTheDocument();
    expect(screen.queryByText("zmiana · dziś: nie")).not.toBeInTheDocument();
  });

  it("w trakcie zapisu okna nie da się zamknąć, a przełączniki czekają na odpowiedź", async () => {
    let finishSave: (value: unknown) => void = () => undefined;
    vi.mocked(adminApi.updateRoleSectionPermissions).mockReturnValueOnce(
      new Promise((resolve) => {
        finishSave = resolve;
      }) as never,
    );
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("switch", { name: "Finanse: Klienci: dodawanie i edycja" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Potwierdź i zapisz" }));

    // Zamknięte w trakcie zapisu okno odsłaniało przełączniki: zmiana zrobiona
    // w tym czasie znikała bez słowa razem ze szkicem, gdy zapis się kończył.
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Anuluj" })).toBeDisabled(),
    );
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    for (const control of screen.getAllByRole("switch", { hidden: true })) {
      expect(control).toBeDisabled();
    }
    for (const name of ["Finanse", "Rekruter", "Delivery Lead"]) {
      expect(screen.getByRole("button", { name, hidden: true })).toBeDisabled();
    }

    await act(async () => {
      finishSave({ data: { revision: 13, changed: true, invalidated_users: 1 } });
    });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(
      await screen.findByText(/Zapisano uprawnienia roli Finanse/),
    ).toBeInTheDocument();
    expect(adminApi.updateRoleSectionPermissions).toHaveBeenCalledTimes(1);
    expect(permissionSwitch("Finanse: Moduł Finanse")).toBeEnabled();
  });

  it("odpowiedź bez listy uprawnień jest awarią, a nie dziewięcioma wyłączonymi przełącznikami", async () => {
    vi.mocked(adminApi.getSectionPermissions).mockResolvedValue({
      data: {
        revision: 12,
        roles: [{ role: "recruiter", permissions: {}, action_permissions: {} }],
      },
    } as never);
    renderTab();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się pobrać uprawnień ról.",
    );
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
});
