import { describe, expect, it } from "vitest";

import {
  acceptAll,
  acceptedChanges,
  aiStatusMessage,
  changeNumbers,
  dispositionFilename,
  effectiveChange,
  insertedParagraphs,
  isDocxName,
  paragraphPieces,
  summarize,
  type RedlineChange,
  type RedlineParagraph,
} from "@/lib/legal-redline";

const P: RedlineParagraph = {
  index: 1,
  text: "Partner świadczy usługi przez 30 dni.",
  style: null,
  in_table: false,
  heading: false,
};

function change(over: Partial<RedlineChange> & Pick<RedlineChange, "id">): RedlineChange {
  return {
    kind: "replace",
    paragraph: 1,
    new_text: "",
    find: "",
    start: null,
    end: null,
    before: false,
    reason: "",
    sources: [],
    blocked: false,
    ...over,
  };
}

const at = (find: string) => ({ find, start: P.text.indexOf(find), end: P.text.indexOf(find) + find.length });

describe("paragraphPieces", () => {
  it("pokazuje skreślenie i wstawkę w miejscu zmiany", () => {
    const pieces = paragraphPieces(P, [change({ id: "a", ...at("30"), new_text: "14" })], {}, {});
    expect(pieces).toEqual([
      { kind: "text", text: "Partner świadczy usługi przez " },
      { kind: "del", text: "30", changeId: "a", decision: "pending" },
      { kind: "ins", text: "14", changeId: "a", decision: "pending" },
      { kind: "text", text: " dni." },
    ]);
  });

  it("odrzucona zmiana to zwykły tekst oryginału", () => {
    const pieces = paragraphPieces(P, [change({ id: "a", ...at("30"), new_text: "14" })], { a: "rejected" }, {});
    expect(pieces).toEqual([{ kind: "text", text: P.text }]);
  });

  it("dopisanie na końcu i poprawka z „Zmień”", () => {
    const end = P.text.length;
    const pieces = paragraphPieces(
      P,
      [change({ id: "b", start: end, end, new_text: " Zdalnie." })],
      {},
      { b: { new_text: " Z biura.", reason: "" } },
    );
    expect(pieces.at(-1)).toEqual({ kind: "ins", text: " Z biura.", changeId: "b", decision: "pending" });
  });

  it("skreślenie całego akapitu", () => {
    const pieces = paragraphPieces(P, [change({ id: "x", kind: "delete_paragraph", find: P.text })], {}, {});
    expect(pieces).toEqual([{ kind: "del", text: P.text, changeId: "x", decision: "pending" }]);
  });

  it("nakładające się zmiany nie psują tekstu — druga jest pomijana w podglądzie", () => {
    const pieces = paragraphPieces(
      P,
      [change({ id: "a", ...at("usługi przez"), new_text: "x" }), change({ id: "b", ...at("przez 30"), new_text: "y" })],
      {},
      {},
    );
    expect(pieces.filter((p) => p.kind === "text").map((p) => p.text).join("")).toBe("Partner świadczy  30 dni.");
  });
});

describe("decyzje", () => {
  const blocked = change({
    id: "z",
    ...at("Partner"),
    new_text: "Wykonawca",
    blocked: true,
    sources: [{ ref: "kc", label: "art. 1 KC", quote: "nie ma", kind: "law", state: "mismatch" }],
  });
  const ok = change({ id: "a", ...at("30"), new_text: "14" });

  it("„Przyjmij wszystkie” pomija zablokowany cytat", () => {
    expect(acceptAll([ok, blocked], {}, {})).toEqual({ a: "accepted" });
  });

  it("„Zmień” zdejmuje niesprawdzony cytat i blokadę", () => {
    const edited = effectiveChange(blocked, { new_text: "Wykonawca", reason: "Moja decyzja." });
    expect(edited.blocked).toBe(false);
    expect(edited.sources).toEqual([]);
    expect(edited.reason).toBe("Moja decyzja.");
  });

  it("do pliku idą tylko przyjęte, w kolejności dokumentu, po poprawkach", () => {
    const later = change({ id: "c", paragraph: 3, start: 0, end: 0, new_text: "X" });
    const result = acceptedChanges(
      [later, ok, blocked],
      { c: "accepted", a: "accepted", z: "rejected" },
      { a: { new_text: "21", reason: "r" } },
    );
    expect(result.map((c) => c.id)).toEqual(["a", "c"]);
    expect(result[0].new_text).toBe("21");
  });

  it("podsumowanie liczy stany i blokady", () => {
    expect(summarize([ok, blocked], { a: "accepted" }, {})).toEqual({
      total: 2,
      accepted: 1,
      rejected: 0,
      pending: 1,
      blocked: 1,
    });
  });

  it("numery zmian idą za kolejnością w dokumencie", () => {
    const insert = change({ id: "n", kind: "insert_paragraph", paragraph: 1, new_text: "Nowy" });
    const first = change({ id: "f", paragraph: 0, start: 0, end: 1, find: "x", new_text: "y" });
    expect([...changeNumbers([insert, ok, first]).entries()]).toEqual([
      ["f", 1],
      ["a", 2],
      ["n", 3],
    ]);
  });
});

describe("nowe akapity", () => {
  it("odrzucony nowy akapit znika z podglądu", () => {
    const insert = change({ id: "n", kind: "insert_paragraph", paragraph: 1, new_text: "Nowy" });
    expect(insertedParagraphs(1, [insert], {}, {}, "after")).toHaveLength(1);
    expect(insertedParagraphs(1, [insert], { n: "rejected" }, {}, "after")).toHaveLength(0);
    expect(insertedParagraphs(1, [insert], {}, {}, "before")).toHaveLength(0);
  });
});

describe("pomocnicze", () => {
  it("rozpoznaje DOCX po nazwie", () => {
    expect(isDocxName("Umowa 12-2026.DOCX")).toBe(true);
    expect(isDocxName("Umowa.pdf")).toBe(false);
    expect(isDocxName("umowa.doc")).toBe(false);
  });

  it("czyta polską nazwę pliku z Content-Disposition", () => {
    const header = "attachment; filename=\"Umowa  poprawki asystenta.docx\"; filename*=UTF-8''Umowa%20%E2%80%94%20poprawki%20asystenta.docx";
    expect(dispositionFilename(header, "x")).toBe("Umowa — poprawki asystenta.docx");
    expect(dispositionFilename("", "zapas.docx")).toBe("zapas.docx");
  });

  it("pusta lista z modelu nie wygląda jak „bez uwag”, gdy model padł", () => {
    expect(aiStatusMessage("failed", 0)).toMatch(/nie odpowiedział/);
    expect(aiStatusMessage("ok", 0)).toMatch(/nie zaproponował/);
    expect(aiStatusMessage("ok", 3)).toBeNull();
    expect(aiStatusMessage("off", 0)).toMatch(/wyłączone/);
  });
});
