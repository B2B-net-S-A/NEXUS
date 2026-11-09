import { describe, expect, it } from "vitest";

import {
  permissionsSnapshot,
  roleEntry,
  userPermissionsResponse,
} from "@/components/settings/admin/__tests__/permission-fixtures";
import {
  changedRows,
  changesCountLabel,
  extraPermissionsLabel,
  extraPermissionsTitle,
  grantableRoles,
  grantedByRoles,
  grantedPermissions,
  legacyLimits,
  logoutSentence,
  peopleCountLabel,
  permissionsOfRoles,
  personPermissionRows,
  requiredByCaption,
  rolePermissionChanges,
  rolePermissionGroups,
  rolesAcceptGrants,
  setPersonPermission,
  snapshotIsUsable,
  storedPersonOverrides,
  togglePermission,
  userPermissionsSave,
  type AdminPermissionsSnapshot,
  type PersonOverride,
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
      "recruiter",
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
      "Sprzedaż",
      "Ludzie",
      "Pieniądze",
      "Rekrutacje",
      "Klienci i kontrakty",
    ]);
    expect(groups[2].rows.map((row) => row.label)).toEqual([
      "Stawki i kwoty: podgląd",
      "Stawki i kwoty: zmiana",
      "Moduł Finanse",
      "Wyniki firmy: podsumowania przychodu i marży",
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
    const role = roleEntry("recruiter", ["clients_edit"]);
    const local: AdminPermissionsSnapshot = { ...snapshot, roles: [role] };
    const draft = togglePermission(grantedPermissions(role), "clients_edit");

    expect(rolePermissionChanges(role, draft)).toEqual([
      { role: "recruiter", action: "clients_edit", access: "none" },
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
      "company_results",
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
    expect(logoutSentence(3, "Rekruter")).toBe(
      "Po zapisaniu 3 osoby z rolą Rekruter zostaną wylogowane i zalogują się ponownie.",
    );
    expect(logoutSentence(7, "Delivery Lead")).toBe(
      "Po zapisaniu 7 osób z rolą Delivery Lead zostanie wylogowanych i zaloguje się ponownie.",
    );
    expect(logoutSentence(0, "Praktykant")).toBe(
      "Nikt nie ma dziś roli Praktykant, więc nikt nie zostanie wylogowany.",
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

describe("uprawnienia jednej osoby", () => {
  const tcm = ["talent_community_manager"];

  it("nadanie przyjmują tylko konta, których każda rola jest do nadania", () => {
    expect(rolesAcceptGrants(snapshot, tcm)).toBe(true);
    expect(rolesAcceptGrants(snapshot, ["delivery_lead", "recruiter"])).toBe(true);
    expect(rolesAcceptGrants(snapshot, ["admin"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, ["admin", "recruiter"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, ["user"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, ["trainee"])).toBe(false);
    expect(rolesAcceptGrants(snapshot, [])).toBe(false);
  });

  it("role razem dają sumę uprawnień z zależnościami", () => {
    expect([...permissionsOfRoles(snapshot, tcm)].sort()).toEqual([
      "b2b_signature_confirmation",
      // „Ludzie w NEXUSIE”: TCM domyślnie obsługuje skrzynkę administracja@.
      "cases",
      "contract_status",
      "delivery_view",
    ]);
    expect(permissionsOfRoles(snapshot, ["recruiter", "finance"]).has("finance_module")).toBe(true);
    // 19.10.2026: rekruter ma z roli tylko podpis umowy (autor albo zespół).
    expect([...permissionsOfRoles(snapshot, ["recruiter"])]).toEqual([
      "b2b_signature_confirmation",
    ]);
  });

  const overrides = (entries: Partial<Record<Permission, PersonOverride>>) =>
    new Map(Object.entries(entries) as [Permission, PersonOverride][]);
  const rowOf = (rows: ReturnType<typeof personPermissionRows>, key: Permission) => {
    const row = rows.find((candidate) => candidate.key === key);
    if (!row) throw new Error(`brak wiersza ${key}`);
    return row;
  };

  it("lista to cały katalog w kolejności grup, z tym, co daje rola", () => {
    const rows = personPermissionRows(snapshot, grantedByRoles(snapshot, tcm), new Map());
    expect(rows.map((row) => row.key)).toEqual(
      snapshot.permission_groups.flatMap((group) => group.permissions),
    );
    expect(rows).toHaveLength(19);
    expect(rows.filter((row) => row.fromRole).map((row) => row.key)).toEqual([
      "delivery_view",
      "contract_status",
      "b2b_signature_confirmation",
      "cases",
    ]);
    expect(rows.every((row) => row.on === row.fromRole)).toBe(true);
    // Wyłączony program „Ludzie w NEXUSIE” (18.10.2026): bez grupy „people”.
    const hidden = personPermissionRows(
      snapshot,
      grantedByRoles(snapshot, tcm),
      new Map(),
      new Set(["people"]),
    );
    expect(hidden).toHaveLength(14);
    expect(hidden.map((row) => row.key)).not.toContain("cases");
  });

  it("nadanie włącza wiersz i blokuje to, czego wymaga", () => {
    const rows = personPermissionRows(
      snapshot,
      grantedByRoles(snapshot, tcm),
      overrides({ finance_module: "manage" }),
    );
    expect(rowOf(rows, "finance_module")).toMatchObject({ on: true, fromRole: false });
    expect(rowOf(rows, "amounts_view")).toMatchObject({
      on: true,
      fromRole: false,
      requiredBy: ["finance_module"],
    });
    expect(rowOf(rows, "amounts_edit")).toMatchObject({ on: false, requiredBy: [] });
  });

  it("odebranie wyłącza wiersz z roli, a wymagane zostaje zablokowane do końca", () => {
    const granted = grantedByRoles(snapshot, ["finance"]);
    const before = personPermissionRows(snapshot, granted, new Map());
    expect(rowOf(before, "amounts_view")).toMatchObject({
      on: true,
      fromRole: true,
      requiredBy: ["amounts_edit", "finance_module", "orders_work"],
    });

    const one = personPermissionRows(
      snapshot,
      granted,
      overrides({ finance_module: "none" }),
    );
    expect(rowOf(one, "finance_module")).toMatchObject({ on: false, fromRole: true });
    expect(rowOf(one, "amounts_view").requiredBy).toEqual([
      "amounts_edit",
      "orders_work",
    ]);

    const both = personPermissionRows(
      snapshot,
      granted,
      overrides({
        finance_module: "none",
        amounts_edit: "none",
        orders_work: "none",
      }),
    );
    expect(rowOf(both, "amounts_view")).toMatchObject({ on: true, requiredBy: [] });
  });

  it("uprawnienie tylko wynikające z roli znika razem z tym, co je wymuszało", () => {
    // Rola z samą „zmianą kwot”: podgląd ma tylko przez zależność — tak jak
    // liczy to resolver, odebranie zmiany zabiera też podgląd.
    const custom = permissionsSnapshot({
      roles: [roleEntry("recruiter", ["amounts_edit"])],
    });
    const granted = grantedByRoles(custom, ["recruiter"]);
    expect(rowOf(personPermissionRows(custom, granted, new Map()), "amounts_view")).toMatchObject({
      on: true,
      fromRole: true,
      requiredBy: ["amounts_edit"],
    });

    const revoked = overrides({ amounts_edit: "none" });
    expect(rowOf(personPermissionRows(custom, granted, revoked), "amounts_view")).toMatchObject({
      on: false,
      fromRole: true,
      requiredBy: [],
    });
    // Powrót na „Z roli” musi je nadać, bo rola nie ma tego wiersza.
    expect(setPersonPermission(revoked, granted, "amounts_view", true).get("amounts_view")).toBe(
      "manage",
    );
  });

  it("wyjątek powstaje tylko wtedy, gdy wybór różni się od wierszy ról", () => {
    const granted = grantedByRoles(snapshot, tcm);
    expect(setPersonPermission(new Map(), granted, "contract_status", false)).toEqual(
      overrides({ contract_status: "none" }),
    );
    expect(
      setPersonPermission(overrides({ contract_status: "none" }), granted, "contract_status", true),
    ).toEqual(new Map());
    expect(setPersonPermission(new Map(), granted, "clients_edit", true)).toEqual(
      overrides({ clients_edit: "manage" }),
    );
    expect(
      setPersonPermission(overrides({ clients_edit: "manage" }), granted, "clients_edit", false),
    ).toEqual(new Map());
  });

  it("zapisane nadania i odebrania czyta z odpowiedzi serwera", () => {
    expect(
      storedPersonOverrides(
        userPermissionsResponse({ grants: ["clients_edit"], restrictions: ["contract_status"] })
          .user,
      ),
    ).toEqual(overrides({ clients_edit: "manage", contract_status: "none" }));
  });

  const save = (
    response: ReturnType<typeof userPermissionsResponse>,
    draft: ReadonlyMap<Permission, PersonOverride>,
    {
      roles = tcm,
      rolesChanged = false,
      removeLegacy = false,
    }: { roles?: string[]; rolesChanged?: boolean; removeLegacy?: boolean } = {},
  ) =>
    userPermissionsSave({
      response,
      draft,
      roleGranted: grantedByRoles(snapshot, roles),
      rolesChanged,
      removeLegacy,
    });

  it("nic nie wysyła, gdy administrator niczego nie ruszył", () => {
    const response = userPermissionsResponse({
      grants: ["contracts_orders_edit"],
      restrictions: ["contract_status"],
    });
    expect(save(response, storedPersonOverrides(response.user))).toBeNull();
  });

  it("zbędne wyjątki nie wylogowują osoby przy zwykłej poprawce konta", () => {
    // Rola dostała to uprawnienie już po nadaniu; odebrane, którego rola nie
    // daje; odebrane, które i tak trzyma zależność. Porządki poczekają na zapis,
    // w którym administrator naprawdę coś zmienia.
    const response = userPermissionsResponse({
      grants: ["contract_status"],
      restrictions: ["clients_edit"],
    });
    expect(save(response, storedPersonOverrides(response.user))).toBeNull();
    const held = userPermissionsResponse({ roles: ["finance"], restrictions: ["amounts_view"] });
    expect(
      save(held, storedPersonOverrides(held.user), { roles: ["finance"] }),
    ).toBeNull();
    // Przełączenie tam i z powrotem to też brak zmiany.
    const granted = grantedByRoles(snapshot, tcm);
    const stale = userPermissionsResponse({ restrictions: ["clients_edit"] });
    const back = setPersonPermission(
      setPersonPermission(storedPersonOverrides(stale.user), granted, "clients_edit", true),
      granted,
      "clients_edit",
      false,
    );
    expect(save(stale, back)).toBeNull();
  });

  it("wysyła „manage”, „none” albo „inherit”, z rewizją odczytu", () => {
    const response = userPermissionsResponse(
      { grants: ["contracts_orders_edit"], restrictions: ["cases"] },
      31,
    );
    expect(
      save(response, overrides({ clients_edit: "manage", contract_status: "none" })),
    ).toEqual({
      revision: 31,
      changes: [],
      actionChanges: [
        { action: "clients_edit", access: "manage" },
        { action: "contracts_orders_edit", access: "inherit" },
        { action: "contract_status", access: "none" },
        { action: "cases", access: "inherit" },
      ],
    });
  });

  it("odebrane, którego wymaga zachowane z tego samego okna, nie idzie na serwer", () => {
    // Administrator odebrał zmianę i podgląd kwot, potem przywrócił zmianę:
    // podgląd jest znów włączony i zablokowany, a serwer odmówiłby zapisu.
    const response = userPermissionsResponse({ roles: ["finance"] });
    expect(
      save(response, overrides({ amounts_view: "none", finance_module: "none" }), {
        roles: ["finance"],
      }),
    ).toEqual({
      revision: 12,
      changes: [],
      actionChanges: [{ action: "finance_module", access: "none" }],
    });
  });

  it("wyjątek, który po zmianie ról niczego nie zmienia, wraca do „inherit”", () => {
    const response = userPermissionsResponse({
      grants: ["contracts_orders_edit", "finance_module"],
      restrictions: ["cases"],
    });
    // Delivery Lead daje kontrakty, a nie daje „Spraw”, więc odebrania nie ma czego trzymać.
    expect(
      save(response, storedPersonOverrides(response.user), {
        roles: ["delivery_lead"],
        rolesChanged: true,
      }),
    ).toEqual({
      revision: 12,
      changes: [],
      actionChanges: [
        { action: "contracts_orders_edit", access: "inherit" },
        { action: "cases", access: "inherit" },
      ],
    });
  });

  it("zmiana ról bez zbędnych wyjątków niczego nie wysyła", () => {
    const response = userPermissionsResponse({ grants: ["finance_module"] });
    expect(
      save(response, storedPersonOverrides(response.user), {
        roles: ["delivery_lead"],
        rolesChanged: true,
      }),
    ).toBeNull();
  });

  it("stare limity sekcji: nazywa je i usuwa przez „inherit”, odebrane zostają", () => {
    const response = userPermissionsResponse({
      restrictions: ["contract_status"],
      legacy_section_caps: { delivery: "read", finance: "none" },
    });
    expect(legacyLimits(response.user)).toEqual([
      "Delivery: tylko odczyt",
      "Finanse: brak dostępu",
    ]);
    expect(legacyLimits(userPermissionsResponse({ restrictions: ["cases"] }).user)).toEqual([]);

    expect(save(response, storedPersonOverrides(response.user), { removeLegacy: true })).toEqual({
      revision: 12,
      changes: [
        { section: "delivery", access: "inherit" },
        { section: "finance", access: "inherit" },
      ],
      actionChanges: [],
    });
  });

  it("zna wszystkie dziewiętnaście uprawnień (dwanaście + pięć „Ludzie” + dwa „Sprzedaż”)", () => {
    expect(PERMISSION_KEYS).toHaveLength(19);
  });
});
