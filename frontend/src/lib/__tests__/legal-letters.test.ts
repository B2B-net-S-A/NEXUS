import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  LETTER_KINDS,
  approvalView,
  availableKinds,
  citationSummary,
  defaultKind,
  letterBody,
  letterFilename,
  letterHref,
  letterKindFromHref,
  mailSubject,
  type LetterDraft,
} from "@/lib/legal-letters";

const NOTICE = { contract_type: "b2b", agreement_termination_party: "consultant", agreement_termination_mode: "notice" };
const PLAIN = { contract_type: "b2b", agreement_termination_party: null, agreement_termination_mode: null };

function draft(overrides: Partial<LetterDraft> = {}): LetterDraft {
  return {
    kind: "notice_reply",
    label: "Odpowiedź na wypowiedzenie Partnera",
    source: "model",
    editable: true,
    template: null,
    subject: "potwierdzenie wypowiedzenia umowy",
    text: "Szanowny Panie, …",
    recipient: { kind: "partner", name: "Jan Testowy", lines: [], email: null, candidate_id: 1 },
    facts: [],
    steps: [],
    deadline_note: null,
    warning: null,
    checks: [],
    counts: { ok: 1, missing: 0, mismatch: 0 },
    blocked: false,
    block_reasons: [],
    issues: [],
    lawyer_review: [],
    passages: [],
    notes: [],
    model: null,
    error: null,
    task_key: null,
    disclaimer: "",
    ...overrides,
  };
}

describe("rodzaje pisma", () => {
  it("lustro rodzajów z backendu", () => {
    const backend = readFileSync(
      path.resolve(process.cwd(), "../backend/app/services/legal/letters.py"),
      "utf-8",
    );
    for (const kind of LETTER_KINDS) expect(backend).toContain(`"${kind.key}"`);
  });

  it("odpowiedź i cofnięcie tylko po wypowiedzeniu Partnera, nic poza B2B", () => {
    expect(availableKinds(NOTICE).map((k) => k.key)).toContain("notice_reply");
    const plain = availableKinds(PLAIN).map((k) => k.key);
    expect(plain).not.toContain("notice_reply");
    expect(plain).not.toContain("notice_withdrawal");
    expect(plain).toContain("termination_notice");
    expect(availableKinds({ ...PLAIN, contract_type: "uop" })).toEqual([]);
    expect(defaultKind(NOTICE, "1")).toBe("notice_reply");
    expect(defaultKind(PLAIN, "notice_reply")).toBe("termination_notice");
    expect(defaultKind(PLAIN, "penalty_note")).toBe("penalty_note");
  });
});

describe("zatwierdzenie", () => {
  it("pytanie o formę blokuje do odpowiedzi", () => {
    const asked = draft({
      warning: { level: "question", title: "", message: "", clause_ref: null, document_name: null, actions: [] },
      blocked: true,
      block_reasons: ["Odpowiedz na pytanie o formę wypowiedzenia."],
    });
    expect(approvalView(asked, asked.text, false).canApprove).toBe(false);
    expect(approvalView(asked, asked.text, true)).toEqual({ canApprove: true, reason: null });
  });

  it("zły cytat blokuje, poprawiony tekst sprawdzi serwer przy zatwierdzeniu", () => {
    const bad = draft({ blocked: true, block_reasons: ["1 cytat nie ma pokrycia w źródłach."] });
    expect(approvalView(bad, bad.text, false)).toEqual({
      canApprove: false,
      reason: "1 cytat nie ma pokrycia w źródłach.",
    });
    expect(approvalView(bad, `${bad.text} poprawka`, false).canApprove).toBe(true);
    // Wzoru nie poprawia się w panelu — blokada zostaje.
    const template = draft({ editable: false, blocked: true, block_reasons: ["We wzorze brakuje danych."] });
    expect(approvalView(template, "inny tekst", false).canApprove).toBe(false);
    expect(approvalView(draft(), "  ", false).canApprove).toBe(false);
  });

  it("podsumowanie cytatów mówi, że nic nie wysłano", () => {
    expect(citationSummary({ ok: 3, missing: 1, mismatch: 0 })).toBe("3 z 4 cytatów sprawdzone · nic nie wysłano");
    expect(citationSummary({ ok: 0, missing: 0, mismatch: 0 })).toBe("bez cytatów · nic nie wysłano");
  });
});

describe("adres i ciało żądania", () => {
  it("panel z adresu ?pismo= bez gubienia innych parametrów", () => {
    expect(letterHref("/contracts/12", "?tab=documents", "notice_reply")).toBe(
      "/contracts/12?tab=documents&pismo=notice_reply",
    );
    expect(letterHref("/contracts/12", "?tab=documents&pismo=1", null)).toBe("/contracts/12?tab=documents");
    expect(letterHref("/contracts/12", "?pismo=1", null)).toBe("/contracts/12");
    expect(letterKindFromHref("/contracts/12?pismo=notice_reply")).toBe("notice_reply");
    expect(letterKindFromHref("/contracts/12")).toBeNull();
  });

  it("ciało bez pustych pól (serwer odrzuca nieznane)", () => {
    expect(letterBody({ kind: "notice_reply", instruction: "  " })).toEqual({ kind: "notice_reply" });
    expect(
      letterBody({ kind: "penalty_note", instruction: " krótko ", penalty_amount: 5000, original_confirmed: true }, "T"),
    ).toEqual({ kind: "penalty_note", instruction: "krótko", penalty_amount: 5000, original_confirmed: true, text: "T" });
  });

  it("temat maila i nazwa pliku", () => {
    expect(mailSubject("potwierdzenie wypowiedzenia")).toBe("Potwierdzenie wypowiedzenia");
    expect(letterFilename("Nota / wezwanie", "2026-11-25")).toBe("Nota - wezwanie — 2026-11-25.docx");
  });
});
