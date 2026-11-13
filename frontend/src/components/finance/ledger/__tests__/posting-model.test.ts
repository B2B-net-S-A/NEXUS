import { describe, expect, it } from "vitest";

import type { DecreeSection } from "@/lib/api/finance-posting";

import {
  categoryLocked,
  checkDraft,
  fxLabel,
  draftFromSection,
  draftToInput,
  emptyRow,
  formatGrosze,
  previewDescription,
  previousMonth,
  toGrosze,
  unknownTemplateFields,
  type Draft,
} from "../posting-model";

const SECTION: DecreeSection = {
  computed: true,
  manual: false,
  computed_at: "2026-11-13T10:00:00+00:00",
  register: "purchase",
  register_label: "Zakup",
  doc_type: "FVZ",
  description: "Usługi IT 10/2026",
  currency: "PLN",
  rule: { id: 1, label: "Kontraktorzy" },
  positions: [
    {
      kind: "cost",
      kind_label: "Koszt",
      account: "402-203",
      account_name: "Usługi obce",
      side: "debit",
      side_label: "Wn",
      amount: "10000.00",
      vat_rate: "23",
      deduction: "full",
      deduction_label: "100%",
    },
    {
      kind: "vat",
      kind_label: "VAT",
      account: "221",
      account_name: "VAT naliczony",
      side: "debit",
      side_label: "Wn",
      amount: "2300.00",
      vat_rate: "23",
      deduction: "full",
      deduction_label: "100%",
    },
    {
      kind: "counterparty",
      kind_label: "Rozrachunek z kontrahentem",
      account: "201-2-901",
      account_name: null,
      side: "credit",
      side_label: "Ma",
      amount: "12300.00",
      vat_rate: null,
      deduction: null,
      deduction_label: null,
    },
  ],
  debit_total: "12300.00",
  credit_total: "12300.00",
  balanced: true,
  issues: [],
  editable: true,
  batch: null,
  fx_rate: null,
  fx_date: null,
};

describe("kwoty", () => {
  it("czyta polski i kropkowy zapis, odrzuca zero, minus i trzy miejsca", () => {
    expect(toGrosze("1 234,56")).toBe(123456);
    expect(toGrosze("1234.5")).toBe(123450);
    expect(toGrosze("7")).toBe(700);
    expect(toGrosze("0")).toBeNull();
    expect(toGrosze("-5")).toBeNull();
    expect(toGrosze("1,234")).toBeNull();
    expect(toGrosze("")).toBeNull();
    expect(toGrosze("=1+1")).toBeNull();
  });

  it("formatuje grosze po polsku", () => {
    expect(formatGrosze(123456789)).toBe("1 234 567,89");
    expect(formatGrosze(5)).toBe("0,05");
  });
});

describe("szkic korekty", () => {
  it("z dekretu: zbilansowany i bez problemów", () => {
    const draft = draftFromSection(SECTION);
    expect(draft.rows).toHaveLength(3);
    const check = checkDraft(draft);
    expect(check).toMatchObject({ debit: 1230000, credit: 1230000, balanced: true, problems: [] });
  });

  it("bez bilansu podaje różnicę Wn i Ma", () => {
    const draft = draftFromSection(SECTION);
    draft.rows[2] = { ...draft.rows[2], amount: "12299,99" };
    const check = checkDraft(draft);
    expect(check.balanced).toBe(false);
    expect(check.problems).toEqual(["Suma Wn (12 300,00) różni się od sumy Ma (12 299,99)."]);
  });

  it("pusta kwota i konto blokują zapis", () => {
    const draft: Draft = { register: "purchase", doc_type: "FVZ", description: "", rows: [emptyRow()] };
    const problems = checkDraft(draft).problems;
    expect(problems.some((problem) => problem.includes("numer konta"))).toBe(true);
    expect(problems.some((problem) => problem.includes("kwota"))).toBe(true);
  });

  it("zły typ dokumentu blokuje zapis", () => {
    const draft = { ...draftFromSection(SECTION), doc_type: "FV Z!" };
    expect(checkDraft(draft).problems[0]).toContain("Typ dokumentu");
  });

  it("pusty dekret startuje od kosztu, VAT i rozrachunku", () => {
    const draft = draftFromSection({ ...SECTION, positions: [], computed: false });
    expect(draft.rows.map((row) => [row.kind, row.side])).toEqual([
      ["cost", "debit"],
      ["vat", "debit"],
      ["counterparty", "credit"],
    ]);
  });

  it("do API idą kwoty z kropką, konta bez spacji, typ wielkimi literami", () => {
    const draft = draftFromSection(SECTION);
    draft.doc_type = "fvz";
    draft.rows[0] = { ...draft.rows[0], account: " 402 -203", amount: "10 000,5" };
    const input = draftToInput(draft);
    expect(input.doc_type).toBe("FVZ");
    expect(input.positions[0]).toMatchObject({ account: "402-203", amount: "10000.50" });
    expect(input.positions[2].deduction).toBeNull();
  });
});

describe("wzór opisu", () => {
  it("podstawia pola i zgłasza nieznane", () => {
    expect(previewDescription("{usługa} {MM}/{RRRR}", "Usługi IT", { year: 2026, month: 10 })).toBe(
      "Usługi IT 10/2026",
    );
    expect(unknownTemplateFields("{usługa} {miesiac} {MM}")).toEqual(["miesiac"]);
    expect(unknownTemplateFields("{usługa} {MM}/{RRRR} {numer} {kontrahent}")).toEqual([]);
  });

  it("eksport domyślnie za poprzedni miesiąc", () => {
    expect(previousMonth("2026-11-13")).toBe("2026-10");
    expect(previousMonth("2027-01-02")).toBe("2026-12");
  });
});

describe("poprawki po przeglądzie (13.11)", () => {
  it("kategorii nie zmienia się po „Gotowa”, w paczce ani po zaksięgowaniu", () => {
    expect(categoryLocked("verified", false)).toBe(false);
    expect(categoryLocked("new", false)).toBe(false);
    expect(categoryLocked("ready", false)).toBe(true);
    expect(categoryLocked("ready", true)).toBe(true);
    expect(categoryLocked("booked", false)).toBe(true);
  });

  it("kurs NBP na karcie po polsku, bez kursu nic", () => {
    expect(fxLabel({ ...SECTION, currency: "EUR", fx_rate: "4.2512", fx_date: "2026-11-03" })).toBe(
      "Kurs NBP EUR 4,2512 z 03.11.2026",
    );
    expect(fxLabel(SECTION)).toBeNull();
  });
});
