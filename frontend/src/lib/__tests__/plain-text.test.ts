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
