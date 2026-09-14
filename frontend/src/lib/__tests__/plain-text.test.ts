import { describe, expect, it } from "vitest";

import { stripHtmlTags } from "@/lib/plain-text";

describe("stripHtmlTags (UAT M11-B08 — tytuły transkrypcji Fireflies)", () => {
  it("usuwa znaczniki i zwija odstępy", () => {
    expect(stripHtmlTags("<p>Rozmowa   rekrutacyjna</p>")).toBe("Rozmowa rekrutacyjna");
    expect(stripHtmlTags("<p>A</p><p>B</p>")).toBe("A B");
  });

  it("rozwija podstawowe encje i przepuszcza zwykły tekst", () => {
    expect(stripHtmlTags("R&amp;D &lt;test&gt;")).toBe("R&D <test>");
    expect(stripHtmlTags("Zwykły tytuł")).toBe("Zwykły tytuł");
    expect(stripHtmlTags(null)).toBe("");
  });
});

describe("stripHtmlTags — encje polskich znaków (UAT B09)", () => {
  it("rozwija nazwane encje polskich liter, także w treści bez znaczników", () => {
    expect(stripHtmlTags("nie analizował w og&oacute;le wąskich gardeł")).toBe(
      "nie analizował w ogóle wąskich gardeł",
    );
    expect(stripHtmlTags("Pracuje na dw&oacute;jce")).toBe("Pracuje na dwójce");
    expect(stripHtmlTags("&Lstrok;&oacute;d&zacute; &aogon;&eogon;&cacute;&nacute;&sacute;&zdot;")).toBe(
      "Łódź ąęćńśż",
    );
  });

  it("rozwija encje numeryczne dziesiętne i szesnastkowe", () => {
    expect(stripHtmlTags("og&#243;le i dw&#xF3;jka")).toBe("ogóle i dwójka");
  });

  it("nieznaną encję zostawia dosłownie, `&nbsp;` zwija do spacji", () => {
    expect(stripHtmlTags("A&nbsp;&nbsp;B &foo; C")).toBe("A B &foo; C");
  });
});
