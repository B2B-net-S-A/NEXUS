import { describe, expect, it } from "vitest";

import type { B2BGeneratedContractRow } from "@/lib/api";
import {
  canCorrectInForm,
  contractStatusOptions,
  existingContractFor,
  generatedIdFromHeaders,
  generatorEditHref,
  generatorPrefillHref,
  generatorTabFromParam,
  mergeRegisterPages,
  nextRegisterOffset,
  registerRowWarnings,
  registerSearchHref,
} from "@/lib/b2b-generator-register";

function row(
  overrides: Partial<B2BGeneratedContractRow> = {},
): B2BGeneratedContractRow {
  return {
    id: 1,
    contract_number: "1471/2026",
    partner_name: null,
    partner_display_name: null,
    partner_secondary_line: null,
    partner_nip: null,
    start_date: null,
    client_name: null,
    language: "pl",
    signing_date: null,
    created_at: null,
    created_by_name: null,
    signature_status: "unsigned",
    signature_source: null,
    contract_status: "in_progress",
    closure_reason: null,
    closure_reason_other: null,
    closure_date: null,
    can_change_status: true,
    candidate_id: null,
    job_id: null,
    client_id: null,
    contract_id: null,
    candidate_name: null,
    job_title: null,
    canonical_client_name: null,
    signed_at: null,
    signed_by_name: null,
    can_confirm_signed: false,
    blocked_reason: null,
    can_delete: false,
    can_edit: false,
    can_download: false,
    ...overrides,
  };
}

const values = (r: Parameters<typeof contractStatusOptions>[0]) =>
  contractStatusOptions(r).map((o) => `${o.value}${o.disabled ? "(off)" : ""}`);

describe("contractStatusOptions — lustro reguł PATCH-a", () => {
  it("niepodpisana „W trakcie”: bez „Aktywnej”, „W trakcie” wyszarzone", () => {
    expect(
      values({ contract_status: "in_progress", signature_status: "unsigned" }),
    ).toEqual(["in_progress(off)", "cancelled", "closed"]);
  });

  it("podpisana aktywna: „Aktywna” i zawieszenie, bez anulowania", () => {
    expect(
      values({ contract_status: "active", signature_status: "signed_both" }),
    ).toEqual(["active", "in_progress(off)", "suspended", "closed"]);
  });

  it("zakończona NIEPODPISANA wraca na „W trakcie”, nigdy na „Aktywna”", () => {
    expect(
      values({ contract_status: "closed", signature_status: "unsigned" }),
    ).toEqual(["in_progress", "closed"]);
  });

  it("zakończona PODPISANA wraca na „Aktywna”, a „W trakcie” zostaje wyszarzone", () => {
    expect(
      values({ contract_status: "closed", signature_status: "signed_both" }),
    ).toEqual(["active", "in_progress(off)", "closed"]);
  });

  it("zawieszona: „Aktywna” tylko przez „Przywróć” (wymaga projektu)", () => {
    expect(
      values({ contract_status: "suspended", signature_status: "signed_both" }),
    ).toEqual(["in_progress(off)", "suspended", "closed"]);
  });

  it("anulowana wraca na „W trakcie”", () => {
    expect(
      values({ contract_status: "cancelled", signature_status: "unsigned" }),
    ).toEqual(["in_progress", "cancelled", "closed"]);
  });

  it("wiersz „Aktywny” sprzed audytu (niepodpisany) nie traci pozycji w triggerze", () => {
    expect(
      values({ contract_status: "active", signature_status: "unsigned" }),
    ).toContain("active");
  });
});

describe("mergeRegisterPages", () => {
  it("sortuje całość malejąco po roku i numerze, nie po stringu", () => {
    const merged = mergeRegisterPages([
      [row({ id: 1, contract_number: "999/2026" })],
      [
        row({ id: 2, contract_number: "1000/2026" }),
        row({ id: 3, contract_number: "1500/2025" }),
      ],
    ]);
    expect(merged.map((r) => r.contract_number)).toEqual([
      "1000/2026",
      "999/2026",
      "1500/2025",
    ]);
  });

  it("nie dubluje wiersza, który przesunął się między stronami", () => {
    const merged = mergeRegisterPages([
      [row({ id: 7, contract_number: "10/2026" })],
      [row({ id: 7, contract_number: "10/2026" })],
    ]);
    expect(merged).toHaveLength(1);
  });

  it("numer spoza formatu nie znika — trafia na koniec", () => {
    const merged = mergeRegisterPages([
      [row({ id: 1, contract_number: "stary-12" }), row({ id: 2, contract_number: "1/2020" })],
    ]);
    expect(merged.map((r) => r.id)).toEqual([2, 1]);
  });
});

describe("nextRegisterOffset", () => {
  it("pełna strona → kolejny offset, niepełna → koniec", () => {
    expect(nextRegisterOffset(new Array(100), 1)).toBe(100);
    expect(nextRegisterOffset(new Array(100), 2)).toBe(200);
    expect(nextRegisterOffset(new Array(37), 1)).toBeUndefined();
  });
});

describe("registerRowWarnings", () => {
  it("aktywna umowa przy zakończonym kontrakcie — ostrzeżenie z datą", () => {
    expect(
      registerRowWarnings({
        contract_status: "active",
        signature_status: "signed_both",
        contract_id: 9,
        linked_contract_status: "ended",
        linked_contract_end_date: "2026-08-31",
      }),
    ).toEqual([
      { tone: "danger", text: "Kontrakt zakończony 31.08.2026 — zmień status umowy" },
    ]);
  });

  it("zawieszona przy unieważnionym kontrakcie też ostrzega", () => {
    expect(
      registerRowWarnings({
        contract_status: "suspended",
        signature_status: "signed_both",
        contract_id: 9,
        linked_contract_status: "void",
        linked_contract_end_date: null,
      })[0]?.text,
    ).toBe("Kontrakt zakończony — zmień status umowy");
  });

  it("zakończona umowa przy zakończonym kontrakcie — zgodne, bez ostrzeżenia", () => {
    expect(
      registerRowWarnings({
        contract_status: "closed",
        signature_status: "signed_both",
        contract_id: 9,
        linked_contract_status: "ended",
        linked_contract_end_date: "2026-08-31",
      }),
    ).toEqual([]);
  });

  it("kończący się kontrakt", () => {
    expect(
      registerRowWarnings({
        contract_status: "active",
        signature_status: "signed_both",
        contract_id: 9,
        linked_contract_status: "ending",
        linked_contract_end_date: "2026-10-15",
      }),
    ).toEqual([{ tone: "warning", text: "Kontrakt kończy się 15.10.2026" }]);
  });

  it("podpisana bez kontraktu — kontrakt usunięty", () => {
    expect(
      registerRowWarnings({
        contract_status: "active",
        signature_status: "signed_both",
        contract_id: null,
        linked_contract_status: null,
        linked_contract_end_date: null,
      }),
    ).toEqual([{ tone: "danger", text: "Kontrakt usunięty — brak kontraktora" }]);
  });

  it("niepodpisana bez kontraktu to stan normalny, bez ostrzeżeń", () => {
    expect(
      registerRowWarnings({
        contract_status: "in_progress",
        signature_status: "unsigned",
        contract_id: null,
      }),
    ).toEqual([]);
  });
});

describe("existingContractFor", () => {
  const rows = [
    row({ id: 1, candidate_id: 5, contract_status: "cancelled" }),
    row({ id: 2, candidate_id: 5, contract_status: "in_progress" }),
    row({ id: 3, candidate_id: 6, contract_status: "active" }),
  ];

  it("znajduje żywą umowę tej osoby, pomija anulowane i cudze", () => {
    expect(existingContractFor(rows, 5)?.id).toBe(2);
    expect(existingContractFor(rows, 7)).toBeNull();
    expect(existingContractFor(rows, null)).toBeNull();
  });

  it("nie ostrzega przed umową, którą formularz właśnie zapisał", () => {
    expect(existingContractFor(rows, 5, 2)).toBeNull();
  });

  it("zakończona i zawieszona — zawieszona to wciąż żywa umowa", () => {
    expect(
      existingContractFor(
        [
          row({ id: 8, candidate_id: 5, contract_status: "closed" }),
          row({ id: 9, candidate_id: 5, contract_status: "suspended" }),
        ],
        5,
      )?.id,
    ).toBe(9);
  });
});

describe("adres zakładek i linki", () => {
  it("przyjmuje identyfikatory zakładek i czytelne aliasy", () => {
    expect(generatorTabFromParam("closed")).toBe("closed");
    expect(generatorTabFromParam("ended")).toBe("closed");
    expect(generatorTabFromParam("current")).toBe("generated");
    expect(generatorTabFromParam("without-project")).toBe("no-project");
    expect(generatorTabFromParam("xyz")).toBeNull();
    expect(generatorTabFromParam(null)).toBeNull();
  });

  it("link do rejestru trafia w zakładkę statusu i koduje numer", () => {
    expect(registerSearchHref("1500/2026", "suspended")).toBe(
      "/contracts/b2b-generator?tab=no-project&q=1500%2F2026",
    );
    expect(registerSearchHref("1500/2026", "in_progress")).toBe(
      "/contracts/b2b-generator?tab=generated&q=1500%2F2026",
    );
  });

  it("link do formularza niesie parę albo prowadzi na pusty generator", () => {
    expect(generatorPrefillHref(42, 10)).toBe(
      "/contracts/b2b-generator?tab=generator&candidate=42&job=10",
    );
    expect(generatorPrefillHref(null, 10)).toBe("/contracts/b2b-generator");
  });
});

describe("generatedIdFromHeaders", () => {
  it("czyta id wiersza z nagłówka (axios: małe litery)", () => {
    expect(generatedIdFromHeaders({ "x-generated-contract-id": "123" })).toBe(123);
  });

  it("brak albo śmieci → null (starszy backend)", () => {
    expect(generatedIdFromHeaders({})).toBeNull();
    expect(generatedIdFromHeaders({ "x-generated-contract-id": "abc" })).toBeNull();
    expect(generatedIdFromHeaders(undefined)).toBeNull();
  });
});

describe("canCorrectInForm — lustro bramki /form i /rerender", () => {
  const base = {
    can_edit: true,
    can_download: true,
    contract_status: "in_progress" as const,
    signature_status: "unsigned" as const,
  };

  it("autor/admin, niepodpisana „W trakcie” — tak", () => {
    expect(canCorrectInForm(base)).toBe(true);
    expect(generatorEditHref(7)).toBe(
      "/contracts/b2b-generator?tab=generator&edit=7",
    );
  });

  it("każdy inny przypadek — nie", () => {
    expect(canCorrectInForm({ ...base, can_edit: false })).toBe(false);
    expect(canCorrectInForm({ ...base, can_download: false })).toBe(false);
    expect(canCorrectInForm({ ...base, contract_status: "cancelled" })).toBe(false);
    expect(
      canCorrectInForm({ ...base, signature_status: "signed_both" }),
    ).toBe(false);
  });
});
