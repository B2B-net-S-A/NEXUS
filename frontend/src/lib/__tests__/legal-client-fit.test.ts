import { describe, expect, it } from "vitest";

import type { ClientFitFinding } from "@/lib/api/legalClientFit";
import {
  affectedLabel,
  annexHasText,
  appendAnnexText,
  clientFitAnnexHref,
  clientFitTitle,
  findingsCountLabel,
  gapsLabel,
  panelFindings,
  parseClientFitParam,
  sortFindings,
} from "@/lib/legal-client-fit";

function finding(id: number, state: ClientFitFinding["state"]): ClientFitFinding {
  return {
    id,
    topic: `t${id}`,
    topic_label: `Temat ${id}`,
    state,
    summary: "",
    client_quote: "Fikcyjny zapis klienta.",
    client_ref: "§ 1",
    client_source: { kind: "framework_contract", id: 1, name: "Umowa ramowa" },
    our_quote: null,
    our_ref: null,
    next_step: null,
    annex_text: null,
    lawyer_review: [],
    affected_contracts: 3,
    clause_draft: null,
  };
}

describe("kolejność i wybór ustaleń", () => {
  it("luki przed decyzjami, zgodne na końcu, w grupie kolejność serwera", () => {
    const sorted = sortFindings([finding(1, "ok"), finding(2, "decide"), finding(3, "gap"), finding(4, "gap")]);
    expect(sorted.map((f) => f.id)).toEqual([3, 4, 2, 1]);
  });

  it("panel ma wszystkie luki i decyzje oraz jedną zgodną pozycję", () => {
    const items = panelFindings([finding(1, "ok"), finding(2, "gap"), finding(3, "ok"), finding(4, "decide")]);
    expect(items.map((f) => f.id)).toEqual([2, 4, 1]);
  });

  it("bez zgodnych panel nie dokłada niczego", () => {
    expect(panelFindings([finding(1, "gap")]).map((f) => f.id)).toEqual([1]);
    expect(panelFindings([])).toEqual([]);
  });
});

describe("etykiety", () => {
  it("odmienia luki", () => {
    expect(gapsLabel(1)).toBe("1 luka");
    expect(gapsLabel(2)).toBe("2 luki");
    expect(gapsLabel(4)).toBe("4 luki");
    expect(gapsLabel(5)).toBe("5 luk");
    expect(gapsLabel(12)).toBe("12 luk");
    expect(gapsLabel(22)).toBe("22 luki");
  });

  it("odmienia ustalenia i umowy", () => {
    expect(findingsCountLabel(1)).toBe("1 ustalenie");
    expect(findingsCountLabel(3)).toBe("3 ustalenia");
    expect(findingsCountLabel(7)).toBe("7 ustaleń");
    expect(affectedLabel(1)).toBe("dotyczy 1 aktywnej umowy B2B u klienta");
    expect(affectedLabel(14)).toBe("dotyczy 14 aktywnych umów B2B u klienta");
  });

  it("nagłówek panelu nazywa klienta", () => {
    expect(clientFitTitle("Bank Przykładowy S.A.")).toBe(
      "Sprawdzone z umową ramową Bank Przykładowy S.A. i przepisami",
    );
    expect(clientFitTitle("  ")).toBe("Sprawdzone z umową ramową klienta i przepisami");
  });
});

describe("dopisanie do listy zmian aneksu", () => {
  const empty = { op: "replace" as const, paragraph: "", section: "", text: "" };
  const typed = { op: "replace" as const, paragraph: "5", section: "", text: "Nowe brzmienie." };

  it("pusty wiersz ustępuje, wpisany zostaje, nowy jest „własnym tekstem”", () => {
    const rows = appendAnnexText([empty, typed], "  Partner ukończy szkolenie.  ");
    expect(rows).toEqual([
      typed,
      { op: "free", paragraph: "", section: "", text: "Partner ukończy szkolenie." },
    ]);
  });

  it("to samo zdanie nie wchodzi drugi raz, puste nie wchodzi wcale", () => {
    const once = appendAnnexText([], "Zdanie.");
    expect(appendAnnexText(once, "Zdanie.")).toHaveLength(1);
    expect(appendAnnexText(undefined, "   ")).toEqual([]);
    expect(annexHasText(once, "Zdanie.")).toBe(true);
    expect(annexHasText(once, null)).toBe(false);
  });

  it("nie przekracza limitu zmian aneksu", () => {
    const full = Array.from({ length: 20 }, (_, i) => ({ ...typed, text: `Zmiana ${i}` }));
    expect(appendAnnexText(full, "Nadmiarowa")).toHaveLength(20);
  });
});

describe("adres z zadania", () => {
  it("czyta tylko dodatni numer klienta", () => {
    const params = (value: string | null) => ({ get: () => value });
    expect(parseClientFitParam(params("42"))).toBe(42);
    expect(parseClientFitParam(params("0"))).toBeNull();
    expect(parseClientFitParam(params("12abc"))).toBeNull();
    expect(parseClientFitParam(params(null))).toBeNull();
    expect(parseClientFitParam(null)).toBeNull();
  });

  it("link prowadzi do kreatora aneksu „inna zmiana” z oknem ustaleń", () => {
    expect(clientFitAnnexHref(7)).toBe(
      "/contracts/b2b-generator?tab=annexes&new=annex_custom&zgodnosc=7",
    );
  });
});
