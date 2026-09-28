import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * Strażniki responsywności (audyt 23.09.2026, docs/responsiveness-audit-2026-09-23).
 * Każdy pilnuje reguły, której złamanie psuło WSZYSTKIE ekrany naraz albo
 * ukrywało akcje na urządzeniach dotykowych, a jsdom tego nie widzi.
 */

const SRC = join(__dirname, "..");

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === "__tests__" || name === "node_modules") continue;
      sourceFiles(path, out);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(path);
    }
  }
  return out;
}

type JsxNode = ts.JsxElement | ts.JsxSelfClosingElement;

/** Stałe napisowe pliku (`const INPUT = "…"`) — klasy często żyją w nich. */
function stringConstants(sf: ts.SourceFile): Map<string, string> {
  const out = new Map<string, string>();
  const visit = (node: ts.Node) => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      (ts.isStringLiteral(node.initializer) || ts.isNoSubstitutionTemplateLiteral(node.initializer))
    ) {
      out.set(node.name.text, node.initializer.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return out;
}

/**
 * Tokeny klas z `className` — wszystkie literały w wyrażeniu (także w `cn(…)`
 * i w gałęziach warunków) plus wartości stałych napisowych pliku. Klasa
 * dołożona dynamicznie spoza pliku jest niewidoczna — strażnik pilnuje
 * wzorca pisanego wprost, nie każdego możliwego.
 */
function classTokens(node: JsxNode, constants: Map<string, string>): string[] {
  const attrs = (ts.isJsxElement(node) ? node.openingElement : node).attributes;
  const parts: string[] = [];
  const collect = (n: ts.Node) => {
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) parts.push(n.text);
    else if (ts.isTemplateExpression(n)) parts.push(n.head.text, ...n.templateSpans.map((s) => s.literal.text));
    else if (ts.isIdentifier(n) && constants.has(n.text)) parts.push(constants.get(n.text)!);
    ts.forEachChild(n, collect);
  };
  for (const prop of attrs.properties) {
    if (ts.isJsxAttribute(prop) && prop.name.getText() === "className" && prop.initializer) {
      collect(prop.initializer);
    }
  }
  return parts.join(" ").split(/\s+/).filter(Boolean);
}

function tagName(node: JsxNode): string {
  return (ts.isJsxElement(node) ? node.openingElement : node).tagName.getText();
}

/** Przechodzi po każdym elemencie JSX każdego pliku `.tsx` ze `src`. */
function eachJsxElement(visit: (node: JsxNode, where: (n: ts.Node) => string, constants: Map<string, string>) => void) {
  for (const file of sourceFiles(SRC).filter((f) => f.endsWith(".tsx"))) {
    const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const constants = stringConstants(sf);
    const where = (n: ts.Node) => `${relative(SRC, file)}:${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`;
    const walk = (node: ts.Node) => {
      if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) visit(node, where, constants);
      ts.forEachChild(node, walk);
    };
    walk(sf);
  }
}

// Oba strażniki parsują cały frontend parserem TypeScript — na runnerze CI
// z pokryciem trwa to ~7 s, więcej niż domyślny limit Vitesta (5 s).
const GUARD_TIMEOUT_MS = 60_000;

describe("responsywność — reguły wspólne", () => {
  it("shell nie używa h-screen/100vh (dół strony chował się pod paskiem przeglądarki mobilnej)", () => {
    // Komentarze w shellu tłumaczą, czemu NIE h-screen — liczy się tylko kod.
    const shell = readFileSync(join(SRC, "components/v2/shell/AppShellV2.tsx"), "utf8")
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
      .join("\n");
    expect(shell).not.toMatch(/\bh-screen\b|100vh/);
    expect(shell).toMatch(/\bh-dvh\b/);
  });

  it("pola formularzy mają 16 px na dotyku (iOS nie przybliża strony przy fokusie)", () => {
    const css = readFileSync(join(SRC, "app/globals.css"), "utf8");
    const block = css.match(/@media \(pointer: coarse\) \{[\s\S]*?font-size: max\(16px, 1em\)/);
    expect(block, "brak reguły 16 px dla pól na urządzeniach dotykowych").not.toBeNull();
  });

  it("akcje po najechaniu są widoczne na dotyku (hover nie istnieje na telefonie)", () => {
    // Goły `opacity-0 … group-hover:opacity-100` chowa przycisk na zawsze na
    // ekranie dotykowym — w Tailwind v4 `hover:` działa tylko przy myszy.
    const bare = /(^|[\s"'`])opacity-0(?=[\s"'`])[^"'`\n]*group-hover:opacity-100/;
    const offenders = sourceFiles(SRC)
      .filter((file) => !relative(SRC, file).startsWith("app/preview/"))
      .flatMap((file) =>
        readFileSync(file, "utf8")
          .split("\n")
          .map((line, index) => ({ line, index }))
          .filter(({ line }) => bare.test(line))
          .map(({ index }) => `${relative(SRC, file)}:${index + 1}`),
      );
    expect(
      offenders,
      "użyj `pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100`",
    ).toEqual([]);
  });

  it("pole z flex-1 ma jawną szerokość (inaczej jego minimum liczy się z size=20 i fontu systemu)", () => {
    // Runda 12/13: `<input className="flex-1 …">` bez szerokości wnosi do
    // min-content przodka swoją szerokość domyślną (`size=20`, `cols=20`,
    // najdłuższa opcja `<select>`), zależną od fontu systemu. W `<fieldset>`
    // (min-width: min-content) albo w elemencie flex z `min-width: auto`
    // wiersz przestawał się mieścić w 360 px. `w-0` (albo `w-full`, `w-[…]`,
    // `basis-…`) zeruje ten wkład, a przy `flex-1` nie zmienia układu na
    // desktopie. Komponenty `Input`/`Textarea` mają `w-full` w bazie.
    const offenders: string[] = [];
    eachJsxElement((node, where, constants) => {
      if (!/^(input|textarea|select)$/.test(tagName(node))) return;
      const tokens = classTokens(node, constants);
      if (!tokens.includes("flex-1")) return;
      if (tokens.some((t) => /^(w-0|w-px|w-full|w-\d.*|w-\[.+\]|basis-.+)$/.test(t))) return;
      offenders.push(where(node));
    });
    expect(offenders, "dopisz `w-0` obok `flex-1`").toEqual([]);
  }, GUARD_TIMEOUT_MS);

  it("przewijany kontener nie wypuszcza elementów absolute/sr-only (poziomy scroll całej strony)", () => {
    // Runda 12/13: `sr-only` to `position: absolute`. Bez pozycjonowanego
    // przodka jego blokiem zawierającym jest dokument, więc NIE jest przycinany
    // przez `overflow-x-auto` i z pozycji w szerokiej tabeli poszerza całą
    // stronę na telefonie. Kontener dostaje `relative` (bez wariantu — musi
    // działać na najwęższym ekranie).
    const scroll = /^([a-z0-9-]+:)*overflow-(x-)?(auto|scroll)$/;
    const positioned = /^(relative|absolute|fixed|sticky)$/;
    const escaping = /^(absolute|sr-only)$/;
    const offenders: string[] = [];
    eachJsxElement((node, where, constants) => {
      const tokens = classTokens(node, constants);
      if (!tokens.some((t) => scroll.test(t)) || tokens.some((t) => positioned.test(t))) return;
      const search = (n: ts.Node) =>
        ts.forEachChild(n, (child) => {
          if (ts.isJsxElement(child) || ts.isJsxSelfClosingElement(child)) {
            const inner = classTokens(child, constants);
            if (inner.some((t) => escaping.test(t))) {
              offenders.push(`${where(node)} (${where(child)})`);
              return;
            }
            if (inner.some((t) => positioned.test(t))) return;
          }
          search(child);
        });
      search(node);
    });
    expect(offenders, "dodaj `relative` do przewijanego kontenera").toEqual([]);
  }, GUARD_TIMEOUT_MS);
});
