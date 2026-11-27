/**
 * Grafika i treść posta na LinkedInie (prośba Olafa, decyzja Artura 27.11.2026:
 * warianty „Mapa”, „Konkrety” i karuzela). Strategia zespołu: grafika w poście,
 * link do aplikacji w pierwszym komentarzu — dlatego grafika nie udaje przycisku,
 * tylko mówi, gdzie jest link.
 *
 * Wszystko z publicznej odpowiedzi strony kariery (`GET /api/public/career/r/<slug>`,
 * opublikowana wersja opisu) i tablicy — bez klienta, stawek i nazwiska. Te same
 * czyste funkcje czyta trasa grafiki (`kariera/r/[slug]/grafika-posta`) i zakładka
 * „Post na LinkedIn” w oknie „Udostępnij”.
 */
import { processSteps } from "@/components/career/requirementItems";

import type { CareerBoardJob, CareerJobResponse } from "./api";
import { offerFocusSvg, remoteSvg, type MapSvg } from "./mapSvg";
import { offerOgLine, offerOgSub } from "./ogText";
import { officeNote, offerMapMode } from "./polandMap";
import { bigWord, boardCardFor, facetCounts, jobCities, offerTags } from "./site";

export type PostVariant = "mapa" | "konkrety" | "karuzela";
export const POST_VARIANTS: readonly PostVariant[] = ["mapa", "konkrety", "karuzela"];

export function isPostVariant(value: string | null | undefined): value is PostVariant {
  return value === "mapa" || value === "konkrety" || value === "karuzela";
}

export type PostMap =
  | { kind: "focus"; map: MapSvg; lit: { x: number; base: number; height: number }[]; cities: string; note: string | null }
  | { kind: "remote"; map: MapSvg }
  | { kind: "none" };

/** Slajdy karuzeli — tylko te, które mają treść; okładka i zakończenie zawsze. */
export type CarouselSlide = "cover" | "duties" | "must" | "apply";

export interface PostData {
  /** Plakietki technologii z tablicy (jak w grafice OG). */
  tags: string[];
  /** Wielkie słowo wariantu „Konkrety” (krótka umiejętność z tablicy). */
  word: string | null;
  title: string;
  /** „Warszawa · hybryda · B2B”. */
  line: string | null;
  /** „Czas projektu: … · prowadzi Maciej”. */
  sub: string | null;
  map: PostMap;
  host: string;
  /** Punkty „Czym się zajmiesz” z opisu. */
  duties: string[];
  /** Wymagania (zdania z opisu publicznego), gdy sekcja jest pokazana. */
  must: string[];
  nice: string[];
  /** Krótkie nazwy technologii z tablicy do plakietek i hashtagów. */
  skills: string[];
  /** Kroki procesu jak na stronie oferty; puste, gdy sekcja jest ukryta. */
  steps: { title: string; note: string }[];
  subtitle: string | null;
  /** Podpis biura („biuro 4 dni w miesiącu”) do treści posta. */
  office: string | null;
}

export const POST_DUTY_MAX = 80;

/** „Czym się zajmiesz: a; b; c.” z opisu → punkty, ucięte na granicy słowa. */
export function postDuties(about: string | null | undefined, max = POST_DUTY_MAX): string[] {
  const m = (about ?? "").match(/Czym się zajmiesz:\s*([^\n]+)/i);
  if (!m) return [];
  return m[1]
    .split(/;\s*/)
    .map((t) => t.trim().replace(/[.;]+$/, ""))
    .filter(Boolean)
    .map((t) => (t.length > max ? `${t.slice(0, max).replace(/\s+\S*$/, "").replace(/[,:;–-]+$/, "")}…` : t));
}

/**
 * Dane grafiki z publicznej odpowiedzi i tablicy. `null`, gdy rekrutacja jest
 * zamknięta — do zamkniętej nie robimy posta.
 */
export function buildPostData(
  res: CareerJobResponse,
  boardJobs: readonly CareerBoardJob[],
  host: string,
  slug?: string,
): PostData | null {
  if (res.status !== "open") return null;
  const job = res.job;
  const show = job.show;
  // Parametry ukryte przełącznikiem „pokaż” nie trafiają do grafiki (jak w OG).
  const p = show?.params !== false ? job.params : null;
  const card = boardCardFor(boardJobs, [res.canonical_slug ?? "", (slug ?? job.slug).toLowerCase()]);
  const mode = offerMapMode("open", p, (city) => jobCities({ city }));
  let map: PostMap = { kind: "none" };
  if (mode.kind === "remote") map = { kind: "remote", map: remoteSvg() };
  else if (mode.kind === "focus") {
    const focus = offerFocusSvg(facetCounts(boardJobs), mode.cities);
    map = { kind: "focus", map: focus, lit: focus.lit, cities: mode.cities.join(", "), note: officeNote(p) };
  }
  const word = bigWord(card);
  const firstName = res.recruiter.first_name ?? "";
  return {
    tags: offerTags(word, card?.must ?? []),
    word,
    title: job.title.trim(),
    line: offerOgLine(p),
    sub: offerOgSub(p, firstName),
    map,
    host,
    duties: postDuties(job.about),
    must: show?.must === false ? [] : job.must.map((m) => m.name.trim()).filter(Boolean),
    nice: show?.nice === false ? [] : (job.nice ?? []).map((n) => n.trim()).filter(Boolean),
    skills: (card?.must ?? []).map((s) => s.trim()).filter((s) => s.length > 0 && s.length <= 22),
    steps: show?.process === false ? [] : processSteps(firstName, p?.contract),
    subtitle: job.subtitle?.trim() || null,
    office: officeNote(p),
  };
}

export function carouselSlides(d: PostData): CarouselSlide[] {
  const slides: CarouselSlide[] = ["cover"];
  if (d.duties.length) slides.push("duties");
  if (d.must.length) slides.push("must");
  slides.push("apply");
  return slides;
}

const HASHTAG_MAP: Record<string, string> = { "c#": "csharp", ".net": "dotnet", "c++": "cpp", "f#": "fsharp", "node.js": "nodejs" };

/** „REST API” → `#restapi`, „C#” → `#csharp`; litery spoza alfabetu łacińskiego zostają. */
export function hashtag(skill: string): string | null {
  const key = skill.trim().toLocaleLowerCase("pl-PL");
  const mapped = HASHTAG_MAP[key] ?? key.replace(/[^\p{L}\p{N}]+/gu, "");
  if (mapped.length < 2 || /^\d+$/.test(mapped)) return null;
  return `#${mapped}`;
}

export function postHashtags(skills: readonly string[], max = 4): string[] {
  const tags: string[] = [];
  for (const s of skills) {
    const t = hashtag(s);
    if (t && !tags.includes(t)) tags.push(t);
    if (tags.length >= max) break;
  }
  return [...tags, "#praca", "#b2b"];
}

/**
 * Treść posta: tytuł, gdzie i jak, zdanie o projekcie, technologie, gdzie jest
 * link. Szablon bez modelu AI — tylko pola, które przeszły kontrolę publikacji.
 */
export function postText(d: PostData): string {
  const where = [d.line, d.office ? `(${d.office})` : null].filter(Boolean).join(" ");
  const blocks = [
    [`Nowa rekrutacja: ${d.title}`, where].filter(Boolean).join("\n"),
    d.subtitle ? (/[.!?…]$/.test(d.subtitle) ? d.subtitle : `${d.subtitle}.`) : null,
    d.skills.length ? `Czego szukamy: ${d.skills.slice(0, 5).join(", ")}.` : null,
    "Link do aplikacji w pierwszym komentarzu ↓ Wystarczy samo CV.",
    postHashtags(d.skills).join(" "),
  ];
  return blocks.filter(Boolean).join("\n\n");
}

export function postComment(url: string): string {
  return `Aplikuj tutaj: ${url}`;
}

/** Adres grafiki na tej samej domenie (aplikacja albo kariera — obie przepuszczają `/kariera/*`). */
export function postGraphicPath(slug: string, variant: PostVariant, slide = 1): string {
  const base = `/kariera/r/${encodeURIComponent(slug)}/grafika-posta?v=${variant}`;
  return variant === "karuzela" ? `${base}&s=${slide}` : base;
}

/** Odpowiedź `…/grafika-posta/dane` dla zakładki „Post na LinkedIn”. */
export interface PostDataResponse {
  post: PostData;
  text: string;
  slides: CarouselSlide[];
}

export function postDataPath(slug: string): string {
  return `/kariera/r/${encodeURIComponent(slug)}/grafika-posta/dane`;
}

export const postDataQueryKey = (slug: string | null) => ["career-post-graphic", slug] as const;
