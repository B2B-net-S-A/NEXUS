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
  // Imiennicy z liczenia kontraktorów (26.11.2026), obie kolejności zapisu;
  // pierwszy to początek skrótu z `NAMESAKE_NAME_DIGESTS` w backendzie.
  "f53ec585b3897e2d", "3b87a1ba2acde30f",
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
  // Testy czytników zamówień i ekranów, komentarze i dokumenty (26.11.2026):
  // konsultanci z zamówień i pracownicy, sprawdzeni z kopią bazy na stagingu.
  // Pełne imię i nazwisko w zapisanej kolejności, także formy odmienione.
  "034c38e80389713b", "065b3f9f7394270b", "07f60222aed4beca", "092caaa077544142",
  "0a97b676f29327af", "10c7fe5b54de2c08", "17b5be49bee80973", "1a4e220cd7caa5e7",
  "203a491742e296ee", "2121c3cf250a33c3", "27c95862f5b20512", "2db628f0e2378c84",
  "32d9400564bf88eb", "32e6654784c9e9af", "336b9cb038f5e04d", "3562e9770877120f",
  "35e1b04d474fe2b8", "36dbe8cb88afba85", "37a6c867cb0e69c9", "383356c1f4ba9115",
  "3a1c65b509cf2136", "3b0b32ba61aebf11", "419c3fa6e37c80d4", "41e054690851a1f9",
  "42b3b925128b9117", "433f526ecc798b28", "45ca2a2888c34037", "4998c8801dbc349c",
  "4f458d989b1415c0", "508d97af59d07049", "531cf1b809f5b0ba", "557ce874713ebaff",
  "5bfcb8a164666126", "5d3ccfee0b7527db", "5e4d7169983880b4", "609677bec716b946",
  "628282480c0d5781", "62f293ced2e80c37", "62f7ac729ea33bef", "635ac71fa569c610",
  "6528660cf45579c9", "68296ce444e9d3ff", "68b02c0639a5c389", "7158531f0f00efd1",
  "7357eedcd1bb9621", "757dd8114df30ffb", "763b157ca9dd927c", "79f97568cdfb8d2b",
  "7b321af9edb7b5a9", "7fb59107d2568674", "829cd64a542da487", "83e836b63d40ca7e",
  "865d1decf3753eff", "878b455013031e42", "89590ba297f2ab54", "89d4b3afbced9e30",
  "8c4626769d322019", "8d6441663c04462d", "8dc74f3a1dd72165", "8f0e236676ac6db6",
  "8f21b57126713e73", "9145225b7b6525af", "93b57f61e4474efb", "94e79fc169bf1743",
  "95516222ff1ba25b", "a00807c706249e31", "a23578c5915c2588", "a490f6564d0cbd9f",
  "a5048e720e2df627", "a518008149755211", "a60c16953ee04b50", "aa807a88ff4a331e",
  "ad7cf8e5ed0648d5", "b8c52a0bda19dde4", "ba98f33b7e5b5fe6", "bc698ce7ca477ca3",
  "bd4d72dc511a269d", "c3f83b94eaad8097", "c76378d16a9b9a11", "c78fa331a45bbd4e",
  "ca390566fbde5db6", "d193e796e046818a", "d34e4b20c8c62b55", "d4747d4f97e55f80",
  "d97019404abda9ab", "da538e6a62b4a686", "db8a14ffb12b97b4", "dd3e06c88fe3c412",
  "de3cf7a75e814f29", "e07a9c13045b4746", "e117733175f4f12d", "e3a56214229dec31",
  "e8b4c1a6e85516ee", "ec359850d6426aac", "ecca297903ff0134", "f00a034c8e192b63",
  "f0c18d4fd757ba05", "f415b22f943efd54", "fa2cfeae316dbd73", "fab8e8f2d8f368e9",
  "fb5c90d53f13af8a", "fd93b37cefe2657c", "ff19ac7baafa85a0", "ff76028908ce821b",
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
