import { describe, expect, it } from "vitest";

import { contractAccess, type ContractAccess } from "@/lib/contract-access";
import type { User, UserRole } from "@/store/auth";

import {
  accessSnapshot,
  type AccessSnapshotOptions,
} from "./fixtures/access-snapshot";

const CLIENT_ID = 17;

function account(role: UserRole, options: AccessSnapshotOptions = {}): User {
  return {
    id: 1,
    email: `${role}@example.com`,
    name: role,
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    ...accessSnapshot(role, options),
  };
}

function access(
  role: UserRole,
  options: AccessSnapshotOptions = {},
  overrides: { impersonating?: boolean; clientId?: number | null } = {},
): ContractAccess {
  return contractAccess(account(role, options), {
    impersonating: overrides.impersonating ?? false,
    clientId: overrides.clientId === undefined ? CLIENT_ID : overrides.clientId,
  });
}

describe("contractAccess — domyślne uprawnienia ról", () => {
  it("admin: wszystko", () => {
    expect(access("admin")).toEqual({
      isAdmin: true,
      canManageFinance: true,
      canViewBenchmark: true,
      canViewInvoices: true,
      canManageInvoices: true,
      canEditContract: true,
      financeAmountsOnly: false,
      canEditContractStatus: true,
      canRecoverTermination: true,
      canViewFinance: true,
      canViewContractDocuments: true,
      canEditContractDocuments: true,
      canReassignClient: true,
    });
  });

  it("Delivery Lead u klienta z przypisania: edycja, status, kwoty do odczytu", () => {
    expect(access("delivery_lead", { assignedClientIds: [CLIENT_ID] })).toEqual({
      isAdmin: false,
      canManageFinance: false,
      canViewBenchmark: false,
      canViewInvoices: false,
      canManageInvoices: false,
      canEditContract: true,
      financeAmountsOnly: false,
      canEditContractStatus: true,
      canRecoverTermination: false,
      canViewFinance: true,
      canViewContractDocuments: true,
      canEditContractDocuments: true,
      canReassignClient: false,
    });
  });

  it("Delivery Lead poza portfelem: edytuje kontrakt, ale bez kwot i dokumentów", () => {
    const outside = access("delivery_lead", { assignedClientIds: [99] });
    expect(outside.canEditContract).toBe(true);
    expect(outside.canViewFinance).toBe(false);
    expect(outside.canViewContractDocuments).toBe(false);
    expect(outside.canEditContractDocuments).toBe(false);
  });

  it("Finanse od 0409: pełna edycja kontraktu i kwot, bez zmiany statusu", () => {
    expect(access("finance")).toEqual({
      isAdmin: false,
      canManageFinance: true,
      canViewBenchmark: true,
      canViewInvoices: true,
      canManageInvoices: true,
      canEditContract: true,
      // Finanse edytują cały kontrakt, więc formularz nie jest zawężany do kwot.
      financeAmountsOnly: false,
      canEditContractStatus: false,
      canRecoverTermination: true,
      canViewFinance: true,
      canViewContractDocuments: true,
      canEditContractDocuments: true,
      canReassignClient: false,
    });
  });

  it("TCM: status i cofnięcie zakończenia, nic poza tym", () => {
    expect(access("talent_community_manager")).toEqual({
      isAdmin: false,
      canManageFinance: false,
      canViewBenchmark: false,
      canViewInvoices: false,
      canManageInvoices: false,
      canEditContract: false,
      financeAmountsOnly: false,
      canEditContractStatus: true,
      canRecoverTermination: true,
      canViewFinance: false,
      canViewContractDocuments: false,
      canEditContractDocuments: false,
      canReassignClient: false,
    });
  });

  it.each(["head_of_recruitment", "tac", "recruiter", "sourcer", "user"] as UserRole[])(
    "%s: żadnej akcji na kontrakcie",
    (role) => {
      const result = access(role);
      expect(Object.values(result).every((value) => value === false)).toBe(true);
    },
  );
});

describe("contractAccess — to, co przełączył administrator", () => {
  it("rekruter z „Kontrakty i zamówienia”: edytuje kontrakt, kwot i dokumentów nie widzi", () => {
    const result = access("recruiter", { grant: ["contracts_orders_edit"] });
    expect(result.canEditContract).toBe(true);
    expect(result.canViewFinance).toBe(false);
    expect(result.canViewContractDocuments).toBe(false);
    // Dokumenty mogą nieść stawki — zapis wymaga też podglądu kwot.
    expect(result.canEditContractDocuments).toBe(false);
    expect(result.canEditContractStatus).toBe(false);
    expect(result.canManageFinance).toBe(false);
  });

  it("…a z dodanym „Stawki i kwoty: podgląd” — także dokumenty, u każdego klienta", () => {
    const result = access(
      "recruiter",
      { grant: ["contracts_orders_edit", "amounts_view"] },
      { clientId: 999 },
    );
    expect(result.canViewFinance).toBe(true);
    expect(result.canEditContractDocuments).toBe(true);
  });

  it("Delivery Lead z wyłączonym „Kontrakty i zamówienia” traci edycję, status zostaje", () => {
    const result = access("delivery_lead", {
      revoke: ["contracts_orders_edit"],
      assignedClientIds: [CLIENT_ID],
    });
    expect(result.canEditContract).toBe(false);
    expect(result.canEditContractDocuments).toBe(false);
    expect(result.canEditContractStatus).toBe(true);
    expect(result.canViewFinance).toBe(true);
  });

  it("sama zmiana kwot (bez edycji kontraktu) zawęża formularz do kwot", () => {
    const amountsOnly = access("finance", { revoke: ["contracts_orders_edit"] });
    expect(amountsOnly.canEditContract).toBe(false);
    expect(amountsOnly.canManageFinance).toBe(true);
    expect(amountsOnly.financeAmountsOnly).toBe(true);

    const recruiter = access("recruiter", { grant: ["amounts_edit"] });
    expect(recruiter.financeAmountsOnly).toBe(true);
    expect(recruiter.canViewFinance).toBe(true);
  });

  it("status kontraktu idzie za swoim uprawnieniem", () => {
    expect(
      access("recruiter", { grant: ["contract_status"] }).canEditContractStatus,
    ).toBe(true);
    expect(
      access("talent_community_manager", { revoke: ["contract_status"] })
        .canEditContractStatus,
    ).toBe(false);
  });

  it("Delivery Lead z nadaną zmianą kwot: tylko u klienta z przypisania", () => {
    const options: AccessSnapshotOptions = {
      grant: ["amounts_edit"],
      assignedClientIds: [CLIENT_ID],
    };
    expect(access("delivery_lead", options).canManageFinance).toBe(true);
    expect(access("delivery_lead", options, { clientId: 99 }).canManageFinance).toBe(false);
  });

  it("faktury i benchmark zostają przy „Moduł Finanse”", () => {
    const withoutModule = access("finance", { revoke: ["finance_module"] });
    expect(withoutModule.canViewBenchmark).toBe(false);
    expect(withoutModule.canViewInvoices).toBe(false);
    expect(withoutModule.canManageInvoices).toBe(false);
    // Kwoty kontraktu to osobne uprawnienia — zostają.
    expect(withoutModule.canViewFinance).toBe(true);
    expect(withoutModule.canManageFinance).toBe(true);

    const granted = access("head_of_recruitment", { grant: ["finance_module"] });
    expect(granted.canViewInvoices).toBe(true);
    expect(granted.canManageInvoices).toBe(true);
  });

  it("„Cofnij zakończenie” i „Przepnij na innego klienta” zostają przy roli", () => {
    const everything = access("recruiter", {
      grant: [
        "contracts_orders_edit",
        "contract_status",
        "amounts_edit",
        "finance_module",
      ],
    });
    expect(everything.canRecoverTermination).toBe(false);
    expect(everything.canReassignClient).toBe(false);
    expect(access("delivery_lead", { assignedClientIds: [CLIENT_ID] }).canRecoverTermination).toBe(
      false,
    );
  });
});

describe("contractAccess — podgląd jako i brak klienta", () => {
  it("„podgląd jako” chowa każdą akcję zapisu, odczyt zostaje", () => {
    const result = access("admin", {}, { impersonating: true });
    expect(result.canEditContract).toBe(false);
    expect(result.canEditContractStatus).toBe(false);
    expect(result.canRecoverTermination).toBe(false);
    expect(result.canEditContractDocuments).toBe(false);
    expect(result.financeAmountsOnly).toBe(false);
    expect(result.canReassignClient).toBe(false);
    expect(result.canViewFinance).toBe(true);
    expect(result.canViewContractDocuments).toBe(true);
  });

  it("kontrakt bez klienta: kwot i dokumentów nie da się przypisać do zakresu", () => {
    const result = access("admin", {}, { clientId: null });
    expect(result.canViewFinance).toBe(false);
    expect(result.canViewContractDocuments).toBe(false);
    expect(result.canEditContract).toBe(true);
  });

  it("brak użytkownika = nic", () => {
    const result = contractAccess(null, { impersonating: false, clientId: CLIENT_ID });
    expect(Object.values(result).every((value) => value === false)).toBe(true);
  });
});
