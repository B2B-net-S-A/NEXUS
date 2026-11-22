// Poranna porcja nowości (decyzja Artura 18.11.2026): kroki drobiazgu,
// przepuszczanie ekranów przy blokadzie i tryb ćwiczebny dla przeklikania.

import { afterEach, describe, expect, it } from "vitest";

import { DAILY_PATH, dailyAllows, dailyBlocks, minutesFor, withSteps } from "@/lib/novelties/daily";
import type { Novelty } from "@/lib/novelties/logic";
import { enterPoligon, isNoveltyPractice, isPoligonActive } from "@/lib/poligon/mode";

function novelty(overrides: Partial<Novelty> = {}): Novelty {
  return {
    id: "drobiazg",
    title: "Drobiazg",
    why: "Po co",
    tier: "dot",
    shipped_on: "2026-11-17",
    where: "Rekrutacja",
    href: "/jobs",
    practice_href: null,
    dot_anchor: "jobs.list.twin-pick",
    used_anchor: null,
    path_prefix: null,
    steps: [],
    done: false,
    start: false,
    completed_via: null,
    show_card: false,
    required_now: false,
    can_postpone: false,
    ...overrides,
  };
}

describe("porcja dnia", () => {
  it("drobiazg bez kroków dostaje jeden krok „Rozumiem” na swojej kotwicy", () => {
    const [step] = withSteps(novelty()).steps;
    expect(step).toEqual({ anchor: "jobs.list.twin-pick", text: "Drobiazg", hint: "Po co", ack: true });
  });

  it("wpis z krokami zostaje, jak jest", () => {
    const steps = [
      { anchor: "a.one", text: "1", hint: "h", ack: false },
      { anchor: "a.two", text: "2", hint: "h", ack: false },
    ];
    expect(withSteps(novelty({ steps })).steps).toBe(steps);
  });

  it("zatrzymana osoba widzi tylko listę porcji, chyba że właśnie przeklikuje", () => {
    expect(dailyAllows(DAILY_PATH, false)).toBe(true);
    expect(dailyAllows("/jobs", false)).toBe(false);
    expect(dailyAllows("/dashboard", false)).toBe(false);
    expect(dailyAllows("/jobs/990001", true)).toBe(true);
  });

  it("szacunek czasu liczy też jedyny krok drobiazgu", () => {
    expect(minutesFor([novelty(), novelty({ id: "b" }), novelty({ id: "c" })])).toBe(2);
    expect(minutesFor([])).toBe(1);
  });
});

describe("tryb ćwiczebny dla przeklikania nowości", () => {
  afterEach(() => window.sessionStorage.clear());

  it("porcja włącza ten sam tryb co Poligon, ale z własnym oznaczeniem", () => {
    window.sessionStorage.setItem("nexus.poligon", "novelty");
    expect(isPoligonActive()).toBe(true);
    expect(isNoveltyPractice()).toBe(true);
    window.sessionStorage.setItem("nexus.poligon", "1");
    expect(isPoligonActive()).toBe(true);
    expect(isNoveltyPractice()).toBe(false);
    window.sessionStorage.removeItem("nexus.poligon");
    expect(isPoligonActive()).toBe(false);
  });

  it("enterPoligon z celem „novelty” zapisuje oznaczenie przed przejściem", () => {
    const assign = window.location.assign;
    const visited: string[] = [];
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, assign: (href: string) => visited.push(href) },
    });
    try {
      enterPoligon("/jobs/990001", "novelty");
      expect(isNoveltyPractice()).toBe(true);
      expect(visited).toEqual(["/jobs/990001"]);
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { ...window.location, assign },
      });
    }
  });
});

describe("bramka porcji a Start i Poligon", () => {
  const base = {
    dailyEnforced: true,
    start: { enforced: false },
    poligon: false,
    pathname: "/jobs",
    touringBatch: false,
  };

  it("zatrzymuje na liście porcji, gdy Start jest za osobą", () => {
    expect(dailyBlocks(base)).toBe(true);
    expect(dailyBlocks({ ...base, pathname: DAILY_PATH })).toBe(false);
  });

  // Recenzja 18.11: Start (albo Poligon nowej osoby) wpuszcza na `/poligon`
  // i `/start`, a porcja odsyłała stamtąd na `/nowosci-dnia` — pętla przekierowań.
  it("czeka, dopóki Start albo Poligon blokuje osobę — na każdym ekranie", () => {
    for (const pathname of ["/poligon", "/start", "/dashboard", "/jobs"])
      expect(dailyBlocks({ ...base, pathname, start: { enforced: true } }), pathname).toBe(false);
  });

  // 19.11.2026: Rada nadzorcza wchodzi tylko na swoje ekrany (middleware),
  // więc `/nowosci-dnia` odbijało na `/rada`, a bramka nie pokazywała `/rada` —
  // pusty ekran. Rada nie dostaje porcji nowości zespołu.
  it("nie zatrzymuje Rady nadzorczej", () => {
    expect(dailyBlocks({ ...base, pathname: "/rada", boardOnly: true })).toBe(false);
    expect(dailyBlocks({ ...base, pathname: "/rada" })).toBe(true);
  });

  it("nie blokuje, zanim przyjdzie stan Startu, ani na Poligonie i w panelu wyłącznika", () => {
    expect(dailyBlocks({ ...base, start: null })).toBe(false);
    expect(dailyBlocks({ ...base, poligon: true })).toBe(false);
    expect(dailyBlocks({ ...base, pathname: "/settings/nowosci" })).toBe(false);
    expect(dailyBlocks({ ...base, dailyEnforced: false })).toBe(false);
  });
});
