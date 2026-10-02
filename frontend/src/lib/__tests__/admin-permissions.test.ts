import { describe, expect, it } from "vitest";

import {
  permissionsSnapshot,
  roleEntry,
  userPermissionsResponse,
} from "@/components/settings/admin/__tests__/permission-fixtures";
import {
  changedRows,
  changesCountLabel,
  extraPermissionRows,
  extraPermissionsLabel,
  extraPermissionsTitle,
  grantableRoles,
  grantedPermissions,
  legacyLimits,
  logoutSentence,
  peopleCountLabel,
  permissionsOfRoles,
  requiredByCaption,
  rolePermissionChanges,
  rolePermissionGroups,
  rolesAcceptGrants,
  snapshotIsUsable,
  togglePermission,
  userPermissionsSave,
  type AdminPermissionsSnapshot,
} from "@/lib/admin-permissions";
import { closePermissions, PERMISSION_KEYS, type Permission } from "@/lib/permissions";

const snapshot = permissionsSnapshot();

function roleOf(role: string) {
  const entry = snapshot.roles.find((candidate) => candidate.role === role);
  if (!entry) throw new Error(`brak roli ${role} w danych testu`);
  return entry;
}

function rowsOf(role: string, draft: ReadonlySet<Permission>) {
  return rolePermissionGroups(snapshot, roleOf(role), draft).flatMap(
    (group) => group.rows,
  );
}

describe("role do nadania", () => {
  it("pomija administratora, viewera i praktykanta, a resztę układa jak w zespole", () => {
    expect(grantableRoles(snapshot).map((entry) => entry.role)).toEqual([
      "finance",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
    ]);
  });

  it("odpowiedź sprzed wdrożenia uprawnień jest awarią, nie rolą bez uprawnień", () => {
    const legacy = {
      revision: 3,
      roles: [{ role: "recruiter", permissions: {} }],
    } as unknown as AdminPermissionsSnapshot;
    expect(snapshotIsUsable(legacy)).toBe(false);
    expect(snapshotIsUsable(undefined)).toBe(false);
    expect(snapshotIsUsable(snapshot)).toBe(true);
  });
});

describe("przełączniki roli", () => {
  it("pokazuje grupy i nazwy z API, w kolejności z API", () => {
    const groups = rolePermissionGroups(
      { ...snapshot, permission_groups: [...snapshot.permission_groups].reverse() },
      roleOf("recruiter"),
      new Set(),
    );
    expect(groups.map((group) => group.label)).toEqual([
      "Pieniądze",
      "Rekrutacje",
      "Klienci i kontrakty",
    ]);
    expect(groups[0].rows.map((row) => row.label)).toEqual([
      "Stawki i kwoty: podgląd",
      "Stawki i kwoty: zmiana",
      "Moduł Finanse",
    ]);
  });

  it("uprawnienie wymagane przez włączone jest włączone i zablokowane", () => {
    const rows = rowsOf("recruiter", new Set<Permission>(["amounts_edit"]));
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));

    expect(byKey.amounts_edit).toMatchObject({ on: true, requiredBy: [] });
    expect(byKey.amounts_view).toMatchObject({
      on: true,
      requiredBy: ["amounts_edit"],
    });
    expect(byKey.delivery_view).toMatchObject({
      on: true,
      requiredBy: ["amounts_edit"],
    });
    expect(byKey.clients_edit).toMatchObject({ on: false, requiredBy: [] });
    expect(requiredByCaption(byKey.amounts_view.requiredBy)).toBe(
      "Wymagane przez: „Stawki i kwoty: zmiana”",
    );
  });

  it("zmiana = przełącznik w innym stanie niż dziś, także ten wymuszony", () => {
    const draft = togglePermission(grantedPermissions(roleOf("recruiter")), "amounts_edit");
    const changed = changedRows(rolePermissionGroups(snapshot, roleOf("recruiter"), draft));

    expect(changed.map((row) => [row.key, row.onToday])).toEqual([
      ["delivery_view", false],
      ["amounts_view", false],
      ["amounts_edit", false],
    ]);
    // Wysyłamy tylko to, co administrator przełączył.
    expect(rolePermissionChanges(roleOf("recruiter"), draft)).toEqual([
      { role: "recruiter", action: "amounts_edit", access: "manage" },
    ]);
  });

  it("wyłączenie nadanego uprawnienia wysyła „none” i gasi to, co z niego wynikało", () => {
    const role = roleEntry("tac", ["clients_edit"]);
    const local: AdminPermissionsSnapshot = { ...snapshot, roles: [role] };
    const draft = togglePermission(grantedPermissions(role), "clients_edit");

    expect(rolePermissionChanges(role, draft)).toEqual([
      { role: "tac", action: "clients_edit", access: "none" },
    ]);
    expect(
      changedRows(rolePermissionGroups(local, role, draft)).map((row) => [
        row.key,
        row.on,
        row.onToday,
      ]),
    ).toEqual([
      ["delivery_view", false, true],
      ["clients_edit", false, true],
    ]);
  });

  it("zapisany wiersz zostaje włączony po wyłączeniu tego, co go wymuszało", () => {
    // Delivery Lead ma „podgląd” zapisany wprost, nie tylko jako wymagany.
    const role = roleOf("delivery_lead");
    let draft = grantedPermissions(role);
    for (const key of ["clients_edit", "contracts_orders_edit", "contract_status", "amounts_view"] as const) {
      draft = togglePermission(draft, key);
    }
    const view = rowsOf("delivery_lead", draft).find((row) => row.key === "delivery_view");
    expect(view).toMatchObject({ on: true, requiredBy: [], changed: false });
  });

  it("bez zmian nie ma czego wysyłać", () => {
    for (const role of grantableRoles(snapshot)) {
      expect(rolePermissionChanges(role, grantedPermissions(role))).toEqual([]);
    }
  });

  it("lista do wysłania jest pusta dokładnie wtedy, gdy ekran nie różni się od serwera — i daje to, co widać", () => {
    // Trzy „edycje” Delivery zachowują się identycznie, a podpis i rekrutacje
    // nie mają zależności, więc sześć kluczy pokrywa cały graf wymagań.
    const keys: Permission[] = [
      "delivery_view",
      "clients_edit",
      "contracts_orders_edit",
      "amounts_view",
      "amounts_edit",
      "finance_module",
    ];
    const subsets = Array.from({ length: 2 ** keys.length }, (_, mask) =>
      keys.filter((_key, index) => mask & (1 << index)),
    );
    const sameMembers = (a: Set<Permission>, b: Set<Permission>) =>
      a.size === b.size && [...a].every((key) => b.has(key));
    const failures: string[] = [];

    for (const stored of subsets) {
      const role = roleEntry("recruiter", stored);
      const today = closePermissions(stored);
      for (const drafted of subsets) {
        const draft = new Set(drafted);
        const changes = rolePermissionChanges(role, draft);
        const saved = new Set(stored);
        for (const change of changes) {
          if (change.access === "manage") saved.add(change.action as Permission);
          else saved.delete(change.action as Permission);
        }
        const shown = closePermissions(draft);
        if (!sameMembers(closePermissions(saved), shown)) {
          failures.push(`po zapisie inaczej niż na ekranie: ${stored} → ${drafted}`);
        }
        if ((changes.length > 0) !== !sameMembers(today, shown)) {
          failures.push(`zmiana bez widocznej różnicy albo odwrotnie: ${stored} → ${drafted}`);
        }
      }
    }
    expect(failures).toEqual([]);
  });
});

describe("zdania ekranu", () => {
  it("liczy osoby po polsku", () => {
    expect(peopleCountLabel(0)).toBe("0 osób");
    expect(peopleCountLabel(1)).toBe("1 osoba");
    expect(peopleCountLabel(3)).toBe("3 osoby");
    expect(peopleCountLabel(7)).toBe("7 osób");
    expect(peopleCountLabel(12)).toBe("12 osób");
    expect(peopleCountLabel(22)).toBe("22 osoby");
  });

  it("liczy zmiany po polsku", () => {
    expect(changesCountLabel(0)).toBe("Brak niezapisanych zmian");
    expect(changesCountLabel(1)).toBe("1 zmiana do zapisania");
    expect(changesCountLabel(3)).toBe("3 zmiany do zapisania");
    expect(changesCountLabel(5)).toBe("5 zmian do zapisania");
  });

  it("zdanie o wylogowaniu zgadza się z liczbą osób", () => {
    expect(logoutSentence(1, "Finanse")).toBe(
      "Po zapisaniu 1 osoba z rolą Finanse zostanie wylogowana i zaloguje się ponownie.",
    );
    expect(logoutSentence(3, "Sourcer")).toBe(
      "Po zapisaniu 3 osoby z rolą Sourcer zostaną wylogowane i zalogują się ponownie.",
    );
    expect(logoutSentence(7, "Delivery Lead")).toBe(
      "Po zapisaniu 7 osób z rolą Delivery Lead zostanie wylogowanych i zaloguje się ponownie.",
    );
    expect(logoutSentence(0, "TAC")).toBe(
      "Nikt nie ma dziś roli TAC, więc nikt nie zostanie wylogowany.",
    );
  });

  it("plakietka dodatkowych uprawnień ma trzy formy liczby", () => {
    expect(extraPermissionsLabel(1)).toBe("+1 uprawnienie");
    expect(extraPermissionsLabel(2)).toBe("+2 uprawnienia");
    expect(extraPermissionsLabel(4)).toBe("+4 uprawnienia");
    expect(extraPermissionsLabel(5)).toBe("+5 uprawnień");
    expect(extraPermissionsTitle(["contracts_orders_edit", "amounts_view", "przyszle"])).toBe(
      "Kontrakty i zamówienia: tworzenie i edycja, Stawki i kwoty: podgląd, przyszle",
    );
  });
});

describe("dodatkowe uprawnienia osoby", () => {
  const tcm = ["talent_community_manager"];

  it("nadanie przyjmują tylko konta, których każda rola jest do nadania", () => {
    expect(rolesAcceptGrants(snapshot, tcm)).toBe(true);
    expect(rolesAcceptGrants(snapshot, ["delivery_lead", "tac"])).toBe(true);
    expect(rolesAcceptGrants(snapshot, ["admin"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, ["admin", "recruiter"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, ["user"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, ["trainee"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, [])).toBe(false);
  });

  it("role razem dają sumę uprawnień z zależnościami", () => {
    expect([...permissionsOfRoles(snapshot, tcm)].sort()).toEqual([
      "b2b_signature_confirmation",
      "contract_status",
      "delivery_view",
    ]);
    expect(permissionsOfRoles(snapshot, ["tac", "finance"]).has("finance_module")).toBe(true);
    expect(permissionsOfRoles(snapshot, ["recruiter"]).size).toBe(0);
  });

  it("lista pokazuje wyłącznie to, czego role nie dają", () => {
    const rows = extraPermissionRows(snapshot, permissionsOfRoles(snapshot, tcm), new Set());
    expect(rows.map((row) => row.key)).toEqual([
      "clients_edit",
      "contracts_orders_edit",
      "recruitment_manage",
      "amounts_view",
      "amounts_edit",
      "finance_module",
    ]);
    expect(rows.every((row) => !row.checked)).toBe(true);
    // Delivery Lead dostaje z roli prawie wszystko — zostają dwie pozycje.
    expect(
      extraPermissionRows(
        snapshot,
        permissionsOfRoles(snapshot, ["delivery_lead"]),
        new Set(),
      ).map((row) => row.key),
    ).toEqual(["amounts_edit", "finance_module"]);
  });

  it("uprawnienie wymagane przez zaznaczone jest zaznaczone i zablokowane", () => {
    const rows = extraPermissionRows(
      snapshot,
      permissionsOfRoles(snapshot, tcm),
      new Set<Permission>(["finance_module"]),
    );
    expect(rows.find((row) => row.key === "amounts_view")).toMatchObject({
      checked: true,
      requiredBy: ["finance_module"],
    });
    expect(rows.find((row) => row.key === "amounts_edit")).toMatchObject({
      checked: false,
      requiredBy: [],
    });
  });

  it("nic nie wysyła, gdy administrator niczego nie ruszył", () => {
    const response = userPermissionsResponse({ grants: ["contracts_orders_edit"] });
    expect(
      userPermissionsSave({
        response,
        draft: new Set<Permission>(["contracts_orders_edit"]),
        roleGiven: permissionsOfRoles(snapshot, tcm),
        rolesChanged: false,
        removeLegacy: false,
      }),
    ).toBeNull();
  });

  it("zbędne nadanie nie wylogowuje osoby przy zwykłej poprawce konta", () => {
    // Rola dostała to uprawnienie już po nadaniu go osobie — porządki
    // poczekają na zapis, w którym administrator naprawdę coś zmienia.
    const response = userPermissionsResponse({ grants: ["contract_status"] });
    expect(
      userPermissionsSave({
        response,
        draft: new Set<Permission>(["contract_status"]),
        roleGiven: permissionsOfRoles(snapshot, tcm),
        rolesChanged: false,
        removeLegacy: false,
      }),
    ).toBeNull();
  });

  it("zaznaczenie wysyła „manage”, odznaczenie „inherit”, z rewizją odczytu", () => {
    const response = userPermissionsResponse({ grants: ["contracts_orders_edit"] }, 31);
    expect(
      userPermissionsSave({
        response,
        draft: new Set<Permission>(["clients_edit"]),
        roleGiven: permissionsOfRoles(snapshot, tcm),
        rolesChanged: false,
        removeLegacy: false,
      }),
    ).toEqual({
      revision: 31,
      changes: [],
      actionChanges: [
        { action: "clients_edit", access: "manage" },
        { action: "contracts_orders_edit", access: "inherit" },
      ],
    });
  });

  it("nadanie, które dają nowo wybrane role, wraca do „inherit”", () => {
    const response = userPermissionsResponse({
      grants: ["contracts_orders_edit", "finance_module"],
    });
    expect(
      userPermissionsSave({
        response,
        draft: new Set<Permission>(["contracts_orders_edit", "finance_module"]),
        roleGiven: permissionsOfRoles(snapshot, ["delivery_lead"]),
        rolesChanged: true,
        removeLegacy: false,
      }),
    ).toEqual({
      revision: 12,
      changes: [],
      actionChanges: [{ action: "contracts_orders_edit", access: "inherit" }],
    });
  });

  it("zmiana ról bez zbędnych nadań niczego nie wysyła", () => {
    const response = userPermissionsResponse({ grants: ["finance_module"] });
    expect(
      userPermissionsSave({
        response,
        draft: new Set<Permission>(["finance_module"]),
        roleGiven: permissionsOfRoles(snapshot, ["delivery_lead"]),
        rolesChanged: true,
        removeLegacy: false,
      }),
    ).toBeNull();
  });

  it("stare ograniczenia: nazywa je i usuwa przez „inherit”, bez dubli", () => {
    const response = userPermissionsResponse({
      restrictions: ["contract_status", "clients_edit"],
      legacy_section_caps: { delivery: "read", finance: "none" },
    });
    expect(legacyLimits(response.user)).toEqual([
      "bez uprawnienia „Zakończenie współpracy, zmiana statusu kontraktu”",
      "bez uprawnienia „Klienci: dodawanie i edycja”",
      "Delivery: tylko odczyt",
      "Finanse: brak dostępu",
    ]);
    expect(legacyLimits(userPermissionsResponse().user)).toEqual([]);

    expect(
      userPermissionsSave({
        response,
        // Administrator jednocześnie nadaje uprawnienie, które było odebrane.
        draft: new Set<Permission>(["clients_edit"]),
        roleGiven: permissionsOfRoles(snapshot, tcm),
        rolesChanged: false,
        removeLegacy: true,
      }),
    ).toEqual({
      revision: 12,
      changes: [
        { section: "delivery", access: "inherit" },
        { section: "finance", access: "inherit" },
      ],
      actionChanges: [
        { action: "clients_edit", access: "manage" },
        { action: "contract_status", access: "inherit" },
      ],
    });
  });

  it("zna wszystkie dziewięć uprawnień", () => {
    expect(PERMISSION_KEYS).toHaveLength(9);
  });
});
