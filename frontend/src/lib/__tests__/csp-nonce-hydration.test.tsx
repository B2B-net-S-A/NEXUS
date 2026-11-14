/**
 * Nonce CSP a hydratacja w `next dev` (11.2026, po #3407).
 *
 * Przeglądarka po sparsowaniu zeruje atrybut `nonce` w DOM-ie (wartość zostaje
 * tylko we właściwości `script.nonce`), więc przy hydratacji React porównuje
 * `nonce=""` z DOM-u z wartością z serwera i w dev zgłasza niezgodność.
 * Nakładka Next.js pokazywała wtedy „1 Issue” na każdej stronie i zasłaniała
 * prawdziwe błędy hydratacji. Nonce ma zostać w HTML-u (CSP go sprawdza), więc
 * wyciszamy tylko porównanie na samym elemencie: `suppressHydrationWarning`.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

/** Błędy z hydratacji `<script nonce>`, którego atrybut w DOM przeglądarka już wyzerowała. */
function hydrationErrors(suppress: boolean): string[] {
  const element = (
    <script
      nonce="abc123"
      suppressHydrationWarning={suppress}
      dangerouslySetInnerHTML={{ __html: "void 0" }}
    />
  );
  const container = document.createElement("div");
  container.innerHTML = renderToString(element);
  container.querySelector("script")?.setAttribute("nonce", "");

  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    act(() => {
      hydrateRoot(container, element);
    });
    return spy.mock.calls.map((call) => String(call[0]));
  } finally {
    spy.mockRestore();
  }
}

describe("nonce a hydratacja", () => {
  it("bez suppressHydrationWarning React zgłasza niezgodność nonce (kontrola testu)", () => {
    expect(hydrationErrors(false).some((message) => message.includes("didn't match"))).toBe(true);
  });

  it("z suppressHydrationWarning hydratacja jest cicha", () => {
    expect(hydrationErrors(true)).toEqual([]);
  });
});

describe("app/layout.tsx", () => {
  const layout = readFileSync(join(process.cwd(), "src/app/layout.tsx"), "utf8");

  it("bootstrap motywu niesie nonce z serwera i wycisza jego porównanie przy hydratacji", () => {
    const tag = /<script\b[^>]*\bnonce=\{nonce\}[^>]*\/>/.exec(layout)?.[0] ?? "";
    expect(tag, "w layout.tsx brak <script nonce={nonce} … />").not.toBe("");
    expect(tag).toContain("suppressHydrationWarning");
  });
});
