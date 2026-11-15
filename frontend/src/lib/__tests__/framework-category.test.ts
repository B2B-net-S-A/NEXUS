import { describe, expect, it } from "vitest";

import { addonTechnology, type FrameworkCategory } from "@/lib/api/framework-rates";
import {
  categoryFormError,
  limitBreakdown,
  showsFrameworkCard,
  sourceLabel,
  statusTone,
} from "@/lib/framework-category";
import { summarizeRecompute } from "@/lib/framework-terms";

const card = { id: 1, label: "IT Developer - Senior", role: "IT Developer", seniority: "Senior", rate_max: 100, valid_from: null, valid_to: null, addons: ["Kafka 20%"] };

function category(overrides: Partial<FrameworkCategory> = {}): FrameworkCategory {
  return {
    contract_id: 7,
    client_id: 1,
    rate_client: "110",
    framework_limit: "120",
    gap: "-10",
    status: "in_addon",
    card,
    source: "coa",
    coa_label: "IT Developer - Senior",
    addon: { technology: "Kafka", percent: "20.00", confirmed_by: "LM klienta", confirmed_on: "2031-04-01", evidence: null },
    cards: [card],
    ...overrides,
  };
}

describe("karta Umowa ramowa", () => {
  it("rozbija limit na maksimum z cennika i dopłatę", () => {
    expect(limitBreakdown(category())).toBe("100,00 zł/h + 20% Kafka = 120,00 zł/h");
    expect(limitBreakdown(category({ addon: null }))).toBe("100,00 zł/h");
    expect(limitBreakdown(category({ card: null }))).toBeNull();
  });

  it("znika u klienta bez cennika i bez kategorii z COA", () => {
    expect(showsFrameworkCard(category({ cards: [], card: null, coa_label: null }))).toBe(false);
    expect(showsFrameworkCard(category({ cards: [], card: null }))).toBe(true);
    expect(showsFrameworkCard(undefined)).toBe(false);
  });

  it("nazywa źródło kategorii i ton statusu", () => {
    expect(sourceLabel("coa")).toBe("z COA");
    expect(sourceLabel("dl")).toBe("wybrał Delivery Lead");
    expect(sourceLabel(null)).toBeNull();
    expect(statusTone("over")).toBe("danger");
    expect(statusTone("in_addon")).toBe("info");
  });

  it("dopłata bez potwierdzenia klienta nie przechodzi", () => {
    expect(categoryFormError({ rateCardId: null, addon: "", confirmedBy: "", confirmedOn: "" })).toMatch(/kategorię/);
    expect(categoryFormError({ rateCardId: 1, addon: "Kafka", confirmedBy: " ", confirmedOn: "2031-04-01" })).toMatch(/potwierdzeniem/);
    expect(categoryFormError({ rateCardId: 1, addon: "Kafka", confirmedBy: "LM", confirmedOn: "" })).toMatch(/potwierdzeniem/);
    expect(categoryFormError({ rateCardId: 1, addon: "", confirmedBy: "", confirmedOn: "" })).toBeNull();
  });

  it("wyciąga technologię z etykiety dopłaty", () => {
    expect(addonTechnology("Kafka 20%")).toBe("Kafka");
    expect(addonTechnology("T24 (Temenos Transact) 10%")).toBe("T24 (Temenos Transact)");
  });
});

describe("Przelicz kategorie z COA", () => {
  it("liczy wyniki w stałej kolejności, zmienione najpierw", () => {
    const row = (outcome: string) => ({ contract_id: 1, outcome, coa_label: null, category_before: null, category_after: null, limit_before: null, limit_after: null });
    expect(summarizeRecompute([row("no_coa"), row("updated"), row("no_coa"), row("weird")])).toEqual([
      ["updated", 1],
      ["no_coa", 2],
      ["weird", 1],
    ]);
  });
});
