/**
 * Strażnik: generator nie zakłada kontraktu przed podpisem.
 *
 * Zgłoszenie 09.2026 (umowa 1506/2026, Adam Grono): dokument ze statusem
 * podpisu „Niepodpisana" miał w systemie kontrakt. Winna była poczta zamówień
 * (patrz `backend/tests/test_order_mail_person_already_in_base.py`), ale
 * generator miał własną, drugą drogę: trzy przyciski podpisu wołały
 * `POST /api/b2b-generator/generate`, który zakłada szkic `Contract`.
 * Umowy podpisujemy offline (17.09.2026), więc przyciski zdjęto.
 *
 * Do kontraktu prowadzi odtąd JEDNA droga: „Oznacz jako podpisaną"
 * (`confirm-fully-signed`), która zakłada kontrakt od razu jako `active`.
 * Test czyta ŹRÓDŁO komponentu — mock `signingApi: {}` w sąsiednich testach
 * sprawia, że wywołanie nie wysypałoby renderu, więc zwykły test nic by nie
 * złapał.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  join(process.cwd(), "src/components/v2/pages/B2BContractGeneratorV2.tsx"),
  "utf8",
);

/** Ciało komponentu — bez eksportowanych helperów nad nim (te mają własne testy).
 *
 * Do 23.09.2026 cięcie szukało `export default function`, którego w pliku nie
 * ma: `indexOf` dawał -1, `slice(-1)` ostatni znak, a dwie pierwsze asercje
 * sprawdzały pusty tekst i nie mogły paść. */
const COMPONENT_START = SOURCE.indexOf("export function B2BContractGeneratorV2(");
const COMPONENT = SOURCE.slice(COMPONENT_START);

describe("B2B generator never creates a contract before the signature", () => {
  it("finds the component body it guards", () => {
    expect(COMPONENT_START).toBeGreaterThan(0);
    expect(COMPONENT.length).toBeGreaterThan(10_000);
  });

  it("does not call the endpoint that drafts a Contract", () => {
    expect(COMPONENT).not.toMatch(/b2bGeneratorApi\s*\.\s*generate\s*\(/);
  });

  it("does not call any signing endpoint that needs a contract first", () => {
    expect(COMPONENT).not.toMatch(/signingApi\s*\.\s*\w+\s*\(/);
  });

  it("keeps the only sanctioned path — confirm-fully-signed", () => {
    expect(SOURCE).toMatch(/b2bGeneratorApi\s*\.\s*confirmFullySigned\s*\(/);
  });

  it("no longer renders the three pre-signature actions", () => {
    for (const label of [
      "Wyślij do podpisu (QES)",
      "Oznacz: wysłana mailem",
      "Wgraj podpisaną (z maila)",
    ]) {
      expect(SOURCE).not.toContain(label);
    }
  });
});
