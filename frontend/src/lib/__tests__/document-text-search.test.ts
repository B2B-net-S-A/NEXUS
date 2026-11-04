import { describe, expect, it } from "vitest";

import {
  activateDocumentMatch,
  clearDocumentHighlights,
  findMatchOffsets,
  foldForSearch,
  hasSearchableText,
  highlightDocumentMatches,
} from "@/lib/document-text-search";

function host(html: string): HTMLDivElement {
  const div = document.createElement("div");
  div.innerHTML = html;
  document.body.appendChild(div);
  return div;
}

function hits(root: Element): string[] {
  const byHit = new Map<string, string>();
  root.querySelectorAll("mark[data-doc-search-hit]").forEach((mark) => {
    const key = mark.getAttribute("data-doc-search-hit") ?? "";
    byHit.set(key, (byHit.get(key) ?? "") + mark.textContent);
  });
  return [...byHit.values()];
}

describe("foldForSearch", () => {
  it("ignores case and Polish diacritics one character per character", () => {
    const text = "Łódź, POZNAŃ, Żółć";
    const folded = foldForSearch(text);
    expect(folded).toBe("lodz, poznan, zolc");
    expect(folded.length).toBe(text.length);
  });
});

describe("findMatchOffsets", () => {
  it("finds every non-overlapping match regardless of case and diacritics", () => {
    expect(findMatchOffsets("Poznań i poznan, POZNAN", "poznań")).toEqual([
      [0, 6],
      [9, 15],
      [17, 23],
    ]);
  });

  it("matches a space in the query against any run of whitespace", () => {
    expect(findMatchOffsets("Comarch   S.A.", "comarch s.a.")).toEqual([
      [0, 14],
    ]);
  });

  it("treats regex characters literally and skips one-letter queries", () => {
    expect(findMatchOffsets("C# i C++", "c++")).toEqual([[5, 8]]);
    expect(findMatchOffsets("a a a", "a")).toEqual([]);
  });

  // „Szukaj w CV” przy wymaganiu „.NET lub C#” (16.10.2026): lista słów, nie
  // jedna fraza — każde słowo osobno, dłuższe wygrywa z krótszym w tym samym miejscu.
  it("searches a list of words, each on its own", () => {
    const text = "C# and .NET 8 (ASP.NET Core)";
    expect(findMatchOffsets(text, ".NET lub C#")).toEqual([]);
    expect(findMatchOffsets(text, [".NET", "C#"])).toEqual([
      [0, 2],
      [7, 11],
      [18, 22],
    ]);
    expect(findMatchOffsets("ASP.NET Core", [".NET", "ASP.NET Core"])).toEqual([[0, 12]]);
    expect(findMatchOffsets("C i C++", ["C", "C++"])).toEqual([[4, 7]]);
    expect(findMatchOffsets("C# only", [])).toEqual([]);
  });
});

describe("highlightDocumentMatches (DOCX)", () => {
  it("highlights matches split across Word runs within one paragraph", () => {
    const root = host("<p><span>Com</span><span>arch</span> ERP</p><p>comarch</p>");
    expect(highlightDocumentMatches(root, "Comarch")).toBe(2);
    expect(hits(root)).toEqual(["Comarch", "comarch"]);
    expect(root.textContent).toBe("Comarch ERPcomarch");
  });

  it("highlights every word of a requirement's list", () => {
    const root = host("<p>Microservices in C# and .NET 8</p><p>Skills: C#</p>");
    expect(highlightDocumentMatches(root, [".NET", "C#"])).toBe(3);
    expect(hits(root)).toEqual(["C#", ".NET", "C#"]);
  });

  it("never matches across a paragraph boundary", () => {
    const root = host("<p>Selen</p><p>ium</p>");
    expect(highlightDocumentMatches(root, "selenium")).toBe(0);
  });

  it("ignores CSS injected by docx-preview", () => {
    const root = host("<style>.docx { selenium: 1 }</style><p>Java</p>");
    expect(highlightDocumentMatches(root, "selenium")).toBe(0);
    expect(hasSearchableText(host("<style>p{}</style><p> </p>"))).toBe(false);
    expect(hasSearchableText(root)).toBe(true);
  });

  it("replaces previous highlights and restores the original text on clear", () => {
    const root = host("<p>QA Automation Engineer, QA Engineer</p>");
    expect(highlightDocumentMatches(root, "qa")).toBe(2);
    expect(highlightDocumentMatches(root, "engineer")).toBe(2);
    expect(hits(root)).toEqual(["Engineer", "Engineer"]);
    clearDocumentHighlights(root);
    expect(root.querySelectorAll("mark").length).toBe(0);
    expect(root.innerHTML).toBe("<p>QA Automation Engineer, QA Engineer</p>");
  });

  it("marks exactly one match as active", () => {
    const root = host("<p>test <b>test</b> test</p>");
    expect(highlightDocumentMatches(root, "test")).toBe(3);
    activateDocumentMatch(root, 1);
    const active = root.querySelectorAll("mark[data-active]");
    expect(active).toHaveLength(1);
    expect(active[0].getAttribute("data-doc-search-hit")).toBe("1");
    activateDocumentMatch(root, 2);
    expect(root.querySelectorAll("mark[data-active]")).toHaveLength(1);
  });
});
