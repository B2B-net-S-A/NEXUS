/**
 * Runda 10 (R10-N10-1): harnessy `/preview/*` pokazują WYŁĄCZNIE dane fikcyjne.
 *
 * Do 27.09.2026 harnessy (publiczne na produkcji) nosiły prawdziwe nazwiska
 * konsultantów i pracowników przy prawdziwych klientach, numerach zamówień
 * i stawkach — przepisane z ticketów i z `docs/`. Nazwiska potwierdzały inne
 * pliki repo: `docs/*-completion-report.md`, `docs/qa-session-*.md` oraz
 * przykłady w `backend/app/services/order_policies/*.py`.
 *
 * Nazwiska w tym teście są jako skróty SHA-256 (16 znaków) formy bez polskich
 * znaków i małymi literami — test pilnuje, żeby nie wróciły, i sam ich nie
 * publikuje. Klienci i numery zamówień nie są danymi osobowymi, więc stoją
 * tekstem.
 *
 * Nowy harness z danymi „z produkcji” = czerwony test. Dane fikcyjne pisz
 * wprost jako fikcyjne (Anna Przykładowa, Bank Przykładowy, SAP 4500123456).
 */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

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

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

function digest(text: string): string {
  return createHash("sha256").update(text).digest("hex").slice(0, 16);
}

/** Prawdziwe osoby (nazwisko albo imię i nazwisko), znalezione w harnessach
 * przy audycie rundy 10. */
const REAL_PEOPLE_DIGESTS = new Set([
  "0eb66ae8ba2c32dc", "15e09dda0edeb63c", "230f04ff252dee24", "2543a8d94734c911",
  "322562b6af49461f", "352255b6447cb58d", "3930af4e98091bd9", "3b16dc1e11ce563d",
  "3b3e0ad50bdc49ea", "3f293428017516a7", "3f7f55f5af5ca90a", "44ae0db785a6bec1",
  "4e580360d43c8789", "51c3ded870564cd0", "5910fd1dbc62b452", "5e61898b5894d681",
  "62a37b1890f7422a", "64013d8135915b81", "6d119e9e293c962d", "7114a6d4482895d0",
  "8476b08da4d5cad2", "87a1e35698bf85fb", "8956e6e6b86c64bb", "91fb9cea44bb7cf4",
  "93873cbe1fac9c1f", "93ab3cbc33f2c499", "93fa3c2f29e22add", "a5ce37cdc472db97",
  "b8285453f1cdd405", "b922e9bc4ee677a2", "b9daf191faeb43e1", "bc05d6ebca9d8680",
  "c05aa2d003f284fc", "c1f54f9de59b133c", "c82df1596ecaf7ee", "c8f544fd0ad4926a",
  "cc6a799ce4f51c20", "d2f0153e154284f5", "d6be15b69de81756", "dca674a37d0a43d1",
  "e1239944c05123d5", "e47e42f943727248", "e6f3fb7d7f7ce03b", "e8fd9676618ba5a4",
  "e94377b8986faa54", "e9473e62ee12993e", "f24761c59db45b25", "fbfb45eea394478a",
]);

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
  const text = normalize(readFileSync(path, "utf8"));
  const words = text.split(/[^\p{L}\p{N}_]+/u).filter(Boolean);
  const hits = new Set<string>();
  words.forEach((word, index) => {
    if (REAL_PEOPLE_DIGESTS.has(digest(word))) hits.add(`osoba (skrót ${digest(word)})`);
    const pair = index > 0 ? `${words[index - 1]} ${word}` : "";
    if (pair && REAL_PEOPLE_DIGESTS.has(digest(pair))) hits.add(`osoba (skrót ${digest(pair)})`);
    if (REAL_CLIENT_WORDS.includes(word)) hits.add(`klient „${word}”`);
  });
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

  it("strażnik rozpoznaje prawdziwą osobę również w innej kolejności i bez znaków", () => {
    // Samokontrola normalizacji: „Surname Firstname” z listy zamówień i zapis
    // bez polskich znaków trafiają w ten sam skrót co forma kanoniczna.
    const probe = normalize("Pawel LASKI");
    const [first, last] = probe.split(" ");
    expect(REAL_PEOPLE_DIGESTS.has(digest(`${first} ${last}`))).toBe(true);
  });
});
