/**
 * Nowości do przeklikania: kotwice `data-tour` w obie strony z rejestrem
 * backendu i logika kropki, karty, okna zmiany procesu i kroków.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  acknowledgeStep,
  advanceTour,
  cardCandidate,
  dotNovelties,
  eventForClick,
  pendingCount,
  placeBeside,
  requiredForPath,
  startAllows,
  withinAnchor,
  type Novelty,
} from "@/lib/novelties/logic";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../../../..");
const SRC = join(REPO, "frontend", "src");
const REGISTRY = join(
  REPO,
  "backend",
  "app",
  "data",
  "novelties",
  "novelties.json",
);
// Start w NEXUSIE (30.10.2026) chodzi też po kotwicach `data-help` przewodników.
const START_REGISTRY = join(REGISTRY, "..", "start.json");

interface RegistryEntry {
  id: string;
  dot_anchor: string;
  used_anchor?: string | null;
  steps?: { anchor: string }[];
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === "__tests__" || name === "node_modules") return [];
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx|ts)$/.test(name) ? [path] : [];
  });
}

function anchorsInSource(attribute = "data-tour"): Set<string> {
  const found = new Set<string>();
  for (const file of sourceFiles(SRC)) {
    // Kotwica stoi dosłownie w linii z `data-tour` (także w `cond ? "id" : undefined`);
    // id zawsze ma kropkę („ekran.element”), więc inne napisy w linii się nie liczą.
    for (const line of readFileSync(file, "utf8").split("\n")) {
      if (!line.includes(`${attribute}=`)) continue;
      for (const m of line.matchAll(
        /"([a-z0-9][a-z0-9_-]*(?:\.[a-z0-9_-]+)+)"/g,
      ))
        found.add(m[1]);
    }
  }
  return found;
}

function anchorsOf(registry: RegistryEntry[]): Set<string> {
  return new Set(
    registry
      .flatMap((n) => [
        n.dot_anchor,
        n.used_anchor ?? "",
        ...(n.steps ?? []).map((s) => s.anchor),
      ])
      .filter(Boolean),
  );
}

describe("kotwice nowości", () => {
  const registry: RegistryEntry[] = JSON.parse(readFileSync(REGISTRY, "utf8"));
  const start: RegistryEntry[] = JSON.parse(readFileSync(START_REGISTRY, "utf8"));
  const inRegistry = new Set([...anchorsOf(registry), ...anchorsOf(start)]);
  const inSource = anchorsInSource();
  const inHelp = anchorsInSource("data-help");

  it("każda kotwica z rejestru stoi na elemencie we froncie", () => {
    expect([...anchorsOf(registry)].filter((a) => !inSource.has(a))).toEqual([]);
  });

  it("każda kotwica Startu stoi na elemencie (data-tour albo data-help)", () => {
    expect(
      [...anchorsOf(start)].filter((a) => !inSource.has(a) && !inHelp.has(a)),
    ).toEqual([]);
  });

  it("każde data-tour we froncie należy do nowości z rejestru (bez martwych kotwic)", () => {
    expect([...inSource].filter((a) => !inRegistry.has(a))).toEqual([]);
  });
});

function novelty(overrides: Partial<Novelty> = {}): Novelty {
  return {
    id: "wybieram",
    title: "Wybieram",
    why: "Po co",
    tier: "tour",
    shipped_on: "2026-10-28",
    where: "Rekrutacja",
    href: "/jobs",
    dot_anchor: "jobs.sources.search",
    used_anchor: "candidate.profile.pick",
    path_prefix: null,
    steps: [
      { anchor: "jobs.sources.search", text: "1", hint: "h", ack: false },
      { anchor: "candidate.profile.pick", text: "2", hint: "h", ack: false },
    ],
    done: false,
    start: false,
    completed_via: null,
    show_card: true,
    required_now: false,
    can_postpone: false,
    ...overrides,
  };
}

function element(anchor: string): HTMLElement {
  const outer = document.createElement("button");
  outer.setAttribute("data-tour", anchor);
  const inner = document.createElement("span");
  outer.appendChild(inner);
  return inner;
}

describe("logika nowości", () => {
  it("licznik ✦ pomija drobiazgi i zaliczone", () => {
    expect(
      pendingCount([
        novelty(),
        novelty({ id: "b", tier: "dot" }),
        novelty({ id: "c", done: true }),
      ]),
    ).toBe(1);
  });

  it("karta tylko przy widocznej kropce nowości do przeklikania", () => {
    const list = [novelty({ id: "proc", tier: "process" }), novelty()];
    expect(cardCandidate(list, new Set(["jobs.sources.search"]))?.id).toBe(
      "wybieram",
    );
    expect(cardCandidate(list, new Set())).toBeNull();
    expect(
      cardCandidate(
        [novelty({ show_card: false })],
        new Set(["jobs.sources.search"]),
      ),
    ).toBeNull();
  });

  it("okno zmiany procesu tylko na swoim ekranie i tylko gdy wymagane", () => {
    const proc = novelty({
      id: "umowa",
      tier: "process",
      path_prefix: "/contracts",
      required_now: true,
    });
    expect(requiredForPath([proc], "/contracts")?.id).toBe("umowa");
    expect(requiredForPath([proc], "/jobs/1")).toBeNull();
    expect(
      requiredForPath([{ ...proc, required_now: false }], "/contracts"),
    ).toBeNull();
  });

  it("nowość do przeklikania wymaga okna na swoim ekranie (href), drobiazg nie (30.10.2026)", () => {
    const tour = novelty({ required_now: true });
    expect(requiredForPath([tour], "/jobs/12")?.id).toBe("wybieram");
    expect(requiredForPath([tour], "/candidates")).toBeNull();
    const dot = novelty({ id: "kropka", tier: "dot", required_now: true });
    expect(requiredForPath([dot], "/jobs")).toBeNull();
    // Ekran „/” to tylko pulpit, nie każdy adres.
    const home = novelty({ id: "pulpit", href: "/", required_now: true });
    expect(requiredForPath([home], "/")?.id).toBe("pulpit");
    expect(requiredForPath([home], "/jobs")).toBeNull();
  });

  it("w trakcie Startu i na liście Startu żadna nowość nie wyskakuje", () => {
    const tour = novelty({ required_now: true });
    const startPending = novelty({ id: "start-x", start: true, done: false });
    expect(requiredForPath([tour, startPending], "/jobs")).toBeNull();
    expect(requiredForPath([tour], "/start")).toBeNull();
    expect(
      requiredForPath([tour, { ...startPending, done: true }], "/jobs")?.id,
    ).toBe("wybieram");
  });

  it("krok przechodzi po kliknięciu w kotwicę (także w jej środek), a ostatni kończy", () => {
    const n = novelty();
    expect(
      advanceTour(n, { noveltyId: n.id, step: 0 }, element("inne")),
    ).toBeNull();
    expect(
      advanceTour(
        n,
        { noveltyId: n.id, step: 0 },
        element("jobs.sources.search"),
      ),
    ).toEqual({
      noveltyId: n.id,
      step: 1,
    });
    expect(
      advanceTour(
        n,
        { noveltyId: n.id, step: 1 },
        element("candidate.profile.pick"),
      ),
    ).toBe("finished");
  });

  it("krok ack nie przechodzi kliknięciem, tylko „Rozumiem”", () => {
    const n = novelty({
      steps: [
        { anchor: "a.one", text: "1", hint: "h", ack: false },
        { anchor: "a.two", text: "2", hint: "h", ack: true },
      ],
    });
    expect(
      advanceTour(n, { noveltyId: n.id, step: 1 }, element("a.two")),
    ).toBeNull();
    expect(acknowledgeStep(n, { noveltyId: n.id, step: 1 })).toBe("finished");
  });

  it("użycie w pracy zalicza nowość, drobiazg — klik w jego element", () => {
    expect(eventForClick(novelty(), element("candidate.profile.pick"))).toBe(
      "used",
    );
    expect(
      eventForClick(novelty({ done: true }), element("candidate.profile.pick")),
    ).toBeNull();
    const dot = novelty({
      tier: "dot",
      dot_anchor: "jarvis.mascot.hide",
      used_anchor: null,
      steps: [],
    });
    expect(eventForClick(dot, element("jarvis.mascot.hide"))).toBe(
      "dot_clicked",
    );
    expect(eventForClick(dot, element("inne"))).toBeNull();
  });
});

describe("miejsce karty kroku", () => {
  const card = { width: 340, height: 170 };
  const viewport = { width: 1280, height: 720 };

  it("pod celem, gdy jest miejsce", () => {
    expect(
      placeBeside(
        { top: 160, left: 820, width: 140, height: 40 },
        card,
        viewport,
      ).top,
    ).toBe(212);
  });

  it("przycisk przy dolnej krawędzi: karta nie zasłania celu i mieści się w oknie", () => {
    for (const target of [
      { top: 630, left: 890, width: 170, height: 50 },
      { top: 560, left: 890, width: 170, height: 150 },
    ]) {
      const at = placeBeside(target, card, viewport);
      const overlaps =
        at.left < target.left + target.width &&
        at.left + card.width > target.left &&
        at.top < target.top + target.height &&
        at.top + card.height > target.top;
      expect(overlaps).toBe(false);
      expect(at.top + card.height).toBeLessThanOrEqual(viewport.height);
    }
  });
});

describe("Start w NEXUSIE", () => {
  it("przeklikanie Startu nie ma kropki ani licznika ✦", () => {
    const list = [novelty(), novelty({ id: "start-x", start: true, show_card: false })];
    expect(dotNovelties(list).map((n) => n.id)).toEqual(["wybieram"]);
    expect(pendingCount(list)).toBe(1);
  });

  it("zatrzymana osoba wchodzi tylko na Start, pulpit i panel z wyłącznikiem", () => {
    for (const path of ["/", "/start", "/dashboard", "/dashboard/delivery-lead", "/settings/nowosci", "/onboarding"])
      expect(startAllows(path, false), path).toBe(true);
    for (const path of ["/jobs", "/jobs/12", "/candidates", "/settings", "/startowy", "/contracts"])
      expect(startAllows(path, false), path).toBe(false);
  });

  it("w trakcie przeklikania Startu każdy ekran jest otwarty", () => {
    expect(startAllows("/jobs/12", true)).toBe(true);
  });

  it("kotwica data-help przewodnika też prowadzi krok", () => {
    const outer = document.createElement("div");
    outer.setAttribute("data-help", "jobs.list.filters");
    const inner = document.createElement("span");
    outer.appendChild(inner);
    expect(withinAnchor(inner, "jobs.list.filters")).toBe(true);
    expect(withinAnchor(inner, "jobs.list.search")).toBe(false);
  });
});
