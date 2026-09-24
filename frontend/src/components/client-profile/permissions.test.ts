import { describe, expect, it } from "vitest";

import { canExtendContract } from "@/components/client-profile/actions/ExtendContractMenu";
import {
  canManageAssignedClient,
  canManageClientDelivery,
} from "@/components/client-profile/permissions";
import type { User } from "@/store/auth";

function user(role: User["role"], financeClientIds: number[] = []): User {
  return {
    id: 1,
    email: "u@example.com",
    name: "U",
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    data_scope:
      role === "delivery_lead"
        ? {
            kind: "delivery_clients",
            user_id: 1,
            allowed_client_ids: financeClientIds,
            finance_client_ids: financeClientIds,
            allowed_tac_user_ids: [],
            allowed_operator_user_ids: [],
            allowed_client_tac_pairs: [],
          }
        : undefined,
  } as User;
}

describe("Przedłuż na profilu klienta (audyt W2)", () => {
  it("tylko admin i Delivery Lead, tylko kontrakt „Kończący się”", () => {
    expect(canExtendContract(user("admin"), "ending")).toBe(true);
    expect(canExtendContract(user("delivery_lead"), "ending")).toBe(true);
    // Backend (`DeliveryLeadPlus`) odmawia Finansom i TCM — przycisku nie ma.
    expect(canExtendContract(user("finance"), "ending")).toBe(false);
    expect(canExtendContract(user("talent_community_manager"), "ending")).toBe(false);
    // Aktywny bez daty końca nie ma czego przedłużać.
    expect(canExtendContract(user("admin"), "active")).toBe(false);
    expect(canExtendContract(user("admin"), null)).toBe(false);
  });
});

describe("Zapisy wymagające przypisania DL (audyt S11)", () => {
  it("DL tylko u klienta z własnego portfela, admin wszędzie", () => {
    expect(canManageAssignedClient(user("admin"), 5)).toBe(true);
    expect(canManageAssignedClient(user("delivery_lead", [5]), 5)).toBe(true);
    expect(canManageAssignedClient(user("delivery_lead", [6]), 5)).toBe(false);
    expect(canManageAssignedClient(user("recruiter"), 5)).toBe(false);
  });

  it("zapis Delivery: admin i DL, nie rekruter ani Finanse", () => {
    expect(canManageClientDelivery(user("admin"))).toBe(true);
    expect(canManageClientDelivery(user("delivery_lead"))).toBe(true);
    expect(canManageClientDelivery(user("recruiter"))).toBe(false);
    expect(canManageClientDelivery(user("finance"))).toBe(false);
  });
});
