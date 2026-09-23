import { describe, expect, it } from "vitest";

import {
  excelRowBadges,
  registerRowWarnings,
} from "@/lib/b2b-generator-register";

const base = {
  contract_status: "active" as const,
  signature_status: "signed_both" as const,
  contract_id: null,
  linked_contract_status: null,
  linked_contract_end_date: null,
};

describe("wiersze z rejestru Excela", () => {
  it("dostają plakietkę „Z Excela” i etykiety flag importu", () => {
    const badges = excelRowBadges({
      source: "excel",
      legacy_flags: ["likely_ended", "unknown_code"],
      needs_business_data_annex: true,
      business_data_annex_done_at: null,
      excel_missing_since: "2026-09-23T10:00:00+00:00",
    });
    expect(badges.map((b) => b.text)).toEqual([
      "Z Excela",
      "W Excelu oznaczona jako zakończona — brak daty, sprawdź status",
      "Czeka na aneks „dane firmy”",
      "Brak w ostatnim pliku Excela",
    ]);
    expect(badges[0].tone).toBe("info");
  });

  it("podpisana umowa z Excela bez kontraktu nie jest „usuniętym kontraktem”", () => {
    const texts = registerRowWarnings({ ...base, source: "excel" }).map((w) => w.text);
    expect(texts).toEqual(["Z Excela"]);
  });

  it("umowa z generatora bez kontraktu nadal ostrzega", () => {
    const texts = registerRowWarnings({ ...base, source: "generator" }).map((w) => w.text);
    expect(texts).toContain("Kontrakt usunięty — brak kontraktora");
    expect(texts).not.toContain("Z Excela");
  });

  it("zrobiony aneks pokazuje datę", () => {
    const [annex] = excelRowBadges({
      source: "generator",
      needs_business_data_annex: true,
      business_data_annex_done_at: "2025-03-03",
    });
    expect(annex.text).toBe("Aneks „dane firmy” zrobiony 03.03.2025");
  });
});
