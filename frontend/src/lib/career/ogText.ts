/**
 * Teksty podglądu linku (Open Graph) strony kariery w języku A — tabela
 * z makiety OG-w-portalach (26.11.2026). Czyste funkcje: metadane stron
 * i grafiki biorą stąd te same zdania.
 */
import type { CareerJob, CareerJobParams } from "./api";
import { remoteLabel } from "./format";
import { jobCities, pluralForm } from "./site";

/** Pisownia marki „B2Bnetwork” (decyzja Artura 18.11.2026); makiety OG z 26.11 mają „B2B Network”. */
export const OG_BRAND = "B2Bnetwork";
export const OG_SITE_NAME = `${OG_BRAND} · Kariera`;
export const LIST_DESCRIPTION = "Projekty w bankowości, AI, danych i testach. Zdalnie, hybrydowo i w biurze.";

/** „101 otwartych rekrutacji IT”, „3 otwarte rekrutacje IT”, „1 otwarta rekrutacja IT”. */
export function openRecruitmentsIT(n: number): string {
  const f = pluralForm(n);
  if (f === "one") return "1 otwarta rekrutacja IT";
  return f === "few" ? `${n} otwarte rekrutacje IT` : `${n} otwartych rekrutacji IT`;
}

/** og:title listy; bez danych (awaria API) — bez liczby. */
export function listOgTitle(open: number | null): string {
  return open && open > 0 ? `${openRecruitmentsIT(open)} · ${OG_BRAND}` : `Otwarte rekrutacje IT · ${OG_BRAND}`;
}

/** Miejsce oferty do tytułu i grafiki: rozpoznane miasta (najwyżej dwa), inaczej pole miasta, gdy krótkie. */
export function offerPlace(params: Pick<CareerJobParams, "city"> | null): string | null {
  const raw = params?.city?.trim() ?? "";
  const cities = jobCities({ city: raw });
  if (cities.length > 0) return cities.length > 2 ? `${cities.slice(0, 2).join(", ")} +${cities.length - 2}` : cities.join(", ");
  return raw && raw.length <= 30 ? raw : null;
}

/** og:title oferty: „{stanowisko} · {miasto}, {tryb} · B2Bnetwork” albo „{stanowisko} · zdalnie · B2Bnetwork”. */
export function offerOgTitle(job: Pick<CareerJob, "title" | "params">): string {
  const p = job.params;
  const mode = remoteLabel(p?.remote_policy);
  if (p?.remote_policy === "remote") return `${job.title} · zdalnie · ${OG_BRAND}`;
  const where = [offerPlace(p), mode].filter(Boolean).join(", ");
  return where ? `${job.title} · ${where} · ${OG_BRAND}` : `${job.title} · ${OG_BRAND}`;
}

function sentence(text: string): string {
  const t = text.trim().replace(/\s+/g, " ");
  if (!t) return "";
  const cap = t.charAt(0).toLocaleUpperCase("pl-PL") + t.slice(1);
  return /[.!?…]$/.test(cap) ? cap : `${cap}.`;
}

/**
 * Opis oferty: zdanie o projekcie (podtytuł) i „B2B, {czas projektu}.” albo
 * „Zdalnie z całej Polski.”. Bez podtytułu — sam dopisek z parametrów.
 */
export function offerOgDescription(job: Pick<CareerJob, "subtitle" | "params">): string | null {
  const p = job.params;
  const about = sentence(job.subtitle ?? "");
  let tail = "";
  if (p?.remote_policy === "remote") tail = "Zdalnie z całej Polski.";
  else {
    const contract = p?.contract?.trim();
    const duration = p?.duration?.trim();
    tail = sentence([contract, duration].filter(Boolean).join(", "));
  }
  const out = [about, tail].filter(Boolean).join(" ");
  return out || null;
}

/** Linia pod tytułem grafiki: „Warszawa · hybryda · B2B”, „Zdalnie z całej Polski · B2B”. */
export function offerOgLine(params: CareerJobParams | null): string | null {
  if (!params) return null;
  const contract = params.contract?.trim() || null;
  if (params.remote_policy === "remote") return ["Zdalnie z całej Polski", contract].filter(Boolean).join(" · ");
  const parts = [offerPlace(params), remoteLabel(params.remote_policy), contract].filter(Boolean) as string[];
  return parts.length ? parts.join(" · ") : null;
}

/** Druga linia grafiki: czas projektu i imię prowadzącego (samo imię, jak na stronie). */
export function offerOgSub(params: CareerJobParams | null, recruiterFirstName: string): string | null {
  const duration = params?.duration?.trim();
  const short = duration && duration.length <= 40 ? duration : null;
  const name = recruiterFirstName.trim();
  const parts = [short ? `Czas projektu: ${short}` : null, name ? (short ? `prowadzi ${name}` : `Prowadzi ${name}`) : null];
  const out = parts.filter(Boolean).join(" · ");
  return out || null;
}
