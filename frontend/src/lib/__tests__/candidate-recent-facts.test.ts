import { describe, expect, it } from "vitest";
import {
  recentFactDate,
  recentFactLabel,
  recentFactText,
  recentFactsTitle,
  type RecentFact,
} from "@/lib/candidate-recent-facts";

const talk: RecentFact = { at: "2026-11-02T13:09:06Z", kind: "talk", text: "dostępność ASAP, 110 zł/h" };
const refusal: RecentFact = {
  at: "2026-07-30T11:12:17Z",
  kind: "note",
  text: "nie jest zainteresowany i prosi żeby nie wydzwaniać",
};

describe("„Ostatnio z osobą”", () => {
  it("data w kalendarzu firmy — 23:30 UTC 31.12 to już 01.01 w Warszawie", () => {
    expect(recentFactDate("2026-11-02T13:09:06Z")).toBe("02.11.26");
    expect(recentFactDate("2026-12-31T23:30:00Z")).toBe("01.01.27");
    expect(recentFactDate("nie-data")).toBeNull();
  });

  it("rodzaj po polsku, odrzucenie z klientem", () => {
    expect(recentFactLabel(talk)).toBe("rozmowa");
    expect(recentFactLabel(refusal)).toBe("notatka");
    expect(recentFactLabel({ ...refusal, kind: "rejection", client_name: "Nordea" })).toBe("odrzucenie (Nordea)");
    expect(recentFactLabel({ ...refusal, kind: "rejection", client_name: null })).toBe("odrzucenie");
  });

  it("cudze słowa w cudzysłowie, podsumowanie rozmowy bez", () => {
    expect(recentFactText(talk)).toBe("dostępność ASAP, 110 zł/h");
    expect(recentFactText(refusal)).toBe("„nie jest zainteresowany i prosi żeby nie wydzwaniać”");
  });

  it("dymek ma każdą informację w osobnej linii, najnowszą pierwszą", () => {
    expect(recentFactsTitle([talk, refusal]).split("\n")).toEqual([
      "02.11.26 · rozmowa — dostępność ASAP, 110 zł/h",
      "30.07.26 · notatka — „nie jest zainteresowany i prosi żeby nie wydzwaniać”",
    ]);
  });
});
