/**
 * Jarvis 2 — pomoc na ekranie: klucz ekranu z adresu, lustra z backendem
 * (lista przewodników, kotwice `data-help`, kody odmów), licznik odmów
 * i budżet dymków.
 */
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ERROR_EXPLAINERS } from "@/lib/help/error-explainers";
import {
  JARVIS_STUCK_EVENT,
  STUCK_WINDOW_MS,
  recordRefusal,
  refusalCode,
  resetRefusals,
} from "@/lib/help/refusal-tracker";
import { SCREEN_KEYS, screenKeyFor } from "@/lib/help/screen-key";
import {
  DAILY_UNSOLICITED_BUBBLES,
  canShowUnsolicited,
  markScreenSeen,
  recordUnsolicited,
  resetScreenSeen,
  screenSeen,
} from "@/lib/jarvis/bubble-budget";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../../../..");
const SRC = join(REPO, "frontend", "src");
const GUIDES_PATH = join(REPO, "backend", "app", "data", "screen_guides", "guides.json");

interface GuideJson {
  key: string;
  anchors: { id: string }[];
}
const guides: GuideJson[] = JSON.parse(readFileSync(GUIDES_PATH, "utf8"));

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "__tests__" || entry.name === "node_modules" || entry.name === "preview") continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) {
      out.push(full);
    }
  }
  return out;
}

function withoutComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1").replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
}

describe("klucz ekranu z adresu", () => {
  it.each([
    ["/jobs", "", "jobs.list"],
    ["/jobs/12", "", "jobs.board"],
    ["/jobs/12", "?tab=board", "jobs.board"],
    ["/jobs/12", "?tab=champion", "job.champion"],
    ["/jobs/12", "?tab=champion-profile", "job.champion"],
    ["/jobs/12", "?tab=people&seg=proposals", "jobs.proposals"],
    ["/jobs/12", "?tab=people&seg=shortlist", "jobs.proposals"],
    ["/jobs/12", "?tab=ai-matching", "jobs.proposals"],
    ["/jobs/12", "?tab=pipeline", "jobs.board"],
    ["/jobs/12", "?candidate=5&panel=cv", "jobs.person"],
    ["/candidates", "?mode=request", "candidates.list"],
    ["/talent-radar", "", "candidates.list"],
    ["/candidates/7", "?tab=activity", "candidate.profile"],
    ["/calendar", "?view=week", "calendar"],
    ["/clients/3", "?tab=zamowienia", "client.orders"],
    ["/clients/3", "?tab=profil", null],
    ["/contracts", "?view=order-mail", "contracts.order_mail"],
    ["/contracts", "", null],
    ["/contracts/b2b-generator", "", "contracts.b2b_generator"],
    ["/finance", "?view=order-changes", "finance"],
    ["/order-mail", "", null],
    ["/jobs/new", "", null],
    ["/dashboard", "", null],
  ])("%s%s → %s", (path, search, expected) => {
    expect(screenKeyFor(path, search)).toBe(expected);
  });

  it("zna dokładnie te ekrany, które mają przewodnik w backendzie", () => {
    expect([...SCREEN_KEYS].sort()).toEqual(guides.map((g) => g.key).sort());
    const init = readFileSync(join(REPO, "backend", "app", "data", "screen_guides", "__init__.py"), "utf8");
    const block = /SCREEN_KEYS: tuple\[str, \.\.\.\] = \(([\s\S]*?)\)/.exec(init)?.[1] ?? "";
    const backend = [...block.matchAll(/"([a-z0-9_.]+)"/g)].map((m) => m[1]).sort();
    expect([...SCREEN_KEYS].sort()).toEqual(backend);
  });
});

describe("kotwice data-help", () => {
  const sources = sourceFiles(SRC).map((f) => withoutComments(readFileSync(f, "utf8"))).join("\n");
  const inCode = new Set([...sources.matchAll(/data-help="([a-z0-9][a-z0-9_.-]+)"/g)].map((m) => m[1]));
  const declared = new Set(guides.flatMap((g) => g.anchors.map((a) => a.id)));

  it("każda kotwica przewodnika jest przypięta do elementu na ekranie", () => {
    const missing = [...declared].filter((id) => !inCode.has(id));
    expect(missing, "kotwica bez data-help w kodzie — Jarvis wskazałby nic").toEqual([]);
  });

  it("każdy data-help w kodzie jest opisany w przewodniku", () => {
    const orphans = [...inCode].filter((id) => !declared.has(id));
    expect(orphans, "data-help spoza przewodników — dopisz kotwicę albo usuń atrybut").toEqual([]);
  });
});

describe("wyjaśnienia odmów", () => {
  it("każdy kod istnieje w backendzie", () => {
    const backendDir = join(REPO, "backend", "app");
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".py")) files.push(full);
      }
    };
    walk(backendDir);
    const backend = files.map((f) => readFileSync(f, "utf8")).join("\n");
    const missing = Object.keys(ERROR_EXPLAINERS).filter((code) => !backend.includes(`"${code}"`));
    expect(missing).toEqual([]);
  });

  it("czyta kod z detail.code albo detail.reason, tylko dla odmów", () => {
    expect(refusalCode(409, { detail: { code: "DEBRIEF_REQUIRED" } })).toBe("DEBRIEF_REQUIRED");
    expect(refusalCode(422, { detail: { reason: "b2b_end_date_requires_termination" } })).toBe(
      "b2b_end_date_requires_termination",
    );
    expect(refusalCode(500, { detail: { code: "X" } })).toBeNull();
    expect(refusalCode(409, { detail: "tekst" })).toBeNull();
    expect(refusalCode(422, { detail: [{ loc: ["body"] }] })).toBeNull();
  });
});

describe("licznik odmów", () => {
  beforeEach(() => resetRefusals());

  it("trzecia taka sama odmowa w 2 minuty budzi Jarvisa", () => {
    const listener = vi.fn();
    window.addEventListener(JARVIS_STUCK_EVENT, listener);
    expect(recordRefusal("DEBRIEF_REQUIRED", 0)).toBe(false);
    expect(recordRefusal("DEBRIEF_REQUIRED", 1000)).toBe(false);
    expect(recordRefusal("DEBRIEF_REQUIRED", 2000)).toBe(true);
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(JARVIS_STUCK_EVENT, listener);
  });

  it("stare odmowy wypadają z okna, nieznany kod nic nie robi", () => {
    recordRefusal("CANDIDATE_CLAIMED", 0);
    recordRefusal("CANDIDATE_CLAIMED", 1);
    expect(recordRefusal("CANDIDATE_CLAIMED", STUCK_WINDOW_MS + 10)).toBe(false);
    expect(recordRefusal("NIEZNANY", 0)).toBe(false);
    expect(recordRefusal("NIEZNANY", 1)).toBe(false);
    expect(recordRefusal("NIEZNANY", 2)).toBe(false);
  });
});

describe("budżet dymków", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => window.localStorage.clear());

  it("najwyżej trzy nieproszone dymki dziennie, od nowa następnego dnia", () => {
    for (let i = 0; i < DAILY_UNSOLICITED_BUBBLES; i += 1) {
      expect(canShowUnsolicited(1, "2026-09-23")).toBe(true);
      recordUnsolicited(1, "2026-09-23");
    }
    expect(canShowUnsolicited(1, "2026-09-23")).toBe(false);
    expect(canShowUnsolicited(2, "2026-09-23")).toBe(true);
    expect(canShowUnsolicited(1, "2026-09-24")).toBe(true);
  });

  it("dymek ekranu pokazuje się raz, reset przywraca wszystkie", () => {
    expect(screenSeen(1, "jobs.board")).toBe(false);
    markScreenSeen(1, "jobs.board");
    expect(screenSeen(1, "jobs.board")).toBe(true);
    expect(screenSeen(1, "calendar")).toBe(false);
    resetScreenSeen(1);
    expect(screenSeen(1, "jobs.board")).toBe(false);
  });
});
