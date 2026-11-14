import { describe, expect, it } from "vitest";

import {
  canAssign,
  companyAccountProblems,
  groupNrb,
  lineLocked,
  lineTone,
  nrbDigits,
  operationsLabel,
  postBlocker,
  postMessage,
  readStatement,
  statementPeriod,
  visibleLines,
} from "@/components/accounting/bank-model";
import type { BankLine, BankStatement } from "@/lib/api/accounting-bank";

function line(overrides: Partial<BankLine> = {}): BankLine {
  return {
    id: 1,
    position: 1,
    booked_on: "2026-11-15",
    direction: "debit",
    amount: 1_000,
    title: "x",
    counterparty_name: "",
    counterparty_last4: null,
    kind: "zus",
    kind_label: "ZUS",
    counter_account: "229",
    payroll: false,
    note: "",
    resolved: true,
    ...overrides,
  };
}

function statement(overrides: Partial<BankStatement> = {}): BankStatement {
  return {
    id: 1,
    format: "mt940",
    bank_account_last4: "2875",
    account_name: "",
    ledger_account: "130-1",
    first_day: "2026-11-02",
    last_day: "2026-11-20",
    debit_total: 1_000,
    credit_total: 0,
    lines: [line()],
    payroll_hidden: false,
    counts: { zus: 1 },
    unresolved: 0,
    documents: [],
    ...overrides,
  };
}

describe("bank — okres i rozpoznanie", () => {
  it("okres wyciągu: jeden dzień, miesiąc i przełom roku", () => {
    expect(statementPeriod("2026-11-20", "2026-11-20")).toBe("20.11.2026");
    expect(statementPeriod("2026-11-02", "2026-11-20")).toBe("02.11–20.11.2026");
    expect(statementPeriod("2026-12-28", "2027-01-03")).toBe("28.12.2026–03.01.2027");
  });

  it("kolor: dopasowanie zielone, reguła niebieska, bez konta żółte, duplikat szary", () => {
    expect(lineTone(line({ kind: "cost_invoice" }))).toBe("success");
    expect(lineTone(line({ kind: "zus" }))).toBe("info");
    expect(lineTone(line({ kind: "zus", resolved: false, counter_account: null }))).toBe("warning");
    expect(lineTone(line({ kind: "duplicate", resolved: true, counter_account: null }))).toBe("neutral");
    expect(lineTone(line({ kind: "manual" }))).toBe("neutral");
  });

  it("zatwierdzony WB blokuje zmianę konta tylko swojej grupy", () => {
    const approved = [{ id: 9, number: "WB 1/2026", status: "approved" as const, payroll: false }];
    expect(lineLocked(line(), approved)).toBe(true);
    expect(lineLocked(line({ payroll: true }), approved)).toBe(false);
    expect(canAssign(line(), approved)).toBe(false);
    expect(canAssign(line(), [{ ...approved[0], status: "draft" }])).toBe(true);
    expect(canAssign(line({ kind: "duplicate" }))).toBe(false);
  });

  it("filtr „bez konta” zostawia tylko nierozpoznane", () => {
    const lines = [line(), line({ id: 2, resolved: false, counter_account: null, kind: "unmatched" })];
    expect(visibleLines(lines, true).map((item) => item.id)).toEqual([2]);
    expect(visibleLines(lines, false)).toHaveLength(2);
  });
});

describe("bank — księgowanie", () => {
  it("blokuje WB z operacjami bez konta i bez operacji do księgowania", () => {
    expect(postBlocker(statement())).toBeNull();
    expect(postBlocker(statement({ unresolved: 1 }))).toBe("Jedna operacja czeka na konto — przypisz je i księguj.");
    expect(postBlocker(statement({ unresolved: 3 }))).toBe("Operacje bez konta (3) — przypisz konta i księguj.");
    expect(postBlocker(statement({ lines: [], payroll_hidden: true }))).toBe(
      "Zostały tylko wypłaty dla zespołu — księguje je osoba z Płacami.",
    );
    expect(postBlocker(statement({ lines: [line({ kind: "duplicate" })] }))).toMatch(/duplikaty/);
  });

  it("komunikat po księgowaniu: nowy, przebudowany albo bez zmian", () => {
    const docs = [{ id: 1, number: "WB 1/2026" }];
    expect(postMessage({ created: 1, rebuilt: 0, unchanged: 0, documents: docs })).toMatch(/^WB w buforze: WB 1\/2026/);
    expect(postMessage({ created: 0, rebuilt: 1, unchanged: 0, documents: docs })).toBe("Przebudowano WB w buforze: WB 1/2026.");
    expect(postMessage({ created: 0, rebuilt: 0, unchanged: 1, documents: docs })).toBe("WB bez zmian: WB 1/2026.");
  });

  it("odmienia operacje", () => {
    expect(operationsLabel(1)).toBe("1 operacja");
    expect(operationsLabel(3)).toBe("3 operacje");
    expect(operationsLabel(5)).toBe("5 operacji");
    expect(operationsLabel(12)).toBe("12 operacji");
    expect(operationsLabel(22)).toBe("22 operacje");
  });

  it("wyciąg z adresu", () => {
    expect(readStatement("?statement=12&year=2026")).toBe(12);
    expect(readStatement("?statement=abc")).toBeNull();
    expect(readStatement("")).toBeNull();
  });
});

describe("bank — rachunki firmy", () => {
  it("numer z pola: spacje, kreski i PL", () => {
    expect(nrbDigits("PL61 1090 1014 0000 0712 1981 2875")).toBe("61109010140000071219812875");
    expect(nrbDigits("61-1090-1014-0000-0712-1981-2875")).toBe("61109010140000071219812875");
    expect(nrbDigits("DE89370400440532013000")).toBe("");
    expect(groupNrb("61109010140000071219812875")).toBe("61 1090 1014 0000 0712 1981 2875");
    expect(groupNrb("…2875")).toBe("…2875");
  });

  it("lista rachunków: numer, konto i powtórka", () => {
    const row = { key: "a", number: "61 1090 1014 0000 0712 1981 2875", account: "130-1", name: "" };
    expect(companyAccountProblems([row])).toEqual([]);
    expect(companyAccountProblems([{ ...row, number: "123" }])[0]).toMatch(/26 cyfr/);
    expect(companyAccountProblems([{ ...row, account: " " }])[0]).toMatch(/konto w planie/);
    expect(companyAccountProblems([row, { ...row, key: "b" }])).toEqual(["Rachunek 2 jest na liście dwa razy."]);
  });
});
