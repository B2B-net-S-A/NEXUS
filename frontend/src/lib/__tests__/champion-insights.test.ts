import { describe, expect, it } from "vitest";

import type { InsightNote } from "@/lib/api";
import {
  applyInsightEdit,
  askClientItems,
  newInsight,
  removeInsight,
  visibleInsights,
} from "@/lib/champion-insights";

const note = (over: Partial<InsightNote>): InsightNote => ({
  id: "n-1",
  source: "client",
  topic: "needs",
  audience: "team",
  text: "Szukają kogoś z acquiringu",
  origin: "manual",
  editable: true,
  ...over,
});

describe("sekcja 8 — wpisy „z importu” zmieniają STARE pole klienta", () => {
  const legacy = note({
    id: "legacy:client.consultant_insight",
    source: "consultant",
    origin: "legacy",
    text: "Zespół 6 osób",
  });

  it("edycja wpisu legacy daje łatkę `client.consultant_insight`", () => {
    const change = applyInsightEdit([legacy], legacy.id, { text: "Zespół 8 osób" });
    expect(change.client).toEqual({ consultant_insight: "Zespół 8 osób" });
    expect(change.insights[0].text).toBe("Zespół 8 osób");
  });

  it("usunięcie wpisu legacy czyści stare pole — serwer nie zapisze go jako notatki", () => {
    const change = removeInsight([legacy], legacy.id);
    expect(change.insights).toEqual([]);
    expect(change.client).toEqual({ consultant_insight: "" });
  });

  it("zwykła notatka nie rusza sekcji klienta", () => {
    const n = note({});
    expect(applyInsightEdit([n], n.id, { text: "x" }).client).toBeUndefined();
    expect(removeInsight([n], n.id).client).toBeUndefined();
  });
});

describe("widok kolumn", () => {
  it("kolumna pokazuje notatki swojego źródła, bez „do dopytania”, z filtrem widoczności", () => {
    const notes = [
      note({ id: "a" }),
      note({ id: "b", audience: "candidate" }),
      note({ id: "c", source: "consultant" }),
      note({ id: "d", topic: "ask_client" }),
    ];
    expect(visibleInsights(notes, "client", "all").map((n) => n.id)).toEqual(["a", "b"]);
    expect(visibleInsights(notes, "client", "candidate").map((n) => n.id)).toEqual(["b"]);
    expect(askClientItems(notes).map((n) => n.id)).toEqual(["d"]);
  });

  it("nowa notatka jest „tylko dla zespołu” i ma tymczasowe id `new-…`", () => {
    const n = newInsight("consultant", "team");
    expect(n.audience).toBe("team");
    expect(n.id.startsWith("new-")).toBe(true);
    expect(n.editable).toBe(true);
  });
});
