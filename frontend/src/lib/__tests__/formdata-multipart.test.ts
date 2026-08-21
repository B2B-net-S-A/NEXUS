import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Strażnik klasy defektu, nie dwóch linii.
 *
 * Instancja `api` (`lib/api.ts`) ma domyślne `Content-Type: application/json`.
 * Axios przy tym nagłówku SERIALIZUJE `FormData` do JSON-a, więc plik nigdy
 * nie opuszcza przeglądarki, a FastAPI odpowiada 422 „file Field required".
 * Objaw jest mylący: `curl` na ten sam endpoint działa (omija axiosa), więc
 * defekt wygląda jak problem użytkownika.
 *
 * #1209 naprawił to w radarze — i dwa dni później ten sam błąd wyszedł
 * w odbiorze podpisanej umowy B2B (`signingApi.uploadSigned`) oraz
 * w podglądzie CV (`recommendationsApi.cvUploadPreview`). Naprawa sztuk
 * gwarantuje nawrót, dlatego kontrakt jest sprawdzany na ŹRÓDŁACH: żadne
 * `api.post/put/patch` z ciałem typu `FormData` nie może pójść bez jawnego
 * `multipart/form-data`.
 *
 * Dlaczego skan źródeł, a nie test jednostkowy na kliencie: każdy test, który
 * mockuje `@/lib/api`, przechodzi OBOK zepsutej warstwy — to axios decyduje
 * o serializacji, a mock nie ma czego zepsuć. Zielony byłby przez cały czas
 * trwania defektu.
 *
 * Dlaczego Vitest, a nie skrypt w `package.json`: CI odpala `test:coverage`.
 * `lint:tokens` (precedens skanera źródeł, `scripts/check-candidate-token-usage.mjs`)
 * NIE jest w CI, więc jako skrypt ten strażnik niczego by nie bramkował.
 */

const SRC_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/**
 * Zamienia komentarze i literały tekstowe na spacje tej samej długości.
 * Indeksy zostają nienaruszone, więc pozycję znalezioną w wersji „wyczyszczonej"
 * można wprost odczytać w oryginale. Dzięki temu nawiasy w URL-ach, treść
 * komentarzy i fikstury w testach nie udają kodu.
 */
function blankLiterals(source: string): string {
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
      let j = i + 1;
      while (j < source.length) {
        if (source[j] === "\\") {
          j += 2;
          continue;
        }
        if (source[j] === ch) break;
        j++;
      }
      blank(i, Math.min(j + 1, source.length));
      i = j + 1;
      continue;
    }
    i++;
  }
  return out.join("");
}

function skipWhitespace(source: string, from: number): number {
  let i = from;
  while (i < source.length && /\s/.test(source[i])) i++;
  return i;
}

/** Indeks domykającego nawiasu dla `open` stojącego na pozycji `from`, albo -1. */
function matchBalanced(source: string, from: number, open: string, close: string): number {
  if (source[from] !== open) return -1;
  let depth = 0;
  for (let k = from; k < source.length; k++) {
    if (source[k] === open) depth++;
    else if (source[k] === close) {
      depth--;
      if (depth === 0) return k;
    }
  }
  return -1;
}

/**
 * Nazwy, które w tym pliku NA PEWNO trzymają `FormData`: lokalne `new FormData(…)`
 * oraz parametry/pola zadeklarowane typem `FormData` (tak jedzie `fd` przez
 * helpery w `lib/api/*.ts`). Świadomie konserwatywnie — celem jest zero
 * przeoczeń na realnych uploadach, nie kompletna analiza typów.
 */
function formDataNames(blanked: string): Set<string> {
  const names = new Set<string>();
  for (const m of blanked.matchAll(
    /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*new\s+FormData\s*\(/g,
  )) {
    names.add(m[1]);
  }
  for (const m of blanked.matchAll(/\b([A-Za-z_$][\w$]*)\s*:\s*FormData\b/g)) {
    names.add(m[1]);
  }
  return names;
}

interface Inspected {
  line: number;
  method: string;
  variables: string[];
  hasMultipart: boolean;
}

/** Wszystkie `api.post/put/patch(...)`, których argumentem jest `FormData`. */
function inspectSource(source: string): Inspected[] {
  const blanked = blankLiterals(source);
  const names = formDataNames(blanked);
  if (names.size === 0) return [];

  const found: Inspected[] = [];
  const callRe = /\bapi\s*\.\s*(post|put|patch)\b/g;
  let m: RegExpExecArray | null;
  while ((m = callRe.exec(blanked)) !== null) {
    let i = skipWhitespace(blanked, m.index + m[0].length);
    // `api.post<CvUploadPreviewResponse>(…)` — parametry generyczne przeskakujemy
    // balansowaniem `<>`, bo bywają wielolinijkowe i zawierają `;`.
    if (blanked[i] === "<") {
      const genericEnd = matchBalanced(blanked, i, "<", ">");
      if (genericEnd < 0) continue;
      i = skipWhitespace(blanked, genericEnd + 1);
    }
    if (blanked[i] !== "(") continue;
    const close = matchBalanced(blanked, i, "(", ")");
    if (close < 0) continue;

    const argsCode = blanked.slice(i + 1, close);
    const variables = [...names].filter((name) =>
      new RegExp(`(?<![\\w$.])${name}(?![\\w$])`).test(argsCode),
    );
    if (variables.length === 0) continue;

    found.push({
      // Nagłówek czytamy z ORYGINAŁU — w wersji „wyczyszczonej" literał
      // "multipart/form-data" jest już spacjami.
      hasMultipart: source.slice(i + 1, close).includes("multipart/form-data"),
      line: source.slice(0, m.index).split("\n").length,
      method: m[1],
      variables,
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
      // Pliki testowe pomijamy świadomie: niosą fikstury z celowo zepsutym
      // wywołaniem (patrz test jednostkowy niżej), które nie jest kodem produkcyjnym.
      out.push(full);
    }
  }
  return out;
}

describe("detektor FormData bez multipartu", () => {
  it("łapie wywołanie bez nagłówka i przepuszcza poprawne", () => {
    const broken = [
      "const form = new FormData();",
      "form.append('file', file);",
      "api.post(`/api/signing/contracts/${id}/upload-signed`, form);",
    ].join("\n");
    expect(inspectSource(broken).map((c) => c.hasMultipart)).toEqual([false]);

    const brokenWithConfig = [
      "const fd = new FormData();",
      "api.post<Resp>('/api/x', fd, { params: { top_k: 5 } });",
    ].join("\n");
    expect(inspectSource(brokenWithConfig).map((c) => c.hasMultipart)).toEqual([false]);

    const correct = [
      "const fd = new FormData();",
      "api.post<Resp>('/api/x', fd, {",
      "  headers: { 'Content-Type': 'multipart/form-data' },",
      "});",
    ].join("\n");
    expect(inspectSource(correct).map((c) => c.hasMultipart)).toEqual([true]);

    // Nagłówek wspomniany w KOMENTARZU nie jest nagłówkiem.
    const commentOnly = [
      "const fd = new FormData();",
      "// TODO: multipart/form-data",
      "api.post('/api/x', fd);",
    ].join("\n");
    expect(inspectSource(commentOnly).map((c) => c.hasMultipart)).toEqual([false]);

    // Ciało nie-FormData nie jest przedmiotem tego kontraktu.
    const jsonBody = [
      "const fd = new FormData();",
      "api.post('/api/x', { order_id: 1 });",
    ].join("\n");
    expect(inspectSource(jsonBody)).toEqual([]);
  });
});

describe("kontrakt źródeł: FormData zawsze jako multipart", () => {
  const inspected = listSourceFiles(SRC_DIR).flatMap((file) =>
    inspectSource(fs.readFileSync(file, "utf8")).map((call) => ({
      ...call,
      where: `${path.relative(SRC_DIR, file)}:${call.line}`,
    })),
  );

  it("widzi realne uploady (skan nie jest pusty)", () => {
    // Bez tej asercji literówka w regexie dałaby zielony strażnik na zawsze.
    // 19 wywołań na 2026-08-20; próg z zapasem na usunięcie kilku z nich.
    expect(inspected.length).toBeGreaterThanOrEqual(10);
  });

  it("żadne api.post/put/patch z FormData nie idzie bez multipartu", () => {
    const offenders = inspected
      .filter((call) => !call.hasMultipart)
      .map((call) => `${call.where} — api.${call.method}(… ${call.variables.join(", ")} …)`);
    expect(offenders).toEqual([]);
  });
});
