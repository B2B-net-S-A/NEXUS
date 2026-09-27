import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Strażnik: żadnego natywnego `confirm()` w kodzie frontu (runda 11 audytu,
 * FRONT). Natywny dialog zamraża automatyzację przeglądarki (klik leci
 * w timeout, `navigate` odrzuca dialog i akcja się nie wykonuje) i odstaje od
 * UI. Zamiast niego: `useConfirmV2` (`components/v2/modals/ConfirmV2`),
 * `ConfirmTwoStepButton` albo `ConfirmButton`/`DeleteButton`.
 *
 * `beforeunload` (niezapisane zmiany przy opuszczaniu strony) nie woła
 * `confirm()`, więc strażnik go nie dotyczy.
 */

const SRC = join(__dirname, "..");

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__tests__" || name === "__mocks__" || name === "node_modules") continue;
      sourceFiles(path, out);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

/** Wycina komentarze — liczy się tylko kod (wiele plików tłumaczy w komentarzu, czemu NIE `window.confirm`). */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "))
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

/** Wywołanie natywnego potwierdzenia: goły `confirm(` albo `window.confirm`. */
const NATIVE_CONFIRM =
  /(^|[^\w.$])confirm\s*\(|\b(?:window|globalThis|self)\s*\??\.\s*confirm\b/;

function offendersIn(source: string): number[] {
  return stripComments(source)
    .split("\n")
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => NATIVE_CONFIRM.test(line))
    .map(({ index }) => index + 1);
}

describe("natywne window.confirm", () => {
  it("rozpoznaje wywołania i pomija komentarze oraz metody obiektów", () => {
    expect(offendersIn('if (!confirm("Usunąć?")) return;')).toEqual([1]);
    expect(offendersIn("const ok = window.confirm(`Usunąć ${x}?`);")).toEqual([1]);
    expect(offendersIn("if (window?.confirm) {}")).toEqual([1]);
    expect(offendersIn("  !confirm(\n    `tekst`,\n  )")).toEqual([1]);
    expect(offendersIn("// zamiast `window.confirm(...)`")).toEqual([]);
    expect(offendersIn("/**\n * Zastępuje `window.confirm`.\n */")).toEqual([]);
    expect(offendersIn("{/* bez confirm() */}")).toEqual([]);
    expect(offendersIn("optimisticRef.current?.confirm?.({ ok: true });")).toEqual([]);
    expect(offendersIn("await askConfirm({ title: 'x' });")).toEqual([]);
    expect(offendersIn("pwForm.confirm")).toEqual([]);
  });

  it("kod frontu nie woła natywnego confirm()", () => {
    const offenders = sourceFiles(SRC).flatMap((file) =>
      offendersIn(readFileSync(file, "utf8")).map(
        (line) => `${relative(SRC, file)}:${line}`,
      ),
    );
    expect(
      offenders,
      "użyj useConfirmV2 (components/v2/modals/ConfirmV2) albo ConfirmTwoStepButton zamiast natywnego confirm()",
    ).toEqual([]);
  });
});
