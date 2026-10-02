import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminUserPermissionsResponse } from "@/lib/admin-permissions";
import { UserModal } from "./UserModal";
import {
  permissionsSnapshot,
  userPermissionsResponse,
} from "./__tests__/permission-fixtures";

vi.mock("@/lib/api", () => ({
  adminApi: {
    getSectionPermissions: vi.fn(),
    getUserPermissions: vi.fn(),
  },
}));

import { adminApi } from "@/lib/api";

type ModalProps = Parameters<typeof UserModal>[0];

function renderModal(props: Partial<ModalProps> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onSave = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <UserModal
        initial={{ role: "recruiter", roles: ["recruiter"] }}
        onClose={vi.fn()}
        onSave={onSave}
        loading={false}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onSave, queryClient };
}

function personIs(response: AdminUserPermissionsResponse) {
  vi.mocked(adminApi.getUserPermissions).mockResolvedValue({
    data: response,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(adminApi.getSectionPermissions).mockResolvedValue({
    data: permissionsSnapshot(),
  } as never);
  personIs(userPermissionsResponse());
});

describe("UserModal — exclusive personas", () => {
  it("offers Talent Community Manager as a provisionable role", () => {
    renderModal();

    expect(
      screen.getByRole("option", { name: "Talent Community Manager" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Talent Community Manager" }),
    ).toBeInTheDocument();
  });

  it("nie ma martwego pola „Rola rekrutacyjna (legacy)” (R9-N13-8)", () => {
    renderModal();
    expect(screen.queryByText(/Rola rekrutacyjna/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
  });

  it("clears operational roles when Finance becomes primary", () => {
    const { onSave } = renderModal({
      initial: { role: "delivery_lead", roles: ["delivery_lead", "tac"] },
    });

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "finance" },
    });

    expect(screen.getByRole("checkbox", { name: /Finanse/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "TAC" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "finance",
        roles: ["finance"],
      }),
    );
  });

  it("Praktykant (0374) jest rolą wyłączną — czyści pozostałe role", () => {
    const { onSave } = renderModal({
      initial: { role: "recruiter", roles: ["recruiter", "tac"] },
    });

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "trainee" },
    });

    expect(screen.getByRole("checkbox", { name: /Praktykant/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "TAC" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Rekruter" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ role: "trainee", roles: ["trainee"] }),
    );
  });

  it("praktykanta nie da się dołożyć jako roli dodatkowej", () => {
    renderModal({ initial: { role: "sourcer", roles: ["sourcer"] } });
    expect(screen.getByRole("checkbox", { name: "Praktykant" })).toBeDisabled();
  });

  it("removes Finance when switching back to an operational primary role", () => {
    const { onSave } = renderModal({
      initial: { role: "finance", roles: ["finance"] },
    });

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "recruiter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "recruiter",
        roles: ["recruiter"],
      }),
    );
  });

  it("never offers Viewer as a secondary role and removes stale Viewer hybrids", () => {
    const { onSave } = renderModal({
      initial: { role: "recruiter", roles: ["recruiter", "user"] },
    });

    expect(
      screen.queryByRole("checkbox", { name: /Viewer/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /Viewer/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "recruiter",
        roles: ["recruiter"],
      }),
    );
  });

  it("clears Viewer when switching to an operational primary role", () => {
    const { onSave } = renderModal({ initial: { role: "user", roles: ["user"] } });

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "delivery_lead" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "delivery_lead",
        roles: ["delivery_lead"],
      }),
    );
  });
});

describe("UserModal — imienne uprawnienie do usuwania klientów", () => {
  it("pozwala nadać uprawnienie przy edycji konta", () => {
    const { onSave } = renderModal({
      initial: { id: 5, role: "finance", roles: ["finance"], can_delete_clients: false },
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Może usuwać klientów" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ can_delete_clients: true }),
    );
  });

  it("nie pokazuje uprawnienia przy zakładaniu konta", () => {
    renderModal({ initial: null });

    expect(
      screen.queryByRole("checkbox", { name: "Może usuwać klientów" }),
    ).not.toBeInTheDocument();
  });

  it("pokazuje odmowę serwera zamiast milczeć (UAT M11-B10)", () => {
    renderModal({
      initial: null,
      error: "Adres e-mail musi być w domenie firmy (firma.example).",
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/domenie firmy/);
  });
});

describe("UserModal — odpięcie tożsamości Microsoft (audyt 24.09.2026)", () => {
  it("wysyła odpięcie tylko po zaznaczeniu", () => {
    const { onSave } = renderModal({
      initial: { id: 5, role: "recruiter", roles: ["recruiter"] },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ clear_microsoft_identity: false }),
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Odepnij tożsamość Microsoft" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ clear_microsoft_identity: true }),
    );
  });
});

describe("UserModal — dodatkowe uprawnienia osoby", () => {
  const tcm = {
    id: 90,
    name: "Celina Wzorcowa",
    role: "talent_community_manager",
    roles: ["talent_community_manager"],
  };

  /** Sekcja po wczytaniu — sama ramka pojawia się już w trakcie odczytu. */
  async function extraPermissions() {
    const group = await screen.findByRole("group", { name: "Dodatkowe uprawnienia" });
    await waitFor(() =>
      expect(within(group).queryByRole("status")).not.toBeInTheDocument(),
    );
    return group;
  }

  function labelsIn(group: HTMLElement) {
    return within(group)
      .getAllByRole("checkbox")
      .map((box) => box.closest("label")?.textContent);
  }

  it("nie pokazuje sekcji ani nie pyta o uprawnienia przy zakładaniu konta", () => {
    renderModal({ initial: null });

    expect(
      screen.queryByRole("group", { name: "Dodatkowe uprawnienia" }),
    ).not.toBeInTheDocument();
    expect(adminApi.getSectionPermissions).not.toHaveBeenCalled();
    expect(adminApi.getUserPermissions).not.toHaveBeenCalled();
  });

  it("pokazuje tylko to, czego rola nie daje, z nadaniami tej osoby", async () => {
    personIs(userPermissionsResponse({ grants: ["contracts_orders_edit"] }));
    const { onSave } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    expect(labelsIn(group)).toEqual([
      "Klienci: dodawanie i edycja",
      "Kontrakty i zamówienia: tworzenie i edycja",
      "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
      "Stawki i kwoty: podgląd",
      "Stawki i kwoty: zmiana",
      "Moduł Finanse",
    ]);
    expect(
      within(group).getByRole("checkbox", {
        name: "Kontrakty i zamówienia: tworzenie i edycja",
      }),
    ).toBeChecked();
    expect(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    ).not.toBeChecked();
    expect(group).toHaveTextContent(
      "Lista pokazuje tylko to, czego rola Talent Community Manager nie daje. Zaznaczone działa wyłącznie dla tej osoby.",
    );
    expect(adminApi.getUserPermissions).toHaveBeenCalledWith(90);

    // „Może usuwać klientów” zostaje osobnym polem pod listą.
    const deleteClients = screen.getByRole("checkbox", { name: "Może usuwać klientów" });
    expect(within(group).queryByRole("checkbox", { name: "Może usuwać klientów" })).toBeNull();
    expect(
      group.compareDocumentPosition(deleteClients) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Bez zmian nie ma drugiego żądania ani zapowiedzi wylogowania.
    expect(group).not.toHaveTextContent("Po zapisaniu ta osoba zostanie wylogowana.");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ permissions: null }));
  });

  it("zaznaczenie nadaje „manage”, odznaczenie wraca do „inherit”", async () => {
    personIs(userPermissionsResponse({ grants: ["contracts_orders_edit"] }, 31));
    const { onSave } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    fireEvent.click(
      within(group).getByRole("checkbox", { name: "Klienci: dodawanie i edycja" }),
    );
    fireEvent.click(
      within(group).getByRole("checkbox", {
        name: "Kontrakty i zamówienia: tworzenie i edycja",
      }),
    );

    expect(group).toHaveTextContent("Po zapisaniu ta osoba zostanie wylogowana.");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Celina Wzorcowa",
        permissions: {
          revision: 31,
          changes: [],
          actionChanges: [
            { action: "clients_edit", access: "manage" },
            { action: "contracts_orders_edit", access: "inherit" },
          ],
        },
      }),
    );
  });

  it("uprawnienie wymagane przez zaznaczone jest zaznaczone i zablokowane", async () => {
    const { onSave } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    const view = within(group).getByRole("checkbox", { name: "Stawki i kwoty: podgląd" });
    expect(view).not.toBeChecked();

    fireEvent.click(within(group).getByRole("checkbox", { name: "Moduł Finanse" }));

    expect(view).toBeChecked();
    expect(view).toBeDisabled();
    expect(view).toHaveAccessibleDescription("Wymagane przez: „Moduł Finanse”");
    expect(
      within(group).getByRole("checkbox", { name: "Stawki i kwoty: zmiana" }),
    ).not.toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        permissions: {
          revision: 12,
          changes: [],
          actionChanges: [{ action: "finance_module", access: "manage" }],
        },
      }),
    );
  });

  it("lista idzie za rolą wybraną w formularzu, a zbędne nadanie wraca do „inherit”", async () => {
    personIs(userPermissionsResponse({ grants: ["contracts_orders_edit"] }));
    const { onSave } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    expect(labelsIn(group)).toHaveLength(6);

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "delivery_lead" },
    });

    expect(labelsIn(group)).toEqual(["Stawki i kwoty: zmiana", "Moduł Finanse"]);
    expect(group).toHaveTextContent(
      "Lista pokazuje tylko to, czego role Delivery Lead, Talent Community Manager nie dają.",
    );
    // Delivery Lead daje już „Kontrakty i zamówienia” — nadanie jest zbędne.
    expect(group).toHaveTextContent("Po zapisaniu ta osoba zostanie wylogowana.");

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "delivery_lead",
        permissions: {
          revision: 12,
          changes: [],
          actionChanges: [{ action: "contracts_orders_edit", access: "inherit" }],
        },
      }),
    );
  });

  it("administrator, viewer i praktykant nie dostają dodatkowych uprawnień", async () => {
    personIs(
      userPermissionsResponse({ roles: ["admin"], locked: true, grantable: false }),
    );
    const { onSave } = renderModal({
      initial: { id: 1, role: "admin", roles: ["admin"] },
    });

    // Po wczytaniu zasad sekcja znika — administrator ma wszystko.
    await screen.findByRole("checkbox", { name: "Może usuwać klientów" });
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Dodatkowe uprawnienia" }),
      ).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("permissions");
  });

  it("zmiana roli na praktykanta chowa sekcję i nie wysyła uprawnień", async () => {
    personIs(userPermissionsResponse({ grants: ["contracts_orders_edit"] }));
    const { onSave } = renderModal({ initial: tcm });
    await extraPermissions();

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "trainee" },
    });

    expect(
      screen.queryByRole("group", { name: "Dodatkowe uprawnienia" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("permissions");
  });

  it("dla Finansów lista ma cztery pozycje, których ta rola nie daje", async () => {
    personIs(userPermissionsResponse({ roles: ["finance"] }));
    renderModal({ initial: { id: 7, role: "finance", roles: ["finance"] } });

    const group = await extraPermissions();
    expect(labelsIn(group)).toEqual([
      "Klienci: dodawanie i edycja",
      "Zakończenie współpracy, zmiana statusu kontraktu",
      "Umowy B2B: oznaczanie jako podpisane",
      "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
    ]);
  });

  it("stare ograniczenia: nazywa je i usuwa dopiero po kliknięciu", async () => {
    personIs(
      userPermissionsResponse({
        restrictions: ["contract_status"],
        legacy_section_caps: { delivery: "read" },
      }),
    );
    const { onSave } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    expect(group).toHaveTextContent(
      "Stare ograniczenia tej osoby: bez uprawnienia „Zakończenie współpracy, zmiana statusu kontraktu”; Delivery: tylko odczyt.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({ permissions: null }),
    );

    fireEvent.click(within(group).getByRole("button", { name: "Usuń ograniczenia" }));
    expect(group).toHaveTextContent(
      "Stare ograniczenia tej osoby zostaną usunięte po zapisaniu.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenLastCalledWith(
      expect.objectContaining({
        permissions: {
          revision: 12,
          changes: [{ section: "delivery", access: "inherit" }],
          actionChanges: [{ action: "contract_status", access: "inherit" }],
        },
      }),
    );
  });

  it("błąd odczytu to komunikat z „Ponów”, a zapis zmienia wtedy tylko dane konta", async () => {
    vi.mocked(adminApi.getUserPermissions).mockRejectedValueOnce(new Error("sieć"));
    const { onSave } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    expect(await within(group).findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać uprawnień tej osoby. Zapis zmieni tylko dane konta.",
    );
    expect(within(group).queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("permissions");

    fireEvent.click(within(group).getByRole("button", { name: "Ponów" }));

    expect(
      await within(group).findByRole("checkbox", { name: "Moduł Finanse" }),
    ).toBeInTheDocument();
    expect(within(group).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("nowa wersja zasad porzuca zaznaczenia zamiast przenosić je po cichu", async () => {
    const { onSave, queryClient } = renderModal({ initial: tcm });

    const group = await extraPermissions();
    fireEvent.click(within(group).getByRole("checkbox", { name: "Moduł Finanse" }));
    expect(within(group).getByRole("checkbox", { name: "Moduł Finanse" })).toBeChecked();

    act(() => {
      queryClient.setQueryData<AdminUserPermissionsResponse>(
        ["admin-user-permissions", 90],
        userPermissionsResponse({}, 13),
      );
    });

    expect(
      await within(group).findByText(/Zasady uprawnień zmieniły się w międzyczasie/),
    ).toBeInTheDocument();
    expect(within(group).getByRole("checkbox", { name: "Moduł Finanse" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ permissions: null }));
  });
});
