import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { api, championApi, championSuggestionsApi } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

/**
 * Strażnik klasy defektu: wywołanie, po którego drugiej stronie liczy model,
 * na 30-sekundowym suficie dla CRUD-a.
 *
 * Skutek za niskiego timeoutu jest gorszy niż czekanie (patrz docstring
 * `lib/http-timeouts.ts`): przeglądarka zrywa połączenie, backend kończy
 * generację i PŁACI za nią, a użytkownik widzi generyczny błąd i klika
 * jeszcze raz — czyli mnoży ten koszt. W champion-drafcie dochodzi drugi
 * skutek: kwota `AIFeatureKey.champion_draft` jest commitowana PRZED
 * wywołaniem modelu, więc każde przerwanie pali limit, a profil, który
 * backend faktycznie zapisał, jest niewidoczny do ręcznego przeładowania.
 *
 * Dwie warstwy, bo żadna sama nie wystarcza:
 *  1. zachowanie — efektywny timeout NA PRAWDZIWEJ instancji `api` (test
 *     mockujący `@/lib/api` przechodzi obok: o timeoucie decyduje axios);
 *  2. skan źródeł — RODZINY ścieżek, których każde wywołanie musi nieść
 *     override, żeby piąte wejście do champion-draftu nie dało się dodać po
 *     cichu bez niego (cztery istniejące przez rok go nie miały).
 */

const SRC_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Efektywny `timeout` widziany przez adapter — czyli to, co realnie obowiązuje. */
function captureTimeouts(): {
  timeouts: number[];
  restore: () => void;
} {
  const previous = api.defaults.adapter;
  const timeouts: number[] = [];
  api.defaults.adapter = async (config) => {
    timeouts.push(config.timeout ?? 0);
    return {
      data: {},
      status: 200,
      statusText: "OK",
      headers: {},
      config,
      request: {},
    };
  };
  return {
    timeouts,
    restore: () => {
      api.defaults.adapter = previous;
    },
  };
}

describe("api — efektywny timeout wywołań champion-draft", () => {
  let restore: (() => void) | null = null;

  afterEach(() => {
    restore?.();
    restore = null;
  });

  it("cztery wejścia champion-draft jadą na suficie dla LLM, nie na CRUD-owym", async () => {
    const captured = captureTimeouts();
    restore = captured.restore;

    await championApi.setBriefing(1, 2);
    await championApi.generateRecommendedSearches(1);
    await championSuggestionsApi.generateFromJd(1, "opis");
    await championSuggestionsApi.generateFromHistory(1, { topK: 5 });

    expect(captured.timeouts).toEqual([
      SLOW_ENDPOINT_TIMEOUT_MS,
      SLOW_ENDPOINT_TIMEOUT_MS,
      SLOW_ENDPOINT_TIMEOUT_MS,
      SLOW_ENDPOINT_TIMEOUT_MS,
    ]);
  });

  it("zwykły CRUD zostaje na domyślnym suficie instancji", async () => {
    const captured = captureTimeouts();
    restore = captured.restore;

    await championApi.get(1);

    expect(captured.timeouts).toEqual([30_000]);
    expect(captured.timeouts[0]).toBeLessThan(SLOW_ENDPOINT_TIMEOUT_MS);
  });
});

/**
 * Rodziny ścieżek, dla których backend woła model SYNCHRONICZNIE w requeście.
 * Lista celowo opisuje wzorce, nie pojedyncze URL-e — nowe rodzeństwo
 * (`generate-from-…`) wpada pod strażnika samo.
 */
const LLM_PATH_PATTERNS: ReadonlyArray<{ name: string; re: RegExp }> = [
  {
    name: "champion-draft",
    // `briefing` zakotwiczone na końcu segmentu — bratni GET
    // `briefing/audio-url` zwraca podpisany URL i nie dotyka modelu.
    re: /champion-profile\/(briefing(?![\w/-])|generate-from-[\w-]+|recommended-searches\/generate)/,
  },
  { name: "ai/generate-*", re: /\/api\/ai\/generate-/ },
  { name: "prep-kit", re: /\/api\/prep-kit\/generate/ },
  { name: "refresh-criteria", re: /\/refresh-criteria/ },
  { name: "recompute-scores", re: /\/recompute-scores/ },
  { name: "cv-generator/classify", re: /\/api\/cv-generator\/classify-technologies/ },
];

/**
 * Zamienia KOMENTARZE na spacje tej samej długości (indeksy zostają), literały
 * tekstowe zostawia — URL-e muszą przetrwać, a `SLOW_ENDPOINT_TIMEOUT_MS`
 * wspomniany w komentarzu nie jest override'em.
 */
function blankComments(source: string): string {
  const out = source.split("");
  const blank = (from: number, to: number) => {
    for (let k = from; k < to && k < out.length; k++) {
      if (out[k] !== "\n") out[k] = " ";
    }
  };
  let i = 0;
  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];
    if (ch === "/" && next === "/") {
      let j = i + 2;
      while (j < source.length && source[j] !== "\n") j++;
      blank(i, j);
      i = j;
      continue;
    }
    if (ch === "/" && next === "*") {
      let j = i + 2;
      while (j < source.length && !(source[j] === "*" && source[j + 1] === "/")) j++;
      blank(i, Math.min(j + 2, source.length));
      i = j + 2;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      // Literał przeskakujemy w CAŁOŚCI, żeby `//` w URL-u nie udawało komentarza.
      let j = i + 1;
      while (j < source.length) {
        if (source[j] === "\\") {
          j += 2;
          continue;
        }
        if (source[j] === ch) break;
        j++;
      }
      i = j + 1;
      continue;
    }
    i++;
  }
  return out.join("");
}

/** Indeks domykającego nawiasu dla `open` stojącego na pozycji `from`, albo -1. */
function matchBalanced(source: string, from: number, open: string, close: string): number {
  if (source[from] !== open) return -1;
  let depth = 0;
  let inString: string | null = null;
  for (let k = from; k < source.length; k++) {
    const ch = source[k];
    if (inString) {
      if (ch === "\\") k++;
      else if (ch === inString) inString = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") inString = ch;
    else if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) return k;
    }
  }
  return -1;
}

function skipWhitespace(source: string, from: number): number {
  let i = from;
  while (i < source.length && /\s/.test(source[i])) i++;
  return i;
}

interface LlmCall {
  line: number;
  family: string;
  hasOverride: boolean;
}

function inspectSource(source: string): LlmCall[] {
  const code = blankComments(source);
  const found: LlmCall[] = [];
  const callRe = /\bapi\s*\.\s*(?:post|put|patch|get)\b/g;
  let m: RegExpExecArray | null;
  while ((m = callRe.exec(code)) !== null) {
    let i = skipWhitespace(code, m.index + m[0].length);
    if (code[i] === "<") {
      const genericEnd = matchBalanced(code, i, "<", ">");
      if (genericEnd < 0) continue;
      i = skipWhitespace(code, genericEnd + 1);
    }
    if (code[i] !== "(") continue;
    const close = matchBalanced(code, i, "(", ")");
    if (close < 0) continue;

    const args = code.slice(i + 1, close);
    const family = LLM_PATH_PATTERNS.find((p) => p.re.test(args));
    if (!family) continue;

    found.push({
      family: family.name,
      hasOverride: args.includes("SLOW_ENDPOINT_TIMEOUT_MS"),
      line: source.slice(0, m.index).split("\n").length,
    });
  }
  return found;
}

function listSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__" || entry.name === "test") continue;
      listSourceFiles(full, out);
    } else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

describe("detektor wywołań LLM bez override'u timeoutu", () => {
  it("łapie brak override'u i przepuszcza poprawne", () => {
    const broken = "api.post(`/api/jobs/${id}/champion-profile/briefing`, { note_id: n });";
    expect(inspectSource(broken).map((c) => c.hasOverride)).toEqual([false]);

    const correct = [
      "api.post(`/api/jobs/${id}/champion-profile/generate-from-history`, body, {",
      "  timeout: SLOW_ENDPOINT_TIMEOUT_MS,",
      "});",
    ].join("\n");
    expect(inspectSource(correct).map((c) => c.hasOverride)).toEqual([true]);

    // Override wspomniany w KOMENTARZU nie jest override'em.
    const commentOnly = [
      "// timeout: SLOW_ENDPOINT_TIMEOUT_MS",
      "api.post(`/api/ai/generate-job`, data);",
    ].join("\n");
    expect(inspectSource(commentOnly).map((c) => c.hasOverride)).toEqual([false]);

    // Ścieżka spoza rodzin nie jest przedmiotem tego kontraktu.
    expect(inspectSource("api.get(`/api/jobs/${id}/champion-profile`);")).toEqual([]);
  });
});

describe("kontrakt źródeł: wywołania LLM zawsze z SLOW_ENDPOINT_TIMEOUT_MS", () => {
  const inspected = listSourceFiles(SRC_DIR).flatMap((file) =>
    inspectSource(fs.readFileSync(file, "utf8")).map((call) => ({
      ...call,
      where: `${path.relative(SRC_DIR, file)}:${call.line}`,
    })),
  );

  it("widzi realne wywołania (skan nie jest pusty)", () => {
    // Bez tej asercji literówka w regexie dałaby zielonego strażnika na zawsze.
    expect(inspected.length).toBeGreaterThanOrEqual(8);
  });

  it("żadne wywołanie z rodzin LLM nie idzie na domyślnym suficie", () => {
    const offenders = inspected
      .filter((call) => !call.hasOverride)
      .map((call) => `${call.where} — ${call.family}`);
    expect(offenders).toEqual([]);
  });
});
