import { describe, expect, it } from "vitest";

import { currentFrameworkContract, frameworkSectionMeta } from "@/components/client-profile/ClientHeaderFacts";
import type { FrameworkContractRead } from "@/lib/api/dlPortal";

function contract(overrides: Partial<FrameworkContractRead>): FrameworkContractRead {
  return {
    id: 1,
    client_id: 7,
    name: "Umowa ramowa — usługi IT",
    status: "active",
    effective_date: "2024-03-01",
    expiry_date: null,
    signed_via: "upload",
    currency: null,
    parent_contract_id: null,
    contract_terms_id: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    uploaded_by: null,
    uploaded_at: null,
    notes: null,
    created_at: "2024-03-01T00:00:00Z",
    updated_at: "2024-03-01T00:00:00Z",
    amendments_count: 0,
    days_to_expiry: null,
    ...overrides,
  };
}

describe("umowa ramowa przy sekcji „Umowa i pieniądze”", () => {
  it("bezterminowa wygrywa z terminową; rozwiązane i zastąpione się nie liczą", () => {
    const items = [
      contract({ id: 1, expiry_date: "2026-12-31", days_to_expiry: 42 }),
      contract({ id: 2, expiry_date: null }),
      contract({ id: 3, status: "terminated" }),
    ];
    expect(currentFrameworkContract(items)?.id).toBe(2);
    expect(currentFrameworkContract([contract({ status: "superseded" }), contract({ status: "draft" })])).toBeNull();
  });

  it("z kilku terminowych liczy się ta z najpóźniejszym końcem, także czekająca na podpis", () => {
    const items = [
      contract({ id: 1, expiry_date: "2026-12-13", days_to_expiry: 24 }),
      contract({ id: 2, status: "pending_signature", expiry_date: "2027-12-31", days_to_expiry: 407 }),
    ];
    expect(currentFrameworkContract(items)?.id).toBe(2);
  });

  it("dopisek mówi „bezterminowa”, „do …” albo „wygasła …”, a dymek nazywa umowę", () => {
    expect(frameworkSectionMeta(contract({}))).toEqual({
      text: "bezterminowa",
      title: "Umowa ramowa: Umowa ramowa — usługi IT",
    });
    expect(frameworkSectionMeta(contract({ expiry_date: "2026-12-31", days_to_expiry: 42 })).text).toBe(
      "do 31.12.2026",
    );
    expect(frameworkSectionMeta(contract({ expiry_date: "2026-01-03", days_to_expiry: -320 })).text).toBe(
      "wygasła 03.01.2026",
    );
  });
});
