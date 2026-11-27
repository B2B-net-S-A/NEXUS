import { describe, expect, it } from "vitest";

import type { B2BKrzState } from "@/lib/api";
import {
  EMPTY_KRZ_FORM,
  krzBadge,
  krzDialogLine,
  krzFormFromPayload,
  krzFormToPayload,
  krzWaitingLine,
  peselLooksValid,
} from "@/lib/b2b-krz";

const STATE: B2BKrzState = {
  required: true,
  result: null,
  entry_kind: null,
  entry_label: null,
  entry_note: null,
  checked_at: null,
  checked_by_name: null,
  decision: null,
  decision_reason: null,
  decided_at: null,
  decided_by_name: null,
  nip_changed: false,
  block_reason: "Najpierw sprawdź Partnera",
  decider_names: [],
  can_record: true,
  can_decide: false,
};

describe("krzFormToPayload", () => {
  it("nie wysyła nic, dopóki człowiek nie rozstrzygnie", () => {
    expect(krzFormToPayload(EMPTY_KRZ_FORM)).toBeNull();
    expect(krzFormToPayload({ result: "entry", entryKind: null, entryNote: "x" })).toBeNull();
  });

  it("wpis niesie rodzaj i przyciętą notatkę, brak wpisów tylko wynik", () => {
    expect(krzFormToPayload({ result: "clear", entryKind: "bankruptcy", entryNote: "x" })).toEqual({
      result: "clear",
    });
    expect(
      krzFormToPayload({ result: "entry", entryKind: "enforcement", entryNote: "  Km 1/24 " }),
    ).toEqual({ result: "entry", entry_kind: "enforcement", entry_note: "Km 1/24" });
  });

  it("wczytuje wynik zapisanej umowy przy „Popraw”", () => {
    expect(krzFormFromPayload(null)).toEqual(EMPTY_KRZ_FORM);
    expect(krzFormFromPayload({ result: "entry", entry_kind: "alimony", entry_note: null })).toEqual({
      result: "entry",
      entryKind: "alimony",
      entryNote: "",
    });
  });
});

describe("krzBadge", () => {
  it("mówi, co blokuje umowę", () => {
    expect(krzBadge(STATE)).toEqual({ tone: "warning", label: "KRZ: nie sprawdzono" });
    expect(krzBadge({ ...STATE, nip_changed: true }).label).toContain("NIP zmieniony");
    expect(krzBadge({ ...STATE, result: "clear" })).toEqual({
      tone: "success",
      label: "KRZ: brak wpisów",
    });
    expect(krzBadge({ ...STATE, result: "entry" }).label).toBe("KRZ: wpis, decyzja DL");
    expect(krzBadge({ ...STATE, result: "entry", decision: "allowed" }).tone).toBe("warning");
    expect(krzBadge({ ...STATE, result: "entry", decision: "rejected" }).tone).toBe("danger");
  });

  it("podaje, kto rozstrzyga wpis", () => {
    expect(krzWaitingLine(STATE)).toBeNull();
    expect(krzWaitingLine({ ...STATE, result: "entry", decider_names: ["Anna Lead"] })).toBe(
      "Czeka na decyzję: Anna Lead.",
    );
    expect(krzWaitingLine({ ...STATE, result: "entry" })).toBe(
      "Czeka na decyzję Delivery Leada.",
    );
  });
});

describe("krzDialogLine", () => {
  it("przypomina o KRZ przed „Pobierz DOCX”, niczego nie blokując", () => {
    expect(krzDialogLine(EMPTY_KRZ_FORM).title).toBe("KRZ: nie sprawdzono");
    expect(krzDialogLine({ result: "clear", entryKind: null, entryNote: "" }).tone).toBe("success");
    expect(
      krzDialogLine({ result: "entry", entryKind: "restructuring", entryNote: "" }).title,
    ).toBe("KRZ: Restrukturyzacja");
  });
});

describe("peselLooksValid", () => {
  it("łapie literówkę po cyfrze kontrolnej", () => {
    expect(peselLooksValid("44051401359")).toBe(true);
    expect(peselLooksValid("44051401358")).toBe(false);
    expect(peselLooksValid("4405140135")).toBe(false);
  });
});
