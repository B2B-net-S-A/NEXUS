import { describe, expect, it } from "vitest";

import {
  needsRegistryDialog,
  registryDiffs,
  registryOverrides,
  verificationFailed,
  type CompanyVerification,
  type RegistryCompany,
} from "@/lib/b2b-registry-check";

const company: RegistryCompany = {
  name: "JK SOFTWARE - JAN KOWALSKI",
  person: "Jan Kowalski",
  nip: "1234563218",
  regon: "12345678500000",
  krs: null,
  address: "UL. PROSTA 1/2, 00-001 WARSZAWA",
  entity_type: "sole_trader",
};

const form = {
  legalName: "JK Software Jan Kowalski",
  address: "Prosta 1/2, 00-001 Warszawa",
  regon: "123456785",
};

function verified(overrides: Partial<CompanyVerification> = {}): CompanyVerification {
  return {
    status: "verified",
    registry: "ceidg",
    checked_at: "2026-09-28T10:00:00Z",
    company,
    warnings: [],
    message: null,
    ...overrides,
  };
}

describe("registryDiffs", () => {
  it("ignoruje wielkość liter, interpunkcję, „ul.” i REGON 14-cyfrowy z zerami", () => {
    expect(registryDiffs(form, company)).toEqual([]);
    expect(
      registryDiffs({ ...form, address: "ulica Prosta 1/2, 00-001 Warszawa" }, company),
    ).toEqual([]);
  });

  it("zgłasza realną zmianę adresu, nazwy i REGON-u", () => {
    const diffs = registryDiffs(
      { legalName: "Stara Firma", address: "Krzywa 5, 00-002 Kraków", regon: "111111111" },
      company,
    );
    expect(diffs.map((d) => d.field)).toEqual(["legalName", "address", "regon"]);
    expect(diffs[1]).toMatchObject({
      label: "Adres siedziby firmy",
      form: "Krzywa 5, 00-002 Kraków",
      registry: "UL. PROSTA 1/2, 00-001 WARSZAWA",
    });
  });

  it("brak wartości w rejestrze to nie różnica", () => {
    expect(
      registryDiffs({ ...form, regon: "999999999" }, { ...company, regon: null }),
    ).toEqual([]);
    expect(registryDiffs(form, null)).toEqual([]);
  });

  it("puste pole formularza przy danych w rejestrze to różnica", () => {
    expect(registryDiffs({ ...form, regon: "" }, company).map((d) => d.field)).toEqual([
      "regon",
    ]);
  });
});

describe("needsRegistryDialog", () => {
  it("bez ostrzeżeń i różnic nie otwiera okna", () => {
    expect(needsRegistryDialog(verified(), [])).toBe(false);
  });

  it("otwiera okno przy ostrzeżeniu, braku weryfikacji albo różnicy", () => {
    expect(
      needsRegistryDialog(
        verified({ warnings: [{ code: "krs_liquidation", message: "x" }] }),
        [],
      ),
    ).toBe(true);
    expect(needsRegistryDialog(verificationFailed(), [])).toBe(true);
    expect(
      needsRegistryDialog(verified(), registryDiffs({ ...form, regon: "1" }, company)),
    ).toBe(true);
  });
});

it("registryOverrides mapuje pola na ładunek /render", () => {
  const diffs = registryDiffs(
    { legalName: "Stara", address: "Krzywa 5", regon: "123456785" },
    company,
  );
  expect(registryOverrides(diffs)).toEqual({
    partner_legal_name: "JK SOFTWARE - JAN KOWALSKI",
    partner_business_address: "UL. PROSTA 1/2, 00-001 WARSZAWA",
  });
});
