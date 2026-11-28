/**
 * ALTCHA — zagadka proof-of-work zamiast CAPTCHY na anonimowych formularzach
 * zgłoszeń (strona kariery, `/apply/[token]`). Decyzja Artura z 28.11.2026,
 * pakiet „Ochrona wejścia”; reguła `docs/claude/podstawy/skan-plikow-i-altcha.md`.
 *
 * Przeglądarka pobiera wyzwanie z `GET /api/public/career/challenge` i liczy
 * SHA-256(salt + liczba), aż trafi skrót z wyzwania. Bez ciasteczek, bez
 * zewnętrznego skryptu, bez danych osoby. Kandydat niczego nie klika: liczenie
 * rusza przy pierwszym dotknięciu formularza (`warmAltcha`), a wysyłka bierze
 * gotowe rozwiązanie (`takeAltchaPayload`). Jedno rozwiązanie = jedna wysyłka
 * (serwer odrzuca powtórkę), więc po wzięciu następne liczy się od nowa.
 *
 * Format zgodny z protokołem ALTCHA v1 (backend: `app/services/altcha.py`).
 */

export interface AltchaChallenge {
  algorithm: "SHA-256";
  challenge: string;
  maxnumber: number;
  salt: string;
  signature: string;
}

export type Digest = (text: string) => Promise<string>;

const encoder = new TextEncoder();

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", encoder.encode(text));
  let out = "";
  for (const byte of new Uint8Array(buf)) out += byte.toString(16).padStart(2, "0");
  return out;
}

/** Liczba, dla której SHA-256(salt + liczba) = challenge; `null` = brak w zakresie. */
export async function solveChallenge(
  challenge: AltchaChallenge,
  digest: Digest = sha256Hex,
): Promise<number | null> {
  for (let n = 0; n <= challenge.maxnumber; n += 1) {
    if ((await digest(`${challenge.salt}${n}`)) === challenge.challenge) return n;
  }
  return null;
}

function isChallenge(value: unknown): value is AltchaChallenge {
  if (!value || typeof value !== "object") return false;
  const c = value as Record<string, unknown>;
  return (
    c.algorithm === "SHA-256" &&
    typeof c.challenge === "string" &&
    typeof c.salt === "string" &&
    typeof c.signature === "string" &&
    typeof c.maxnumber === "number" &&
    c.maxnumber > 0 &&
    c.maxnumber <= 10_000_000
  );
}

/** Termin ważności z soli (`…?expires=<unix>`), w milisekundach; 0 = nieznany. */
export function expiresAt(salt: string): number {
  const query = salt.split("?")[1] ?? "";
  const value = Number(new URLSearchParams(query).get("expires"));
  return Number.isFinite(value) && value > 0 ? value * 1000 : 0;
}

export class AltchaUnavailable extends Error {}

interface Prepared {
  payload: string;
  expiresMs: number;
}

// Zapas na wysyłkę dużego CV po wolnym łączu.
const EXPIRY_MARGIN_MS = 2 * 60 * 1000;

async function prepare(apiBase: string): Promise<Prepared> {
  let res: Response;
  try {
    res = await fetch(`${apiBase}/api/public/career/challenge`, { cache: "no-store" });
  } catch {
    throw new AltchaUnavailable("network");
  }
  if (!res.ok) throw new AltchaUnavailable(`status ${res.status}`);
  const challenge: unknown = await res.json().catch(() => null);
  if (!isChallenge(challenge)) throw new AltchaUnavailable("shape");
  const started = Date.now();
  const number = await solveChallenge(challenge);
  if (number === null) throw new AltchaUnavailable("unsolved");
  const payload = btoa(
    JSON.stringify({
      algorithm: challenge.algorithm,
      challenge: challenge.challenge,
      number,
      salt: challenge.salt,
      signature: challenge.signature,
      took: Date.now() - started,
    }),
  );
  return { payload, expiresMs: expiresAt(challenge.salt) };
}

let pending: Promise<Prepared> | null = null;

/** Zacznij liczyć w tle (idempotentne). Wołać przy pierwszym dotknięciu formularza. */
export function warmAltcha(apiBase: string): void {
  if (pending) return;
  const job = prepare(apiBase);
  pending = job;
  // Nieudane przygotowanie nie zostaje w pamięci — wysyłka spróbuje od nowa.
  job.catch(() => {
    if (pending === job) pending = null;
  });
}

/** Rozwiązanie do jednej wysyłki. Rzuca `AltchaUnavailable`, gdy nie da się go policzyć. */
export async function takeAltchaPayload(apiBase: string): Promise<string> {
  const job = pending ?? prepare(apiBase);
  pending = null;
  let ready: Prepared;
  try {
    ready = await job;
  } catch {
    ready = await prepare(apiBase);
  }
  if (ready.expiresMs && ready.expiresMs - Date.now() < EXPIRY_MARGIN_MS) {
    ready = await prepare(apiBase);
  }
  return ready.payload;
}

/** Tylko testy: czyści rozwiązanie w pamięci modułu. */
export function resetAltchaForTests(): void {
  pending = null;
}
