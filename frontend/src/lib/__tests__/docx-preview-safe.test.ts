/**
 * SEC-01 (audyt 22.09 r2): podgląd DOCX nie może wykonać kodu z dokumentu.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SAFE_DOCX_OPTIONS,
  hardenDocxDom,
  isSafeDocxHref,
  renderDocxSafely,
} from "@/lib/docx-preview-safe";

const renderAsync = vi.fn();
vi.mock("docx-preview", () => ({ renderAsync: (...args: unknown[]) => renderAsync(...args) }));

afterEach(() => {
  renderAsync.mockReset();
});

describe("SAFE_DOCX_OPTIONS", () => {
  it("wyłącza altChunk, komentarze i śledzenie zmian", () => {
    expect(SAFE_DOCX_OPTIONS.renderAltChunks).toBe(false);
    expect(SAFE_DOCX_OPTIONS.renderComments).toBe(false);
    expect(SAFE_DOCX_OPTIONS.renderChanges).toBe(false);
  });
});

describe("renderDocxSafely", () => {
  it("wołający nie może włączyć altChunk", async () => {
    const host = document.createElement("div");
    renderAsync.mockImplementation(async (_blob, container: HTMLElement) => {
      container.innerHTML =
        '<section class="docx"><iframe srcdoc="<script>alert(1)</script>"></iframe><p>CV</p></section>';
    });
    await renderDocxSafely(new Blob(["x"]), host, {
      renderAltChunks: true,
      className: "docx",
    } as never);
    const options = renderAsync.mock.calls[0][3];
    expect(options.renderAltChunks).toBe(false);
    expect(options.className).toBe("docx");
    expect(host.querySelector("iframe")).toBeNull();
    expect(host.textContent).toContain("CV");
  });
});

describe("hardenDocxDom", () => {
  it("usuwa elementy aktywne, atrybuty zdarzeń i niebezpieczne linki", () => {
    const host = document.createElement("div");
    host.innerHTML = [
      '<iframe srcdoc="x"></iframe>',
      "<object data='x'></object><embed src='x'>",
      '<img src="data:image/png;base64,AAA" onerror="steal()">',
      '<img src="https://evil.example/x.png">',
      '<a id="js" href="javascript:alert(1)">klik</a>',
      '<a id="js2" href=" java&#9;script:alert(1)">klik</a>',
      '<a id="data" href="data:text/html,<script>1</script>">klik</a>',
      '<a id="rel" href="/api/admin">klik</a>',
      '<a id="ok" href="https://example.com/cv">ok</a>',
      '<a id="mail" href="mailto:jan@example.com">mail</a>',
      '<a id="anchor" href="#bookmark">kotwica</a>',
      '<svg><a id="svg" xlink:href="javascript:alert(1)"><text>s</text></a></svg>',
      '<p onclick="steal()">tekst</p>',
    ].join("");

    hardenDocxDom(host);

    expect(host.querySelector("iframe,object,embed")).toBeNull();
    expect(host.querySelector("[onerror],[onclick]")).toBeNull();
    const imgs = host.querySelectorAll("img");
    expect(imgs[0].getAttribute("src")).toMatch(/^data:image\//);
    expect(imgs[1].hasAttribute("src")).toBe(false);
    expect(host.querySelector("#js")?.hasAttribute("href")).toBe(false);
    expect(host.querySelector("#js2")?.hasAttribute("href")).toBe(false);
    expect(host.querySelector("#data")?.hasAttribute("href")).toBe(false);
    expect(host.querySelector("#rel")?.hasAttribute("href")).toBe(false);
    expect(host.querySelector("#ok")?.getAttribute("href")).toBe("https://example.com/cv");
    expect(host.querySelector("#ok")?.getAttribute("rel")).toContain("noopener");
    expect(host.querySelector("#mail")?.getAttribute("href")).toBe("mailto:jan@example.com");
    expect(host.querySelector("#anchor")?.getAttribute("href")).toBe("#bookmark");
    const svgLink = host.querySelector("#svg");
    expect(svgLink?.getAttribute("xlink:href") ?? svgLink?.getAttribute("href")).toBeNull();
    expect(host.textContent).toContain("tekst");
  });

  it("isSafeDocxHref przyjmuje tylko http(s), mailto, tel i kotwice", () => {
    expect(isSafeDocxHref("https://a.pl")).toBe(true);
    expect(isSafeDocxHref("tel:+48123")).toBe(true);
    expect(isSafeDocxHref("#x")).toBe(true);
    expect(isSafeDocxHref("javascript:alert(1)")).toBe(false);
    expect(isSafeDocxHref("JaVaScRiPt:alert(1)")).toBe(false);
    expect(isSafeDocxHref("vbscript:x")).toBe(false);
    expect(isSafeDocxHref("//evil.example")).toBe(false);
    expect(isSafeDocxHref("")).toBe(false);
    expect(isSafeDocxHref(null)).toBe(false);
  });
});

describe("strażnik źródeł", () => {
  const SRC = join(process.cwd(), "src");

  function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        return entry.name === "__tests__" || entry.name === "node_modules"
          ? []
          : sourceFiles(path);
      }
      const isSource =
        /\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$|\.d\.ts$/.test(entry.name);
      return isSource ? [path] : [];
    });
  }

  it("`docx-preview` importuje wyłącznie docx-preview-safe.ts", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => /["']docx-preview["']/.test(readFileSync(file, "utf8")))
      .map((file) => relative(SRC, file))
      .filter((file) => file !== join("lib", "docx-preview-safe.ts"));
    expect(offenders).toEqual([]);
  });
});
