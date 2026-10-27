/**
 * Prawdziwe osoby (konsultanci, pracownicy, zgłaszający), których nazwiska
 * trafiły kiedyś do publicznego repo — harnessy `/preview/*` (audyt rundy 10,
 * 27.09.2026) i testy (14.10.2026). Repo i logi Actions są publiczne, więc
 * dane fikcyjne pisz wprost jako fikcyjne (Anna Przykładowa, Jan Testowy).
 *
 * Nazwiska stoją tu jako skróty SHA-256 (16 znaków) formy bez polskich znaków
 * i małymi literami — strażnicy pilnują, żeby nie wróciły, i sami ich nie
 * publikują. Czytają je `app/preview/__tests__/harness-fictional-data.test.ts`
 * i `__tests__/fictional-people-in-tests.test.ts`.
 */
import { createHash } from "node:crypto";

/** Małe litery, bez polskich znaków („Łukasz” → „lukasz”). */
export function normalizePersonText(text: string): string {
  return text
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

export function personDigest(text: string): string {
  return createHash("sha256").update(text).digest("hex").slice(0, 16);
}

/** Nazwisko albo imię i nazwisko, po `normalizePersonText`. */
export const REAL_PEOPLE_DIGESTS: ReadonlySet<string> = new Set([
  // Audyt harnessów, runda 10 (27.09.2026).
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
  // Delivery Lead z testu listy rekrutacji (14.10.2026).
  "0b52a7c4fc7a6ede", "8adf95bd406bbcac",
  // Makiety „Szczegółów administracyjnych” na stagingu (26.10.2026) — pełne
  // imiona i nazwiska, bo same nazwiska są pospolite.
  "0c553569a5f63b0e", "9b0e7f611a6e171b",
]);

/**
 * Skróty prawdziwych osób w tekście: pojedyncze słowo albo para sąsiednich
 * słów (także na styku linii — „zgłosił: Jan\n * Kowalski”).
 */
export function realPeopleIn(
  text: string,
  digests: ReadonlySet<string> = REAL_PEOPLE_DIGESTS,
): string[] {
  const words = normalizePersonText(text)
    .split(/[^\p{L}\p{N}_]+/u)
    .filter(Boolean);
  const cache = new Map<string, boolean>();
  const isReal = (candidate: string) => {
    let hit = cache.get(candidate);
    if (hit === undefined) {
      hit = digests.has(personDigest(candidate));
      cache.set(candidate, hit);
    }
    return hit;
  };
  const hits = new Set<string>();
  words.forEach((word, index) => {
    if (isReal(word)) hits.add(personDigest(word));
    if (index > 0) {
      const pair = `${words[index - 1]} ${word}`;
      if (isReal(pair)) hits.add(personDigest(pair));
    }
  });
  return [...hits];
}
