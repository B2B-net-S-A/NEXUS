import { describe, expect, it } from "vitest";

import {
  assetBody,
  assetsSyncMessage,
  emptyAssetForm,
  monthText,
  parseRate,
  planLabel,
  planWindow,
  rateText,
} from "@/components/accounting/assets-model";
import type { AssetPlanRow } from "@/lib/api/accounting-assets";
import type { SyncResult } from "@/lib/api/accounting";

function form(overrides: Partial<ReturnType<typeof emptyAssetForm>> = {}) {
  return {
    ...emptyAssetForm("2026-07-14", "080"),
    name: "Stacje robocze",
    kst: "491",
    initialValue: "36 900,00",
    balanceRate: "30",
    ...overrides,
  };
}

describe("formularz środka → ciało żądania", () => {
  it("nowy środek z OT: kwoty jako tekst, stawka podatkowa jak bilansowa", () => {
    const { body, problems } = assetBody(form());
    expect(problems).toEqual([]);
    expect(body).toMatchObject({
      name: "Stacje robocze",
      kind: "fixed",
      kst: "491",
      accepted_on: "2026-07-14",
      initial_value: "36900.00",
      mpk: "OG",
      balance_method: "linear",
      balance_rate: "30.00",
      tax_rate: "30.00",
      coefficient: null,
      opening: null,
      post_intake: true,
      counter_account: "080",
    });
  });

  it("wymaga nazwy, KŚT środka trwałego, wartości, MPK i stawki", () => {
    const { problems } = assetBody(
      form({ name: " ", kst: "", initialValue: "0", mpk: "ZARZAD", balanceRate: "", taxRate: "" }),
    );
    expect(problems).toEqual([
      "Podaj nazwę środka.",
      "Podaj symbol KŚT (np. 491).",
      "Podaj wartość początkową większą od zera.",
      "MPK: OG, FO, BO albo K<id klienta>.",
      "Plan bilansowy: podaj stawkę.",
      "Plan podatkowy: podaj stawkę.",
    ]);
  });

  it("WNiP bez KŚT i bez degresywnej podatkowo; jednorazowa bez stawki", () => {
    const intangible = assetBody(form({ kind: "intangible", kst: "", taxMethod: "degressive", taxRate: "50" }));
    expect(intangible.problems).toEqual(["WNiP podatkowo: liniowa albo jednorazowa (art. 16k ustawy o CIT)."]);
    expect(intangible.body.kst).toBeNull();
    const oneOff = assetBody(form({ balanceMethod: "one_off", balanceRate: "", taxMethod: "one_off" }));
    expect(oneOff.problems).toEqual([]);
  });

  it("degresywna niesie współczynnik 1,0–2,0", () => {
    expect(assetBody(form({ balanceMethod: "degressive", coefficient: "2,0" })).body.coefficient).toBe("2.00");
    expect(assetBody(form({ balanceMethod: "degressive", coefficient: "2,5" })).problems).toContain(
      "Współczynnik degresywnej: od 1,0 do 2,0.",
    );
  });

  it("stan z Symfonii zamiast OT: miesiąc i umorzenie, zero dozwolone", () => {
    const { body, problems } = assetBody(
      form({ fromSymfonia: true, openingMonth: "2026-10", openingBalance: "0,00", openingTax: "1 845,00" }),
    );
    expect(problems).toEqual([]);
    expect(body.opening).toEqual({
      month: "2026-10-01",
      balance: "0.00",
      tax: "1845.00",
      balance_year: null,
      tax_year: null,
    });
    expect(body.post_intake).toBeUndefined();
    expect(assetBody(form({ fromSymfonia: true, openingBalance: "abc" })).problems).toContain(
      "Stan z Symfonii: umorzenie jako kwota (np. 1234,56).",
    );
  });

  it("zablokowany plan wysyła tylko opis", () => {
    const { body } = assetBody(form({ initialValue: "1,00" }), { planLocked: true });
    expect(Object.keys(body).sort()).toEqual(["equipment_item_id", "inventory_number", "kst", "name", "note"]);
  });
});

describe("etykiety i plan", () => {
  it("stawki, miesiące i opis planu", () => {
    expect(rateText("30.00")).toBe("30%");
    expect(rateText("12.5")).toBe("12,5%");
    expect(parseRate("12,5%")).toBe("12.50");
    expect(parseRate("101")).toBeNull();
    expect(monthText("2026-10")).toBe("10.2026");
    expect(planLabel("linear", "30.00")).toBe("liniowa, 30% rocznie");
    expect(planLabel("one_off", "0.00")).toBe("jednorazowa");
  });

  it("okno planu trzyma wybrany miesiąc w środku listy", () => {
    const rows: AssetPlanRow[] = Array.from({ length: 40 }, (_, index) => {
      const month = 8 + index;
      const year = 2026 + Math.floor((month - 1) / 12);
      return {
        month: `${year}-${String(((month - 1) % 12) + 1).padStart(2, "0")}`,
        amount: 92_250,
        accumulated: 92_250 * (index + 1),
        net: 0,
      };
    });
    const window = planWindow(rows, "2026-10");
    expect(window).toHaveLength(12);
    expect(window[0].month).toBe("2026-08");
    expect(window.map((row) => row.month)).toContain("2026-10");
    const late = planWindow(rows, "2030-01");
    expect(late[late.length - 1].month).toBe("2029-11");
    expect(planWindow(rows.slice(0, 5), "2026-10")).toHaveLength(5);
  });
});

describe("komunikat po „Nalicz amortyzację”", () => {
  const empty: SyncResult = {
    kind: "assets",
    created: 0,
    rebuilt: 0,
    deleted: 0,
    unchanged: 0,
    skipped: 0,
    problems: [],
    problems_total: 0,
  };
  it("mówi, co trafiło do bufora i ile czeka na wyjaśnienie", () => {
    expect(
      assetsSyncMessage({
        depreciation: { ...empty, created: 1 },
        operations: { ...empty, kind: "asset_docs", created: 2, unchanged: 1, problems_total: 1 },
      }),
    ).toBe("Do bufora — AM: nowe 1; dokumenty środków: nowe 2, bez zmian 1. Do wyjaśnienia: 1 (szczegóły w „Źródłach”).");
    expect(assetsSyncMessage({ depreciation: empty, operations: { ...empty, kind: "asset_docs" } })).toBe(
      "Nic nowego do zaksięgowania w tym miesiącu.",
    );
  });
});
