import { describe, expect, it } from "vitest";

import { commentFromNote, debriefFillSummary, type DebriefFromText } from "@/lib/debrief-from-text";

const base: DebriefFromText = {
  status: "ok",
  message: null,
  questions: [{ text: "Czy zna Kubernetes?", quote: "zna Kubernetes" }],
  offer: null,
  rate: null,
  start: { text: "od 1.12", quote: "zacznie 1 grudnia" },
  dropped: 0,
};

describe("debrief-from-text", () => {
  it("podsumowanie z odmianą liczby pytań", () => {
    expect(debriefFillSummary(base)).toBe("Uzupełnione z notatki: 1 pytanie, start. Sprawdź przed zapisem.");
    const five = { ...base, questions: Array.from({ length: 5 }, (_, i) => ({ text: `P${i}?`, quote: "q" })) };
    expect(debriefFillSummary(five)).toMatch(/^Uzupełnione z notatki: 5 pytań/);
    expect(debriefFillSummary({ ...base, status: "unavailable", message: "Nie teraz" })).toBe("Nie teraz");
  });

  it("komentarz = notatka, start dopisany tylko gdy go w niej nie ma dosłownie", () => {
    expect(commentFromNote(" zacznie 1 grudnia ", base)).toBe("zacznie 1 grudnia\nStart: od 1.12");
    expect(commentFromNote("może od 1.12", base)).toBe("może od 1.12");
    expect(commentFromNote("x".repeat(5000), { ...base, start: null })).toHaveLength(4000);
  });
});
