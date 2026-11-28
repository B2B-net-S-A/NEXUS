import { createHash } from "node:crypto";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  expiresAt,
  resetAltchaForTests,
  solveChallenge,
  takeAltchaPayload,
  warmAltcha,
  type AltchaChallenge,
} from "@/lib/altcha";

const sha = (text: string) => createHash("sha256").update(text).digest("hex");

/** Wyzwanie jak z `app/services/altcha.py` (podpis nieistotny dla przeglądarki). */
function challenge(number: number, expiresInS = 1800, maxnumber = 300): AltchaChallenge {
  const salt = `abc123?expires=${Math.floor(Date.now() / 1000) + expiresInS}`;
  return { algorithm: "SHA-256", challenge: sha(`${salt}${number}`), maxnumber, salt, signature: "f".repeat(64) };
}

const fetchMock = vi.fn();
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as unknown as Response;
const decode = (payload: string) => JSON.parse(atob(payload)) as Record<string, unknown>;

beforeEach(() => {
  resetAltchaForTests();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("solveChallenge", () => {
  it("znajduje liczbę tą samą funkcją SHA-256 co serwer (WebCrypto)", async () => {
    expect(await solveChallenge(challenge(137))).toBe(137);
  });

  it("zwraca null, gdy liczby nie ma w zakresie", async () => {
    expect(await solveChallenge({ ...challenge(5), maxnumber: 3 })).toBeNull();
  });
});

describe("expiresAt", () => {
  it("czyta termin z soli i odporny jest na brak", () => {
    expect(expiresAt("x?expires=1700000000")).toBe(1_700_000_000_000);
    expect(expiresAt("bez-terminu")).toBe(0);
  });
});

describe("warmAltcha + takeAltchaPayload", () => {
  it("liczy w tle raz i oddaje rozwiązanie w formacie ALTCHA v1", async () => {
    const c = challenge(42);
    fetchMock.mockResolvedValue(ok(c));

    warmAltcha("http://api");
    warmAltcha("http://api");
    const payload = await takeAltchaPayload("http://api");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://api/api/public/career/challenge");
    expect(decode(payload)).toMatchObject({
      algorithm: "SHA-256",
      challenge: c.challenge,
      number: 42,
      salt: c.salt,
      signature: c.signature,
    });
  });

  it("jedno rozwiązanie = jedna wysyłka: następna pobiera nowe wyzwanie", async () => {
    fetchMock.mockResolvedValueOnce(ok(challenge(1))).mockResolvedValueOnce(ok(challenge(2)));
    const first = await takeAltchaPayload("http://api");
    const second = await takeAltchaPayload("http://api");
    expect(decode(first).number).toBe(1);
    expect(decode(second).number).toBe(2);
  });

  it("wyzwanie bliskie wygaśnięcia liczy od nowa", async () => {
    fetchMock.mockResolvedValueOnce(ok(challenge(3, 30))).mockResolvedValueOnce(ok(challenge(4)));
    expect(decode(await takeAltchaPayload("http://api")).number).toBe(4);
  });

  it("nieudane przygotowanie w tle nie blokuje: wysyłka próbuje jeszcze raz", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline")).mockResolvedValueOnce(ok(challenge(7)));
    warmAltcha("http://api");
    expect(decode(await takeAltchaPayload("http://api")).number).toBe(7);
  });

  it("zła odpowiedź serwera = wyjątek (formularz pokazuje komunikat)", async () => {
    fetchMock.mockResolvedValue(ok({ algorithm: "MD5" }));
    await expect(takeAltchaPayload("http://api")).rejects.toThrow();
  });
});
