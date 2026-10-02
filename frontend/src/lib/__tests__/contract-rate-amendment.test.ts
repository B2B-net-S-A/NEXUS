import { describe, expect, it } from "vitest";

import { canAmendContractRates } from "@/lib/contract-rate-amendment";
import type { User } from "@/store/auth";
import { permissionSnapshot } from "@/test/fixtures/permission-snapshot";

type TestUser = Parameters<typeof canAmendContractRates>[0];

const user = (overrides: Partial<User> & Pick<User, "role">): TestUser =>
  ({ roles: [overrides.role], ...overrides }) as TestUser;

const portfolio = (...clientIds: number[]): User["data_scope"] => ({
  kind: "delivery_clients",
  user_id: 5,
  allowed_client_ids: clientIds,
  allowed_tac_user_ids: [],
  allowed_operator_user_ids: [],
  finance_client_ids: clientIds,
});

describe("canAmendContractRates — „Zmień stawkę” na kontrakcie", () => {
  it("domyślnie zmieniają stawki admin i Finanse, u każdego klienta", () => {
    expect(canAmendContractRates(user({ role: "admin" }), 7)).toBe(true);
    expect(canAmendContractRates(user({ role: "finance" }), 7)).toBe(true);
  });

  it("Delivery Lead domyślnie nie ma zmiany kwot — także u swojego klienta", () => {
    expect(
      canAmendContractRates(
        user({ role: "delivery_lead", data_scope: portfolio(7) }),
        7,
      ),
    ).toBe(false);
  });

  it("rola spoza domyślnych z nadanym uprawnieniem zmienia stawki u każdego klienta", () => {
    const recruiter = user({
      role: "recruiter",
      effective_action_access: permissionSnapshot("amounts_edit"),
    });
    expect(canAmendContractRates(recruiter, 7)).toBe(true);
    expect(canAmendContractRates(recruiter, 99)).toBe(true);
  });

  it("Finanse z wyłączonym uprawnieniem nie zmieniają stawek", () => {
    expect(
      canAmendContractRates(
        user({
          role: "finance",
          effective_action_access: permissionSnapshot(
            "contracts_orders_edit",
            "finance_module",
          ),
        }),
        7,
      ),
    ).toBe(false);
  });

  it("konto z rolą Delivery Leada i nadanym uprawnieniem działa tylko u klientów z przypisania", () => {
    const lead = user({
      role: "delivery_lead",
      effective_action_access: permissionSnapshot(
        "contracts_orders_edit",
        "amounts_edit",
      ),
      data_scope: portfolio(7, 8),
    });
    expect(canAmendContractRates(lead, 7)).toBe(true);
    expect(canAmendContractRates(lead, 99)).toBe(false);
    // Kontrakt jeszcze się nie wczytał — bez klienta nie ma czego potwierdzić.
    expect(canAmendContractRates(lead, null)).toBe(false);
  });

  it("stary profil Delivery Leada bez listy klientów jest zamknięty", () => {
    expect(
      canAmendContractRates(
        user({
          role: "delivery_lead",
          effective_action_access: permissionSnapshot("amounts_edit"),
        }),
        7,
      ),
    ).toBe(false);
  });

  it("brak konta = brak przycisku", () => {
    expect(canAmendContractRates(null, 7)).toBe(false);
    expect(canAmendContractRates(undefined, 7)).toBe(false);
  });
});
