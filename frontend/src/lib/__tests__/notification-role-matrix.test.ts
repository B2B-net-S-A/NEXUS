import { describe, expect, it } from "vitest";

import { roleView } from "@/components/settings/__tests__/notification-role-fixtures";
import {
  EMPTY_ROLE_MATRIX_DRAFT,
  accountsLabel,
  categoryState,
  changeSummary,
  changedCells,
  formatCount,
  initiallyExpanded,
  isGroupMuted,
  perPersonAverage,
  toggleCategory,
  toggleGroup,
  viewIsUsable,
} from "@/lib/notification-role-matrix";

const view = roleView();
const [admin, recruiter] = view.roles;
const contracts = view.categories[2];

describe("notification-role-matrix — szkic", () => {
  it("przełączenie grupy trafia do szkicu, a powrót do stanu z serwera go czyści", () => {
    const muted = toggleGroup(view, EMPTY_ROLE_MATRIX_DRAFT, "recruiter", "pipeline");
    expect(changedCells(view, muted)).toEqual([
      { role: "recruiter", group: "pipeline", muted: true },
    ]);
    const back = toggleGroup(view, muted, "recruiter", "pipeline");
    expect(back).toEqual({});
    expect(changedCells(view, back)).toEqual([]);
  });

  it("włączenie grupy wyłączonej na serwerze wysyła `muted: false`", () => {
    const saved = roleView({}, { pipeline: ["admin"] });
    const draft = toggleGroup(saved, EMPTY_ROLE_MATRIX_DRAFT, "admin", "pipeline");
    expect(changedCells(saved, draft)).toEqual([
      { role: "admin", group: "pipeline", muted: false },
    ]);
  });

  it("kategoria obowiązkowa i nieznane klucze zostają nietknięte", () => {
    expect(toggleGroup(view, EMPTY_ROLE_MATRIX_DRAFT, "admin", "mentions")).toBe(
      EMPTY_ROLE_MATRIX_DRAFT,
    );
    expect(toggleCategory(view, EMPTY_ROLE_MATRIX_DRAFT, "admin", "mentions")).toBe(
      EMPTY_ROLE_MATRIX_DRAFT,
    );
    expect(toggleGroup(view, EMPTY_ROLE_MATRIX_DRAFT, "admin", "nie_ma")).toBe(
      EMPTY_ROLE_MATRIX_DRAFT,
    );
    // Nawet ręcznie wstawiony wpis szkicu nie trafia do zapisu.
    expect(changedCells(view, { "admin|mentions": true })).toEqual([]);
  });

  it("przełącznik kategorii wyłącza wszystkie grupy, a ze stanu mieszanego włącza wszystkie", () => {
    const allOff = toggleCategory(view, EMPTY_ROLE_MATRIX_DRAFT, "admin", "contracts");
    expect(categoryState(contracts, "admin", allOff)).toBe("off");
    expect(changedCells(view, allOff)).toEqual([
      { role: "admin", group: "order_ending", muted: true },
      { role: "admin", group: "contract_ending", muted: true },
    ]);
    // Inna rola nie jest ruszana.
    expect(categoryState(contracts, "recruiter", allOff)).toBe("on");

    const mixed = toggleGroup(view, allOff, "admin", "contract_ending");
    expect(categoryState(contracts, "admin", mixed)).toBe("mixed");
    expect(isGroupMuted(contracts.groups[0], "admin", mixed)).toBe(true);

    const allOn = toggleCategory(view, mixed, "admin", "contracts");
    expect(categoryState(contracts, "admin", allOn)).toBe("on");
    expect(allOn).toEqual({});
  });

  it("zmiany idą w kolejności tabeli, niezależnie od kolejności kliknięć", () => {
    let draft = toggleGroup(view, EMPTY_ROLE_MATRIX_DRAFT, "recruiter", "contract_ending");
    draft = toggleGroup(view, draft, "recruiter", "pipeline");
    draft = toggleGroup(view, draft, "admin", "pipeline");
    expect(changedCells(view, draft)).toEqual([
      { role: "admin", group: "pipeline", muted: true },
      { role: "recruiter", group: "pipeline", muted: true },
      { role: "recruiter", group: "contract_ending", muted: true },
    ]);
  });
});

describe("notification-role-matrix — liczby", () => {
  it("średnia na osobę liczy tylko włączone komórki", () => {
    expect(perPersonAverage(view, admin)).toBe(20);
    expect(perPersonAverage(view, recruiter)).toBe(12);
    const draft = toggleGroup(view, EMPTY_ROLE_MATRIX_DRAFT, "recruiter", "pipeline");
    // Zostają same wzmianki (obowiązkowe): 8 / 4 konta.
    expect(perPersonAverage(view, recruiter, draft)).toBe(2);
    expect(perPersonAverage(view, admin, draft)).toBe(20);
  });

  it("grupa wyłączona na serwerze nie wchodzi do średniej, dopóki szkic jej nie włączy", () => {
    const saved = roleView({}, { order_ending: ["admin"] });
    expect(perPersonAverage(saved, saved.roles[0])).toBe(10);
    const draft = toggleGroup(saved, EMPTY_ROLE_MATRIX_DRAFT, "admin", "order_ending");
    expect(perPersonAverage(saved, saved.roles[0], draft)).toBe(20);
  });

  it("rola bez kont nie ma średniej (to nie zero)", () => {
    expect(perPersonAverage(view, { key: "admin", label: "Admin", accounts: 0 })).toBeNull();
  });

  it("formatuje liczby i konta po polsku", () => {
    expect(formatCount(2779)).toBe("2 779");
    expect(formatCount(42)).toBe("42");
    expect(accountsLabel(1)).toBe("1 konto");
    expect(accountsLabel(3)).toBe("3 konta");
    expect(accountsLabel(7)).toBe("7 kont");
  });
});

describe("notification-role-matrix — podsumowanie i stan startowy", () => {
  it("podsumowanie grupuje zmiany po roli i nazywa grupę razem z kategorią", () => {
    const saved = roleView({}, { pipeline: ["recruiter"] });
    let draft = toggleGroup(saved, EMPTY_ROLE_MATRIX_DRAFT, "recruiter", "pipeline");
    draft = toggleGroup(saved, draft, "recruiter", "order_ending");
    draft = toggleCategory(saved, draft, "admin", "contracts");
    expect(
      changeSummary(saved, draft).map(({ role, off, on }) => ({ role: role.key, off, on })),
    ).toEqual([
      {
        role: "admin",
        off: ["Kontrakty i zamówienia: Koniec zamówienia", "Kontrakty i zamówienia: Koniec umowy"],
        on: [],
      },
      {
        role: "recruiter",
        off: ["Kontrakty i zamówienia: Koniec zamówienia"],
        on: ["Ruchy w rekrutacjach"],
      },
    ]);
    expect(changeSummary(saved, EMPTY_ROLE_MATRIX_DRAFT)).toEqual([]);
  });

  it("kategoria ze stanem mieszanym startuje rozwinięta", () => {
    expect(initiallyExpanded(view)).toEqual([]);
    expect(initiallyExpanded(roleView({}, { contract_ending: ["admin"] }))).toEqual(["contracts"]);
    // Całość wyłączona = zwinięty wiersz mówi prawdę, nie trzeba rozwijać.
    expect(
      initiallyExpanded(roleView({}, { order_ending: ["admin"], contract_ending: ["admin"] })),
    ).toEqual([]);
  });

  it("odpowiedź bez ról albo kategorii nie jest tabelą do pokazania", () => {
    expect(viewIsUsable(view)).toBe(true);
    expect(viewIsUsable(undefined)).toBe(false);
    expect(viewIsUsable(roleView({ roles: [] }))).toBe(false);
    expect(viewIsUsable(roleView({ categories: [] }))).toBe(false);
    expect(viewIsUsable({} as never)).toBe(false);
  });
});
