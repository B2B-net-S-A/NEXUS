/**
 * Strażnik: `response.data.detail` nie trafia do UI z założeniem, że to tekst.
 *
 * FastAPI zwraca `detail` jako string, obiekt (`{message, ...}`) albo TABLICĘ
 * błędów walidacji `{type, loc, msg, input}`. Wzorzec `data?.detail ?? "…"`
 * (albo rzutowanie `data?: { detail?: string }` i odczyt w dwóch krokach)
 * przepuszczał tablicę do JSX — React #31 i ekran „Coś poszło nie tak" na
 * całą stronę (odbiór #1549, lista kandydatów po 422 za NUL w wyszukiwaniu).
 * 15.09.2026 takich miejsc było ponad 70; wszystkie idą teraz przez
 * `apiErrorMessage(error, fallback)` z `@/lib/api-error`.
 *
 * Test czyta ŹRÓDŁA ze znormalizowanymi białymi znakami, więc łapie też
 * warianty rozbite na kilka linii. Bezpieczne odczyty strukturalne
 * (`detail?: unknown` + sprawdzenie typu) go nie dotyczą.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

const PATTERNS: ReadonlyArray<{ name: string; re: RegExp }> = [
  {
    name: "`data?.detail ??` / `||` — fallback that lets an object through",
    re: /data\s*\??\s*\.\s*detail\s*(?:\?\?|\|\|)/g,
  },
  {
    name: "`data?: { detail?: string }` — cast assuming a string detail",
    re: /data\s*\??\s*:\s*\{\s*detail\s*\??\s*:\s*string\b/g,
  },
  {
    name: "`AxiosError<{ detail?: string }>` — cast assuming a string detail",
    re: /AxiosError\s*<\s*\{\s*detail\s*\??\s*:\s*string\s*;?\s*\}\s*>/g,
  },
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "__tests__" || entry.name === "node_modules" ? [] : sourceFiles(path);
    }
    const isSource = /\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$|\.d\.ts$/.test(entry.name);
    return isSource ? [path] : [];
  });
}

function violations(text: string): string[] {
  return PATTERNS.flatMap(({ name, re }) =>
    [...text.matchAll(new RegExp(re.source, "g"))].map(
      (match) => `line ${text.slice(0, match.index).split("\n").length}: ${name}`,
    ),
  );
}

describe("API error detail is never assumed to be a string", () => {
  it("routes every read through apiErrorMessage", () => {
    const offenders = sourceFiles(SRC).flatMap((file) =>
      violations(readFileSync(file, "utf8")).map((v) => `${relative(SRC, file)} ${v}`),
    );
    expect(
      offenders,
      "Use apiErrorMessage(error, fallback) from @/lib/api-error: FastAPI detail can be an array or object.",
    ).toEqual([]);
  });

  it("still recognises every guarded shape (no silently dead guard)", () => {
    const bad = [
      'setError(e?.response?.data?.detail || "Błąd");',
      '(e as { response?: { data?: { detail?: string } } })?.response?.data\n  ?.detail ?? "Błąd"',
      "const resp = (err as { response?: { data?: { detail?: string } } }).response;",
      "const axiosError = error as AxiosError<{ detail?: string }>;",
    ];
    for (const snippet of bad) expect(violations(snippet), snippet).not.toEqual([]);

    const safe = [
      'setError(apiErrorMessage(e, "Błąd"));',
      "const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;",
      'if (typeof detail === "string") return detail;',
    ];
    for (const snippet of safe) expect(violations(snippet), snippet).toEqual([]);
  });
});
