/**
 * Lista zmian aneksu z własną nazwą (16.11.2026) — lustro reguł serwera
 * (`registry.annex_changes_problems`, `context.annex_change_points`).
 */
import { describe, expect, it } from "vitest";

import type { AnnexChangeRow, DocumentTypeDef } from "@/lib/api/b2bDocuments";
import {
  annexChangeLead,
  annexChangesProblems,
  cleanAnnexChanges,
  clauseRows,
  fillClauseText,
} from "@/lib/annex-changes";
import { annexChangeText, annexTitle, cleanValues, invalidListFields, missingRequired } from "@/lib/b2b-documents";

const row = (patch: Partial<AnnexChangeRow>): AnnexChangeRow => ({
  op: "replace",
  paragraph: "",
  section: "",
  text: "",
  ...patch,
});

const TYPE = {
  key: "annex_custom",
  fields: [
    {
      key: "annex_title",
      label: "Czego dotyczy aneks",
      kind: "text",
      required: true,
      sensitive: false,
      help: null,
      options: [],
      show_if: null,
      group: "change",
      lookup: null,
      lookup_fills: [],
    },
    {
      key: "changes",
      label: "Zmiany w umowie",
      kind: "annex_changes",
      required: true,
      sensitive: false,
      help: null,
      options: [],
      show_if: null,
      group: "change",
      lookup: null,
      lookup_fills: [],
    },
  ],
} as unknown as DocumentTypeDef;

describe("lista zmian aneksu", () => {
  it("odmawia tymi samymi zdaniami co serwer", () => {
    expect(
      annexChangesProblems([
        row({ op: "replace", text: "x" }),
        row({ op: "add", paragraph: "10", text: "x" }),
        row({ op: "replace", paragraph: "10", section: "1", text: " " }),
        row({ op: "delete", paragraph: "7" }),
        row({ op: "free", text: "Własny punkt." }),
      ]),
    ).toEqual([
      "Zmiana 1: podaj numer paragrafu (§).",
      "Zmiana 2: podaj numer dodawanego ustępu.",
      "Zmiana 3: wpisz treść.",
    ]);
  });

  it("nie przepuszcza klauzuli z niepodstawionym miejscem", () => {
    expect(annexChangesProblems([row({ op: "free", text: "na rzecz: [uzupełnij]," })])).toEqual([
      "Zmiana 1: uzupełnij miejsca oznaczone [uzupełnij].",
    ]);
  });

  it("pomija zupełnie puste wiersze i obcina spacje", () => {
    expect(
      cleanAnnexChanges([row({}), row({ op: "free", text: "  Punkt  " })]),
    ).toEqual([{ op: "free", paragraph: "", section: "", text: "Punkt" }]);
  });

  it("pusta lista to brak wymaganego pola, a nie lista stawek", () => {
    expect(missingRequired(TYPE, { annex_title: "zmiana", changes: [row({})] })).toEqual([
      "Zmiany w umowie",
    ]);
    expect(
      missingRequired(TYPE, { annex_title: "zmiana", changes: [row({ op: "free", text: "x" })] }),
    ).toEqual([]);
  });

  it("wysyła oczyszczone wiersze i zgłasza ich problemy w walidacji formularza", () => {
    const values = {
      annex_title: " zmiana ",
      changes: [row({}), row({ op: "delete", paragraph: " 7 " })],
    };
    expect(cleanValues(TYPE, values)).toEqual({
      annex_title: "zmiana",
      changes: [{ op: "delete", paragraph: "7", section: "", text: "" }],
    });
    expect(invalidListFields(TYPE, { changes: [row({ op: "add", paragraph: "10", text: "x" })] })).toEqual([
      "Zmiana 1: podaj numer dodawanego ustępu.",
    ]);
  });

  it("pokazuje formułkę, którą dopisze dokument", () => {
    expect(annexChangeLead(row({ paragraph: "§10", section: "1" }))).toBe(
      "§ 10 ust. 1 Umowy otrzymuje brzmienie: „…”",
    );
    expect(annexChangeLead(row({ op: "add", paragraph: "10", section: "2a" }))).toBe(
      "w § 10 Umowy dodaje się ust. 2a w brzmieniu: „…”",
    );
    expect(annexChangeLead(row({ op: "delete", paragraph: "7" }))).toBe("§ 7 Umowy skreśla się.");
  });
});

describe("gotowe klauzule", () => {
  it("podstawia paragraf i klienta, a brak zostawia do uzupełnienia", () => {
    expect(
      fillClauseText("w {non_compete_paragraph} na rzecz: {client_legal_name}.", {
        non_compete_paragraph: "§ 10 ust. 1",
        client_legal_name: " ",
      }),
    ).toBe("w § 10 ust. 1 na rzecz: [uzupełnij].");
  });

  it("buduje wiersze z definicji klauzuli", () => {
    expect(
      clauseRows(
        { key: "k", label: "K", title: "t", rows: [{ op: "free", text: "dla {client_legal_name}" }] },
        { client_legal_name: "PKO BP S.A." },
      ),
    ).toEqual([{ op: "free", paragraph: "", section: "", text: "dla PKO BP S.A." }]);
  });
});

describe("rejestr aneksów", () => {
  it("pokazuje nazwę nadaną aneksowi", () => {
    expect(annexTitle("annex_custom")).toBe("Inna zmiana");
    expect(
      annexChangeText({ kind: "custom", title: "zwolnienie z zakazu konkurencji", count: 1 }),
    ).toEqual({ before: null, after: "zwolnienie z zakazu konkurencji" });
    expect(annexChangeText({ kind: "custom", title: null, count: 0 })).toBeNull();
  });
});
