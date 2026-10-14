/**
 * Runda 10 (R10-N10-1): harnessy `/preview/*` pokazują WYŁĄCZNIE dane fikcyjne.
 *
 * Do 27.09.2026 harnessy (publiczne na produkcji) nosiły prawdziwe nazwiska
 * konsultantów i pracowników przy prawdziwych klientach, numerach zamówień
 * i stawkach — przepisane z ticketów i z `docs/`. Nazwiska potwierdzały inne
 * pliki repo: `docs/*-completion-report.md`, `docs/qa-session-*.md` oraz
 * przykłady w `backend/app/services/order_policies/*.py`.
 *
 * Nazwiska są jako skróty SHA-256 we wspólnym `__tests__/fixtures/real-people.ts`
 * (ten sam zbiór pilnuje testów — `__tests__/fictional-people-in-tests.test.ts`).
 * Klienci i numery zamówień nie są danymi osobowymi, więc stoją tekstem.
 *
 * Nowy harness z danymi „z produkcji” = czerwony test. Dane fikcyjne pisz
 * wprost jako fikcyjne (Anna Przykładowa, Bank Przykładowy, SAP 4500123456).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import {
  normalizePersonText as normalize,
  realPeopleIn,
} from "@/__tests__/fixtures/real-people";

const SRC = join(process.cwd(), "src");

const HARNESS_FILES = [
  ...walk(join(SRC, "app/preview")),
  ...walk(join(SRC, "components/candidates/preview")),
  join(SRC, "components/trainee/preview-fixtures.ts"),
];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : walk(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

/** Klienci NEXUSA — w harnessie stoją klienci fikcyjni. */
const REAL_CLIENT_WORDS = [
  "velobank", "nordea", "alior", "polkomtel", "polkomtela", "cardif", "pko", "bik", "bnp",
  "paribas", "orlen", "tauron", "mbank", "erste", "ernst", "agricole", "pocztowy",
  "pocztowego", "cez",
];

/** Numery zamówień i umów przepisane z prawdziwych dokumentów. */
const REAL_ORDER_NUMBERS = [
  "4500030197", "4500030845", "4500029903", "4500029904", "4500719650", "4500719651",
  "4500719652", "4500030067", "4500031000", "4500099001", "3/07/2031/bl", "3/09/2026/bl",
  "eywo00016165", "oit/0189", "oit/0190", "e-zdrow",
];

function findings(path: string): string[] {
  const source = readFileSync(path, "utf8");
  const text = normalize(source);
  const words = text.split(/[^\p{L}\p{N}_]+/u).filter(Boolean);
  const hits = new Set<string>(realPeopleIn(source).map((d) => `osoba (skrót ${d})`));
  for (const word of words) {
    if (REAL_CLIENT_WORDS.includes(word)) hits.add(`klient „${word}”`);
  }
  for (const number of REAL_ORDER_NUMBERS) {
    if (text.includes(number)) hits.add(`numer „${number}”`);
  }
  return [...hits].map((hit) => `${relative(SRC, path)}: ${hit}`);
}

describe("harnessy /preview/* bez prawdziwych danych", () => {
  it("skanuje harnessy (strażnik nie jest pusty)", () => {
    expect(HARNESS_FILES.length).toBeGreaterThan(50);
  });

  it("żaden harness nie nosi prawdziwej osoby, klienta ani numeru zamówienia", () => {
    expect(HARNESS_FILES.flatMap(findings)).toEqual([]);
  });

  it("normalizacja zrównuje wielkość liter i polskie znaki", () => {
    // Zapis z listy zamówień („ŁUKASZ ŻÓŁTEK”) i bez znaków („Lukasz Zoltek”)
    // dają tę samą formę, więc trafiają w ten sam skrót. Nazwisko fikcyjne —
    // prawdziwe stałoby tu tekstem w publicznym repo.
    expect(normalize("ŁUKASZ ŻÓŁTEK")).toBe("lukasz zoltek");
    expect(normalize("Lukasz Zoltek")).toBe(normalize("Łukasz Żółtek"));
  });
});
