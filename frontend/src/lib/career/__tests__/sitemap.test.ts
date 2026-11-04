import { describe, expect, it } from "vitest";

import { boardJobSlugs, careerSitemapEntries } from "../sitemap";

describe("mapa strony domeny kariery", () => {
  it("strona główna i otwarte rekrutacje, bez powtórek i dziwnych slugów", () => {
    const entries = careerSitemapEntries("kariera.b2bnetwork.pl", [
      "senior-java-k7q2",
      "senior-java-k7q2",
      "../admin",
      "data-engineer-a1b2",
    ]);
    expect(entries.map((e) => e.url)).toEqual([
      "https://kariera.b2bnetwork.pl/",
      "https://kariera.b2bnetwork.pl/r/senior-java-k7q2",
      "https://kariera.b2bnetwork.pl/r/data-engineer-a1b2",
    ]);
  });

  it("odpowiedź tablicy w innym kształcie albo awaria = brak ofert, nie błąd", () => {
    expect(boardJobSlugs({ jobs: [{ slug: "a-b" }, { slug: 3 }, null] })).toEqual(["a-b"]);
    expect(boardJobSlugs({ detail: "Not Found" })).toEqual([]);
    expect(boardJobSlugs(null)).toEqual([]);
  });
});
