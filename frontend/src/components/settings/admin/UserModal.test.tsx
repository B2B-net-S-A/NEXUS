import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminUserPermissionsResponse } from "@/lib/admin-permissions";
import { UserModal } from "./UserModal";
import {
  permissionsSnapshot,
  userPermissionsResponse,
} from "./__tests__/permission-fixtures";

// Program „Ludzie w NEXUSIE” (18.10.2026): domyślnie włączony w tych testach;
// przypadki wyłączonego programu przestawiają `hrProgram.on`.
const hrProgram = vi.hoisted(() => ({ on: true }));
vi.mock("@/lib/api/hr", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/hr")>()),
  useHrProgram: () => hrProgram.on,
}));

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
      initial: { role: "delivery_lead", roles: ["delivery_lead", "recruiter"] },
    });

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "finance" },
    });

    expect(screen.getByRole("checkbox", { name: /Finanse/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Rekruter" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "finance",
        roles: ["finance"],
      }),
    );
  });

  it("roli Praktykant nie da się nadać — moduł ukryty 17.10.2026", () => {
    renderModal({ initial: { role: "recruiter", roles: ["recruiter"] } });
    expect(screen.queryByRole("option", { name: "Praktykant" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Praktykant/ })).not.toBeInTheDocument();
  });

  it("konto, które już ma rolę Praktykant, dalej ją widzi i może ją zmienić", () => {
    const { onSave } = renderModal({
      initial: { id: 5, role: "trainee", roles: ["trainee"] },
    });

    expect(screen.getAllByRole("combobox")[0]).toHaveValue("trainee");
    expect(screen.getByRole("checkbox", { name: /Praktykant/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Rekruter" })).toBeDisabled();

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "recruiter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ role: "recruiter", roles: ["recruiter"] }),
    );
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

describe("UserModal — uprawnienia tej osoby", () => {
  const tcm = {
    id: 90,
    name: "Celina Wzorcowa",
    role: "talent_community_manager",
    roles: ["talent_community_manager"],
  };
  const finance = { id: 7, role: "finance", roles: ["finance"] };

  /** Sekcja po wczytaniu — sama ramka pojawia się już w trakcie odczytu. */
  async function personPermissions() {
    const group = await screen.findByRole("group", { name: "Uprawnienia tej osoby" });
    await waitFor(() =>
      expect(within(group).queryByRole("status")).not.toBeInTheDocument(),
    );
    return group;
  }

  function row(group: HTMLElement, permission: string) {
    return within(group).getByRole("radiogroup", { name: permission });
  }

  function option(group: HTMLElement, permission: string, name: string) {
    return within(row(group, permission)).getByRole("radio", { name });
  }

  function namesIn(group: HTMLElement) {
    return within(group)
      .getAllByRole("radiogroup")
      .map((item) => item.getAttribute("aria-labelledby"))
      .map((id) => document.getElementById(id as string)?.textContent);
  }

  it("nie pokazuje sekcji ani nie pyta o uprawnienia przy zakładaniu konta", () => {
    renderModal({ initial: null });

    expect(
      screen.queryByRole("group", { name: "Uprawnienia tej osoby" }),
    ).not.toBeInTheDocument();
    expect(adminApi.getSectionPermissions).not.toHaveBeenCalled();
    expect(adminApi.getUserPermissions).not.toHaveBeenCalled();
  });

  it("pokazuje cały katalog w kolejności grup i stan każdego wiersza", async () => {
    personIs(userPermissionsResponse({ grants: ["contracts_orders_edit"] }));
    const { onSave } = renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(namesIn(group)).toEqual([
      "Klienci, kontrakty i zamówienia: podgląd",
      "Klienci: dodawanie i edycja",
      "Kontrakty i zamówienia: tworzenie i edycja",
      "Zakończenie współpracy, zmiana statusu kontraktu",
      "Umowy B2B: oznaczanie jako podpisane",
      "Umowy klientów: lista i pliki (w plikach mogą być stawki)",
      "Zamówienia: zmiany, PDF-y, import MD",
      "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
      "Stawki i kwoty: podgląd",
      "Stawki i kwoty: zmiana",
      "Moduł Finanse",
      "Wyniki firmy: podsumowania przychodu i marży",
      "Administracja współpracy: kartoteka, urlopy za innych, wejście i odejście",
      "Rozliczenia: stawki osób, premie, rozliczenie miesiąca",
      "Sprzęt: ewidencja, wydania, zwroty i protokoły",
      "Sprawy: skrzynka administracja@",
      "Raporty godzin: akceptacja całej firmy",
      "Sprzedaż: podgląd firm, szans i kontaktów",
      "Sprzedaż: prowadzenie szans i kartoteki firm",
    ]);
    // Rola daje: „Z roli” / „Odebrane”. Nie daje: „Brak” / „Nadane”.
    expect(option(group, "Sprawy: skrzynka administracja@", "Z roli")).toBeChecked();
    expect(option(group, "Sprawy: skrzynka administracja@", "Odebrane")).not.toBeChecked();
    expect(option(group, "Klienci: dodawanie i edycja", "Brak")).toBeChecked();
    expect(
      option(group, "Kontrakty i zamówienia: tworzenie i edycja", "Nadane"),
    ).toBeChecked();
    expect(group).toHaveTextContent(
      "Rola daje punkt wyjścia. Tu możesz dla tej jednej osoby dodać uprawnienie albo je odebrać. Każda zmiana trafia do Historii zdarzeń i wylogowuje tę osobę.",
    );
    expect(adminApi.getUserPermissions).toHaveBeenCalledWith(90);

    // „Może usuwać klientów” zostaje osobnym polem pod listą.
    const deleteClients = screen.getByRole("checkbox", { name: "Może usuwać klientów" });
    expect(
      group.compareDocumentPosition(deleteClients) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Bez zmian nie ma drugiego żądania ani zapowiedzi wylogowania.
    expect(group).not.toHaveTextContent("Po zapisaniu ta osoba zostanie wylogowana.");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ permissions: null }));
  });

  it("przy wyłączonym programie nie pokazuje grupy „Ludzie”", async () => {
    hrProgram.on = false;
    try {
      renderModal({ initial: tcm });
      const group = await personPermissions();
      expect(namesIn(group)).toHaveLength(14);
      expect(namesIn(group)).not.toContain("Sprawy: skrzynka administracja@");
    } finally {
      hrProgram.on = true;
    }
  });

  it("wysyła „manage”, „none” i „inherit” według przełączników", async () => {
    personIs(
      userPermissionsResponse(
        { grants: ["contracts_orders_edit"], restrictions: ["cases"] },
        31,
      ),
    );
    const { onSave } = renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(option(group, "Sprawy: skrzynka administracja@", "Odebrane")).toBeChecked();

    fireEvent.click(option(group, "Klienci: dodawanie i edycja", "Nadane"));
    fireEvent.click(option(group, "Kontrakty i zamówienia: tworzenie i edycja", "Brak"));
    fireEvent.click(option(group, "Umowy B2B: oznaczanie jako podpisane", "Odebrane"));
    fireEvent.click(option(group, "Sprawy: skrzynka administracja@", "Z roli"));

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
            { action: "b2b_signature_confirmation", access: "none" },
            { action: "cases", access: "inherit" },
          ],
        },
      }),
    );
  });

  it("odebranie jest w kolorze ostrzegawczym, reszta aktywnych w głównym", async () => {
    renderModal({ initial: tcm });
    const group = await personPermissions();
    const fromRole = option(group, "Sprawy: skrzynka administracja@", "Z roli");
    const none = option(group, "Klienci: dodawanie i edycja", "Brak");
    expect(fromRole.className).toContain("bg-primary");
    expect(none.className).toContain("bg-primary");

    fireEvent.click(option(group, "Sprawy: skrzynka administracja@", "Odebrane"));
    const revoked = option(group, "Sprawy: skrzynka administracja@", "Odebrane");
    expect(revoked.className).toContain("bg-warning-muted");
    expect(revoked.className).toContain("text-warning-muted-foreground");
    expect(revoked.className).not.toContain("bg-primary");

    fireEvent.click(option(group, "Klienci: dodawanie i edycja", "Nadane"));
    expect(option(group, "Klienci: dodawanie i edycja", "Nadane").className).toContain(
      "bg-primary",
    );
  });

  it("strzałka przełącza wiersz z klawiatury", async () => {
    const user = userEvent.setup();
    const { onSave } = renderModal({ initial: tcm });
    const group = await personPermissions();

    option(group, "Sprawy: skrzynka administracja@", "Z roli").focus();
    await user.keyboard("{ArrowRight}");

    const revoked = option(group, "Sprawy: skrzynka administracja@", "Odebrane");
    expect(revoked).toHaveFocus();
    expect(revoked).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        permissions: expect.objectContaining({
          actionChanges: [{ action: "cases", access: "none" }],
        }),
      }),
    );
  });

  it("uprawnienie wymagane przez zachowane jest zablokowane z podpisem", async () => {
    personIs(userPermissionsResponse({ roles: ["finance"] }));
    renderModal({ initial: finance });

    const group = await personPermissions();
    const view = option(group, "Stawki i kwoty: podgląd", "Z roli");
    expect(view).toBeChecked();
    expect(view).toBeDisabled();
    expect(option(group, "Stawki i kwoty: podgląd", "Odebrane")).toBeDisabled();
    expect(view).toHaveAccessibleDescription(
      "Wymagane przez: „Stawki i kwoty: zmiana”, „Moduł Finanse”, „Zamówienia: zmiany, PDF-y, import MD”",
    );

    // Odebranie wszystkich, które go wymagają, zwalnia blokadę.
    fireEvent.click(option(group, "Stawki i kwoty: zmiana", "Odebrane"));
    expect(view).toBeDisabled();
    fireEvent.click(option(group, "Moduł Finanse", "Odebrane"));
    expect(view).toBeDisabled();
    fireEvent.click(
      option(group, "Zamówienia: zmiany, PDF-y, import MD", "Odebrane"),
    );
    expect(option(group, "Stawki i kwoty: podgląd", "Odebrane")).toBeEnabled();
  });

  it("nadanie blokuje to, czego wymaga, i nie wysyła go osobno", async () => {
    const { onSave } = renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(option(group, "Stawki i kwoty: podgląd", "Brak")).toBeChecked();

    fireEvent.click(option(group, "Moduł Finanse", "Nadane"));

    const view = option(group, "Stawki i kwoty: podgląd", "Nadane");
    expect(view).toBeChecked();
    expect(view).toBeDisabled();
    expect(view).toHaveAccessibleDescription("Wymagane przez: „Moduł Finanse”");
    expect(option(group, "Stawki i kwoty: zmiana", "Brak")).toBeChecked();

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

  it("zmiana roli przelicza listę, a zbędne nadanie wraca do „inherit”", async () => {
    personIs(userPermissionsResponse({ grants: ["contracts_orders_edit"] }));
    const { onSave } = renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(
      option(group, "Kontrakty i zamówienia: tworzenie i edycja", "Nadane"),
    ).toBeChecked();

    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "delivery_lead" },
    });

    // Delivery Lead daje już „Kontrakty i zamówienia”.
    expect(
      option(group, "Kontrakty i zamówienia: tworzenie i edycja", "Z roli"),
    ).toBeChecked();
    expect(option(group, "Moduł Finanse", "Brak")).toBeChecked();
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

  it("administrator nie ma sekcji uprawnień", async () => {
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
        screen.queryByRole("group", { name: "Uprawnienia tej osoby" }),
      ).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("permissions");
  });

  it("konto administratora nie pokazuje sekcji, gdy odczyt osoby jeszcze trwa", async () => {
    vi.mocked(adminApi.getUserPermissions).mockReturnValue(
      new Promise(() => undefined) as never,
    );
    renderModal({ initial: { id: 1, role: "admin", roles: ["admin"] } });

    // Zasady wystarczą, żeby wiedzieć, że administratorowi nic się nie nadaje —
    // nagłówek „Wczytywanie…” nie czeka na odczyt osoby, po którym by zniknął.
    await waitFor(() => expect(adminApi.getSectionPermissions).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Uprawnienia tej osoby" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("konto praktykanta nie ma sekcji i nie wysyła uprawnień", async () => {
    personIs(
      userPermissionsResponse({ roles: ["trainee"], locked: true, grantable: false }),
    );
    const { onSave } = renderModal({
      initial: { id: 5, role: "trainee", roles: ["trainee"] },
    });

    // Same zasady wystarczą, żeby schować sekcję — praktykantowi nic się nie nadaje.
    await waitFor(() => expect(adminApi.getSectionPermissions).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Uprawnienia tej osoby" }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("permissions");
  });

  it("stare limity sekcji: nazywa je i usuwa dopiero po kliknięciu; odebrane to zwykłe wiersze", async () => {
    personIs(
      userPermissionsResponse({
        restrictions: ["contract_status"],
        legacy_section_caps: { delivery: "read" },
      }),
    );
    const { onSave } = renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(
      option(group, "Zakończenie współpracy, zmiana statusu kontraktu", "Odebrane"),
    ).toBeChecked();
    expect(group).toHaveTextContent("Stare ograniczenia tej osoby: Delivery: tylko odczyt.");
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
          actionChanges: [],
        },
      }),
    );
  });

  it("bez starych limitów sekcji nie ma przycisku, nawet gdy coś jest odebrane", async () => {
    personIs(userPermissionsResponse({ restrictions: ["contract_status"] }));
    renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(within(group).queryByRole("button", { name: "Usuń ograniczenia" })).toBeNull();
    expect(group).not.toHaveTextContent("Stare ograniczenia");
  });

  it("błąd odczytu to komunikat z „Ponów”, a zapis zmienia wtedy tylko dane konta", async () => {
    vi.mocked(adminApi.getUserPermissions).mockRejectedValueOnce(new Error("sieć"));
    const { onSave } = renderModal({ initial: tcm });

    const group = await personPermissions();
    expect(await within(group).findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać uprawnień tej osoby. Zapis zmieni tylko dane konta.",
    );
    expect(within(group).queryByRole("radiogroup")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave.mock.calls[0][0]).not.toHaveProperty("permissions");

    fireEvent.click(within(group).getByRole("button", { name: "Ponów" }));

    expect(
      await within(group).findByRole("radiogroup", { name: "Moduł Finanse" }),
    ).toBeInTheDocument();
    expect(within(group).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("nowa wersja zasad porzuca wybory zamiast przenosić je po cichu", async () => {
    const { onSave, queryClient } = renderModal({ initial: tcm });

    const group = await personPermissions();
    fireEvent.click(option(group, "Moduł Finanse", "Nadane"));
    expect(option(group, "Moduł Finanse", "Nadane")).toBeChecked();

    act(() => {
      queryClient.setQueryData<AdminUserPermissionsResponse>(
        ["admin-user-permissions", 90],
        userPermissionsResponse({}, 13),
      );
    });

    expect(
      await within(group).findByText(/Zasady uprawnień zmieniły się w międzyczasie/),
    ).toBeInTheDocument();
    expect(option(group, "Moduł Finanse", "Brak")).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ permissions: null }));
  });
});
