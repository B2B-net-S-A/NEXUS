import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { SCENE_COMPONENT_IDS } from "../CareerScene";
import {
  CAREER_SCENE_IDS,
  ctaLabel,
  leftoverNice,
  methodName,
  processSteps,
  sceneItems,
  scoreNote,
  toggleInOrder,
} from "../model";

describe("sceny ról — model wyniku", () => {
  it("pozycje: najpierw wymagania, potem mile widziane, najwyżej pięć", () => {
    const items = sceneItems(
      [
        { name: "Java", note: " 5 lat " },
        { name: "  ", note: "pusta nazwa odpada" },
        { name: "Kafka", note: null },
      ],
      ["AWS", "", "Docker", "Go", "Rust"],
    );
    expect(items.map((i) => [i.name, i.kind])).toEqual([
      ["Java", "must"],
      ["Kafka", "must"],
      ["AWS", "nice"],
      ["Docker", "nice"],
      ["Go", "nice"],
    ]);
    expect(items[0].note).toBe("5 lat");
    expect(new Set(items.map((i) => i.key)).size).toBe(5);
    expect(leftoverNice(["AWS", "", "Docker", "Go", "Rust"], items)).toEqual(["Rust"]);
  });

  it("więcej niż pięć wymagań — scena bierze pierwsze pięć, mile widziane zostają ozdobą", () => {
    const must = Array.from({ length: 7 }, (_, i) => ({ name: `W${i}`, note: null }));
    const items = sceneItems(must, ["AWS"]);
    expect(items).toHaveLength(5);
    expect(items.every((i) => i.kind === "must")).toBe(true);
    expect(leftoverNice(["AWS"], items)).toEqual(["AWS"]);
  });

  it("brak wymagań i mile widzianych = brak sceny", () => {
    expect(sceneItems([], [])).toEqual([]);
  });

  it("zaznaczanie trzyma kolejność klikania i odznacza drugim kliknięciem", () => {
    let order: number[] = [];
    order = toggleInOrder(order, 3);
    order = toggleInOrder(order, 0);
    order = toggleInOrder(order, 2);
    expect(order).toEqual([3, 0, 2]);
    expect(toggleInOrder(order, 0)).toEqual([3, 2]);
  });

  it("poniżej kompletu zawsze „Nie musisz mieć wszystkiego — aplikuj”, także przy zerze", () => {
    expect(scoreNote(0, 5)).toBe("Nie musisz mieć wszystkiego — aplikuj.");
    expect(scoreNote(4, 5)).toBe("Nie musisz mieć wszystkiego — aplikuj.");
    expect(scoreNote(5, 5)).toBe("Pełne dopasowanie — czekamy na Ciebie.");
    expect(scoreNote(3, 3)).toBe("Pełne dopasowanie — czekamy na Ciebie.");
  });

  it("przycisk „Aplikuj” ma wynik, gdy coś zaznaczono", () => {
    expect(ctaLabel(0, 5)).toBe("Aplikuj — 2 minuty");
    expect(ctaLabel(2, 5)).toBe("Aplikuj — masz 2 z 5");
    expect(ctaLabel(3, 3)).toBe("Aplikuj — masz 3 z 3");
  });

  it("nazwa wymagania jako metoda diagramu sekwencji", () => {
    expect(methodName("Spring Boot")).toBe("springBoot");
    expect(methodName("SQL")).toBe("sql");
    expect(methodName("Język angielski B2")).toBe("jezykAngielskiB2");
    expect(methodName("17+ lat")).toBe("_17Lat");
    expect(methodName("—")).toBe("wymaganie");
  });

  it("kroki procesu jak w ProcessSteps", () => {
    expect(processSteps("Marta", "B2B").map((s) => s.title)).toEqual([
      "rozmowa z Martą",
      "weryfikacja techniczna",
      "spotkanie z zespołem",
      "decyzja i start",
    ]);
    expect(processSteps("Marta", null)[3].note).toBe("umowa i wdrożenie");
  });

  it("lista scen w modelu zgadza się z komponentami", () => {
    expect([...SCENE_COMPONENT_IDS].sort()).toEqual([...CAREER_SCENE_IDS].sort());
  });

  it("scenes.css: każdy kolor przez zmienną --kr-*", () => {
    const css = readFileSync(join(__dirname, "..", "scenes.css"), "utf8");
    expect(css.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
    expect(css.match(/rgba?\(/g)).toBeNull();
  });
});
