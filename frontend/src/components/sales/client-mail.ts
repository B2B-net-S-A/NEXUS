import type { ClientMailDraft } from "@/lib/api/sales";

const ADDRESS = /^[^@\s<>,;"']+@[^@\s<>,;"']+\.[^@\s<>,;"']+$/;
const MONEY = /\d[\d\s.,]*\s?(?:zł|pln|eur|€|usd|\$|tys\.?|k\b)/gi;
const INTERNAL_WORDS = /(?<!\p{L})(?:(?:stawk|marż|rabat|cennik|wewnętrzn)\p{L}*|między nami)/giu;
const MAX_FRAGMENTS = 5;

/** Adres w tej samej postaci co na serwerze; `null`, gdy to nie adres. */
export function normalizeAddress(value: string): string | null {
  const address = value.trim().toLowerCase();
  return ADDRESS.test(address) && address.length <= 320 ? address : null;
}

/** Adresy wpisane w pole (po przecinku, średniku albo spacji) i te, których nie da się wysłać. */
export function parseAddresses(input: string): { valid: string[]; invalid: string[] } {
  const valid: string[] = [];
  const invalid: string[] = [];
  for (const part of input.split(/[\s,;]+/)) {
    if (!part) continue;
    const address = normalizeAddress(part);
    if (address === null) invalid.push(part);
    else if (!valid.includes(address)) valid.push(address);
  }
  return { valid, invalid };
}

/** Domyślni adresaci: uczestnicy spoza firmy, bez osób z bazy kandydatów. */
export function initialRecipients(draft: Pick<ClientMailDraft, "recipients">): string[] {
  return draft.recipients.filter((recipient) => !recipient.blocked).map((recipient) => recipient.address);
}

/**
 * Fragmenty, które nie powinny trafić do klienta: kwoty i słowa o stawkach, marżach
 * albo sprawach wewnętrznych. Ostrzeżenie, nie blokada — handlowiec decyduje.
 * „Kandydaci” nie ostrzegają: ogólne „prześlemy propozycję kandydatów” to zalecany
 * przez prompt zwrot, a nazwisk wyrażenie i tak nie rozpozna.
 */
export function riskyFragments(text: string): string[] {
  const found = [...text.matchAll(MONEY), ...text.matchAll(INTERNAL_WORDS)].map((match) =>
    match[0].trim(),
  );
  return [...new Set(found)].slice(0, MAX_FRAGMENTS);
}

/** Klucz jednej wysyłki: drugi klik z tym samym kluczem nie wysyła drugiego maila. */
export function newRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const hex = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20)}`;
}
