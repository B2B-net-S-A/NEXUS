/**
 * Notatka z pytaniami klienta → podpowiedź „Zapisz jako pytania z rozmowy”
 * (20.10.2026).
 *
 * Do tej daty pytania z rozmowy u klienta trafiały głównie do notatek: przy
 * 25 parach w 30 dniach ktoś po rozmowie napisał „klient pytał o…”, a bank
 * pytań klienta dostał 8 pytań w dwa tygodnie. Notatka zostaje notatką — ta
 * reguła tylko rozpoznaje taki tekst i wyjmuje z niego listę pytań do okna
 * pytań, gdzie rekruter ją poprawia przed zapisem. Bez AI: zgadujemy szkic,
 * nie piszemy za człowieka.
 */

import { MAX_DEBRIEF_QUESTIONS, splitPastedQuestions } from "@/lib/interview-cycle";

const ASKED = /pyta\p{L}*/iu;
// `\b` w JS zna tylko litery ASCII („rozmową” nie ma granicy po „ą”), więc
// granice słowa to zaglądanie na litery Unicode.
const CONTEXT =
  /(?<!\p{L})(klient\p{L}*|rozmow\p{L}*|interview\p{L}*|spotkani\p{L}*|techniczn\p{L}*|manager\p{L}*|HM)(?!\p{L})/iu;
// „Klient pytał o:”, „pytania:”, „pytali o” — wszystko po tym to pytania.
const ASKED_LEAD = /pyta\p{L}*\s*(?:o(?!\p{L}))?\s*:?\s*/iu;

/** Czy notatka wygląda na pytania klienta z rozmowy. */
export function looksLikeClientQuestions(text: string): boolean {
  const value = text.trim();
  if (!value) return false;
  if (ASKED.test(value) && CONTEXT.test(value)) return true;
  // Sama lista pytań („Jak…? Czy…?”) bez słowa „pytał”.
  return (value.match(/\?/g) ?? []).length >= 2 && CONTEXT.test(value);
}

function tidy(segment: string): string {
  const text = segment.replace(/\s+/g, " ").trim().replace(/[.;,]+$/u, "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

/** Szkic listy pytań z notatki — do poprawienia w oknie pytań. */
export function extractClientQuestions(text: string): string[] {
  const value = text.trim();
  if (!value) return [];
  const lead = value.match(ASKED_LEAD);
  let body = lead && lead.index != null ? value.slice(lead.index + lead[0].length) : value;

  let segments: string[];
  if (/\r?\n/.test(body.trim())) {
    // Lista w liniach — numery i punktory zdejmuje ta sama reguła co wklejka.
    segments = splitPastedQuestions(body);
  } else {
    // Jedno zdanie po „pytał o:” — kończy je pierwsza kropka przed wielką
    // literą („…Kubernetesem. Kandydatka zadowolona.”).
    if (lead) body = body.split(/\.\s+(?=\p{Lu})/u)[0];
    segments = body.split(/\?\s+|;\s*|•/u).flatMap((part) => {
      const trimmed = part.trim();
      // „o Spring Boot, o Kafkę, o Kubernetesa” — przecinki dzielą tylko listę
      // bez pytajników (zdanie z „?” jest już pytaniem).
      return lead && !trimmed.includes("?") ? trimmed.split(/,\s+/u) : [trimmed];
    });
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of segments) {
    const q = tidy(raw);
    const key = q.toLowerCase();
    if (q.length < 3 || seen.has(key)) continue;
    seen.add(key);
    out.push(q);
    if (out.length >= MAX_DEBRIEF_QUESTIONS) break;
  }
  return out;
}
