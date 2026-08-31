/**
 * Spis treści a PRAWDZIWA treść instrukcji zamówień.
 *
 * Kotwice powstają z DOM-u po wyrenderowaniu Markdownu, więc jedyny sposób, by
 * sprawdzić, że każdy punkt spisu treści faktycznie gdzieś prowadzi, to
 * przepuścić przez renderer dokument, który trafi do bazy — a nie wymyśloną
 * próbkę. Instrukcja ma kilkanaście sekcji per klient i to po nich Delivery
 * Lead nawiguje; martwy odnośnik zostawia go w sekcji innego klienta,
 * z innymi przelicznikami stawek.
 *
 * Render 36 KB Markdownu w jsdom jest kosztowny, więc dokument renderujemy
 * DOKŁADNIE RAZ i wszystkie asercje robimy na jego wyniku.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { assignHeadingIds } from "@/lib/procedure-headings";
import type { ProcedureHeading } from "@/components/v2/ProcedureTableOfContents";

const HERE = dirname(fileURLToPath(import.meta.url));
const PROCEDURE = resolve(
  HERE,
  "../../../../../backend/app/data/procedures/zamowienia-instrukcja-delivery-lead.md",
);

const markdown = readFileSync(PROCEDURE, "utf-8");

let headings: ProcedureHeading[] = [];
let renderedIds: string[] = [];

beforeAll(() => {
  const { container } = render(
    <div data-testid="content">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>,
  );
  const root = container.querySelector<HTMLElement>('[data-testid="content"]')!;
  headings = assignHeadingIds(root);
  renderedIds = Array.from(root.querySelectorAll("h2, h3")).map((el) => el.id);
});

describe("spis treści instrukcji zamówień", () => {
  it("każdy punkt spisu treści odpowiada wyrenderowanemu nagłówkowi", () => {
    expect(headings.length).toBeGreaterThan(10);
    expect(headings.map((h) => h.id)).toEqual(renderedIds);
  });

  it("identyfikatory kotwic są unikalne", () => {
    const ids = headings.map((h) => h.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("instrukcja ma sekcję każdego klienta z własną regułą", () => {
    const titles = headings.map((h) => h.text);
    for (const client of [
      "BNP Paribas",
      "BIK",
      "Polkomtel",
      "Lotte Wedel",
      "Cyfrowy Polsat",
      "Nordea",
      "Bank Pocztowy",
      "Credit Agricole",
      "Erste Bank Polska",
      "Orlen",
      "PFRON",
    ]) {
      expect(titles, `brak sekcji dla klienta ${client}`).toContain(client);
    }
  });

  it("dokument nie zaczyna się nagłówkiem pierwszego poziomu", () => {
    // Widok procedury renderuje tytuł z bazy jako własny nagłówek nad treścią —
    // `# Tytuł` w Markdownie dałby ten sam napis dwa razy pod rząd.
    expect(markdown.trimStart().startsWith("# ")).toBe(false);
  });
});
