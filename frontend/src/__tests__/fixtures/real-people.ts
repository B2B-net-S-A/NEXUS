/**
 * Prawdziwe osoby (konsultanci, pracownicy, zgłaszający), których nazwiska
 * trafiły kiedyś do publicznego repo — harnessy `/preview/*` (audyt rundy 10,
 * 27.09.2026), testy (14.10.2026) i dokumenty w `docs/` (26.11.2026). Repo i
 * logi Actions są publiczne, więc dane fikcyjne pisz wprost jako fikcyjne
 * (Anna Przykładowa, Jan Testowy).
 *
 * Nazwiska stoją tu jako skróty SHA-256 (16 znaków) formy bez polskich znaków
 * i małymi literami — strażnicy pilnują, żeby nie wróciły, i sami ich nie
 * publikują. Czytają je `app/preview/__tests__/harness-fictional-data.test.ts`
 * i `__tests__/fictional-people-in-tests.test.ts` (testy i `docs/`).
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
  // Testy kontraktorów i naprawy 0274 (26.11.2026).
  "173e3143bc97bdc1",
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
  // Raporty w `docs/` i opisy układów PDF w czytnikach zamówień (26.11.2026):
  // osoby, które stały tam przy stawce albo kwocie. Pełne imię i nazwisko,
  // kilka rzadkich nazwisk także samych (w raportach stały bez imienia).
  "8ccc3f82f0693a33", "5c9eee8ab0afeef7", "16bd7dd17ccbd015", "128ad5b2ae3e103a",
  "ac1a1e9e5bcff0bd", "c12f563ad017bbdd", "325aa589f100cb0d", "21b4193456be6557",
  "0285615eae584942", "6dfe59220e8bf292", "9cf9c664484570f6", "af634fde963d7d25",
  "8f8f88121b17081b", "a9710796a7548ced", "b023b0fb7105f591", "4bd3552534c1dbb8",
  "ec737767c9a36e33", "49a8c450231906bb", "dcce910b0bbea7e8", "3fcd98b25ae79dbc",
  "ad77d99a2dc6638d", "479fe12595385178", "4158be8608cbd23f", "793fc6ce767d588f",
  "3f938c405fb77453", "0709d2088b1d3f3d", "48d42f7b02f1b02a", "cddd4ed764a8f691",
  "48c4605185721ad6", "089180f0ec48350b", "931d8ce1383c1193",
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
