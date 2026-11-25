import { beforeEach, describe, expect, it, vi } from "vitest";

// Poligon 25.11.2026: ekran pokazywał „27 z 27 · Poligon zaliczony”, serwer miał
// 26 (zapis jednego ćwiczenia w tle się nie udał) i blokada nie przepuszczała.

const post = vi.hoisted(() => vi.fn(async () => ({ data: null })));
vi.mock("@/lib/api", () => ({ api: { post } }));

import type { Exercise } from "../exercises";
import { markDone, resendMissing } from "../progress";

const path = [{ id: "lista-zakres" }, { id: "baza-lista" }, { id: "baza-szukaj" }] as Exercise[];

beforeEach(() => {
  post.mockClear();
  window.localStorage.clear();
});

describe("postęp Poligonu", () => {
  it("dosyła serwerowi ćwiczenia zaliczone w przeglądarce, których serwer nie zna — raz", () => {
    window.localStorage.setItem("nexus.poligon.done", JSON.stringify(["lista-zakres", "baza-lista"]));
    expect(resendMissing(["poligon-lista-zakres"], path)).toEqual(["baza-lista"]);
    expect(post).toHaveBeenCalledWith("/api/novelties/poligon-baza-lista/events", { event: "used" });
    expect(resendMissing(["poligon-lista-zakres"], path)).toEqual([]);
  });

  it("„Coś nie działa” zalicza ćwiczenie zdarzeniem `broken`", () => {
    markDone("baza-szukaj", { broken: true });
    expect(post).toHaveBeenCalledWith("/api/novelties/poligon-baza-szukaj/events", { event: "broken" });
    expect(JSON.parse(window.localStorage.getItem("nexus.poligon.done") ?? "[]")).toContain("baza-szukaj");
  });
});
