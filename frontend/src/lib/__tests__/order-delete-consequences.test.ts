/**
 * Dialog usuwania zamówienia ma mówić PRAWDĘ.
 *
 * Do 18.09.2026 natywny `confirm` twierdził: „pozostałe zamówienia i umowa tej
 * osoby nie zmienią się". Tymczasem `ContractClientRate.source_order_id` ma
 * `ondelete=CASCADE`, a `Contract._resolve_scheduled_rate` przy braku kroku
 * obowiązującego sięga po najbliższy PRZYSZŁY — miesiące historyczne dostają
 * inną stawkę. Na produkcji: 99 zamówień ma własny krok, 31 kontraktów ma ich
 * więcej niż jeden, 5 z różnymi kwotami.
 */

import { describe, expect, it } from "vitest";

import type { OrderDeletePreview } from "@/lib/api/dlPortal";
import {
  NO_SIDE_EFFECTS_TEXT,
  orderDeleteBlocked,
  orderDeleteConsequences,
  rateChangeSentence,
} from "@/lib/order-delete-consequences";

function preview(over: Partial<OrderDeletePreview> = {}): OrderDeletePreview {
  return {
    order_id: 351,
    order_number: "351",
    status: "active",
    is_group_line: false,
    deletes_row: true,
    blocked_by: [],
    has_file: false,
    rate_changes: [],
    currency: "PLN",
    rate_unit: "hourly",
    amounts_redacted: false,
    ...over,
  };
}

describe("orderDeleteConsequences", () => {
  it("bez skutków ubocznych mówi to WPROST, zamiast obiecywać w ciemno", () => {
    expect(orderDeleteConsequences(preview())).toEqual([]);
    // Zdanie pada wyłącznie wtedy, gdy jest prawdziwe.
    expect(NO_SIDE_EFFECTS_TEXT).toContain("nic się nie zmieni");
  });

  it("wymienia przecenione okresy z kwotami — przypadek kontraktu 167", () => {
    const items = orderDeleteConsequences(
      preview({
        rate_changes: [
          {
            effective_from: "2026-03-01",
            effective_until: "2026-09-01",
            rate: 185,
            replacement_rate: 178,
            changes_amount: true,
          },
        ],
      }),
    );

    expect(items).toHaveLength(1);
    expect(items[0].tone).toBe("warning");
    expect(items[0].text).toContain("01.03.2026");
    expect(items[0].text).toContain("01.09.2026");
    expect(items[0].text).toContain("185,00 PLN/h");
    expect(items[0].text).toContain("178,00 PLN/h");
  });

  it("krok o tej samej kwocie nie straszy — zmienia się pochodzenie, nie cena", () => {
    const items = orderDeleteConsequences(
      preview({
        rate_changes: [
          {
            effective_from: "2026-03-01",
            effective_until: null,
            rate: 185,
            replacement_rate: 185,
            changes_amount: false,
          },
        ],
      }),
    );
    expect(items[0].tone).toBe("info");
    expect(items[0].text).toContain("kwota zostaje bez zmian");
  });

  it("bez dostępu do finansów mówi, ŻE się przeceni — bez kwot", () => {
    const items = orderDeleteConsequences(
      preview({
        amounts_redacted: true,
        currency: null,
        rate_changes: [
          {
            effective_from: "2026-03-01",
            effective_until: "2026-09-01",
            rate: null,
            replacement_rate: null,
            changes_amount: true,
          },
        ],
      }),
    );
    expect(items[0].text).toContain("przeliczony inną stawką");
    expect(items[0].text).not.toMatch(/\d+,\d\d/);
  });

  it("rozliczenia blokują usunięcie i mówią, co by przepadło", () => {
    const p = preview({ blocked_by: ["rozliczone MD konsultantów (12)"] });
    expect(orderDeleteBlocked(p)).toBe(true);
    expect(orderDeleteConsequences(p)[0].tone).toBe("blocked");
    expect(orderDeleteConsequences(p)[0].text).toContain("rozliczone MD");
  });

  it("linia grupy zostaje anulowana, a nie usunięta — i dialog to mówi", () => {
    const items = orderDeleteConsequences(
      preview({ is_group_line: true, deletes_row: false }),
    );
    expect(items.map((i) => i.text).join(" ")).toContain("anulowane");
  });

  it("wgrany dokument PO zniknie razem z zamówieniem", () => {
    const items = orderDeleteConsequences(preview({ has_file: true }));
    expect(items.map((i) => i.text).join(" ")).toContain("PO");
  });
});

describe("rateChangeSentence", () => {
  it("krok bez daty końca opisuje otwarty okres", () => {
    const text = rateChangeSentence(
      {
        effective_from: "2026-03-01",
        effective_until: null,
        rate: 185,
        replacement_rate: 178,
        changes_amount: true,
      },
      "PLN",
      "hourly",
    );
    expect(text).toContain("od 01.03.2026");
    expect(text).not.toContain("do ");
  });
});

describe("FIN-02 (audyt 22.09 r2): okres bez żadnej stawki", () => {
  it("mówi wprost, że kontrakt zostanie bez przychodu", () => {
    const text = rateChangeSentence(
      {
        effective_from: "2026-09-15",
        effective_until: null,
        rate: 167.5,
        replacement_rate: null,
        changes_amount: true,
        removes_revenue: true,
      },
      "PLN",
      "hourly",
    );
    expect(text).toBe(
      "Okres od 15.09.2026 straci stawkę klienta — kontrakt zostanie bez przychodu.",
    );
  });

  it("rola bez finansów też dostaje to zdanie (to nie jest kwota)", () => {
    const text = rateChangeSentence(
      {
        effective_from: "2026-09-15",
        effective_until: "2026-12-31",
        rate: null,
        replacement_rate: null,
        changes_amount: true,
        removes_revenue: true,
      },
      null,
      null,
    );
    expect(text).toContain("kontrakt zostanie bez przychodu");
  });
});
