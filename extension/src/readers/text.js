// Czytniki zrzutu tekstu (główna ścieżka). Zrzut buduje `capturePage`
// (src/page.js) z `innerText` żywej strony:
//   {url, heading: {text, level}, top: {lines}, sections: [{heading, lines, items}],
//    listItems: [{lines, links}], links: [{href, text, label, foreign, inTop}]}
// Wszystko tu to czyste funkcje — testy w node na syntetycznych zrzutach.

import {
  CONTACT_INFO,
  CURRENT_PREFIX,
  EMPLOYMENT_TYPE_WORDS,
  EMPLOYMENT_TYPES,
  NOISE_LINES,
  PAST_PREFIX,
  PUBLIC_LINK_LABELS,
  SECTION_HEADINGS,
  UNKNOWN_MEMBER,
} from "./selectors.js";
import { clean, publicUrlFromSlug, slugContradictsName, slugFromHref } from "./dom.js";
import { isDateLine, isDurationLine, parseDateRange } from "./dates.js";
import { companyFromLine } from "./experience.js";
import { missingFields, splitTitleCompany } from "./profile.js";

export function isNoiseLine(line) {
  const t = clean(line);
  if (!t || NOISE_LINES.some((re) => re.test(t))) return true;
  // „She/Her · 2nd” w jednej linii: każdy kawałek to szum.
  const parts = t.split(/\s*[·•]\s*/).filter(Boolean);
  return parts.length > 1 && parts.every((p) => NOISE_LINES.some((re) => re.test(p)));
}

/** „Full-time · 3 yrs 2 mos”, „3 yrs 2 mos”, „Pełny etat” — bez dat, sam czas/forma. */
export function isDurationOrTypeLine(line) {
  const parts = clean(line)
    .split("·")
    .map((p) => p.trim())
    .filter(Boolean);
  return parts.length > 0 && !isDateLine(line) && parts.every((p) => isDurationLine(p) || EMPLOYMENT_TYPE_WORDS.test(p));
}

function cleanName(text) {
  return clean(text)
    .replace(/\s*[·•]\s*(1st|2nd|3rd\+?|1\.|2\.|3\.\+?)\s*$/i, "")
    .replace(/^(View|Zobacz)\s+/i, "")
    .replace(/[’']s profile$/i, "")
    .trim();
}

function headingMatches(heading, names) {
  const t = clean(heading).toLowerCase();
  return names.some((n) => t === n.toLowerCase() || t.startsWith(`${n.toLowerCase()} `));
}

export function findTextSection(snapshot, name) {
  return (snapshot?.sections || []).find((s) => headingMatches(s.heading, SECTION_HEADINGS[name])) || null;
}

/** Linie sekcji bez nagłówka i bez szumu. */
function bodyLines(section, lines = section.lines) {
  const heading = clean(section.heading);
  return (lines || []).map(clean).filter((l) => l && l !== heading && !isNoiseLine(l));
}

// ── Doświadczenie ───────────────────────────────────────────────────────────

function entry(title, company, dateLine) {
  const range = dateLine ? parseDateRange(dateLine) : null;
  return {
    title: title || null,
    company: company || null,
    start: range?.start ?? null,
    end: range?.end ?? null,
    current: range?.current ?? false,
  };
}

/** Stanowisko nad linią dat: pomija linię samej formy zatrudnienia („Full-time”). */
function titleAbove(lines, dateIdx, floor) {
  let j = dateIdx - 1;
  while (j >= floor && isDurationOrTypeLine(lines[j])) j -= 1;
  return j >= floor && !isDateLine(lines[j]) ? lines[j] : null;
}

/**
 * Jedna pozycja (lista linii między separatorami <hr>):
 *  - zwykła: [stanowisko, „Firma · Full-time”, „May 2023 - Present · 3 yrs”, miasto, opis…]
 *  - grupowa: [firma, „Full-time · 3 yrs 2 mos”, stanowisko 1, daty 1, miasto, stanowisko 2, daty 2…]
 */
export function parseExperienceItem(rawLines, heading = "") {
  const lines = rawLines.map(clean).filter((l) => l && l !== clean(heading) && !isNoiseLine(l));
  if (!lines.length) return [];
  if (lines.length > 1 && isDurationOrTypeLine(lines[1])) {
    const company = companyFromLine(lines[0]) || lines[0];
    const roles = [];
    for (let i = 2; i < lines.length; i += 1) {
      if (isDateLine(lines[i])) roles.push(entry(titleAbove(lines, i, 2), company, lines[i]));
    }
    return roles.length ? roles : [entry(null, company, null)];
  }
  const dateIdx = lines.findIndex(isDateLine);
  if (dateIdx === 0) return [entry(null, null, lines[0])];
  const title = lines[0];
  const company = dateIdx === 1 ? null : companyFromLine(lines[1]);
  return [entry(title, company, dateIdx > 0 ? lines[dateIdx] : null)];
}

/** Zapas bez <hr>: cała sekcja jako lista linii, pozycje kotwiczone na liniach dat. */
export function parseExperienceFlat(rawLines, heading = "") {
  const lines = rawLines.map(clean).filter((l) => l && l !== clean(heading) && !isNoiseLine(l));
  const out = [];
  let prevDate = -1;
  let groupCompany = null;
  for (let d = 0; d < lines.length; d += 1) {
    if (!isDateLine(lines[d])) continue;
    const chunk = lines.slice(prevDate + 1, d);
    const typeIdx = chunk.findIndex(isDurationOrTypeLine);
    if (typeIdx > 0 && typeIdx < chunk.length - 1) groupCompany = companyFromLine(chunk[typeIdx - 1]) || chunk[typeIdx - 1];
    const before = chunk.filter((l) => !isDurationOrTypeLine(l));
    const last = before[before.length - 1] || null;
    const secondLast = before[before.length - 2] || null;
    if (last && EMPLOYMENT_TYPES.test(last)) {
      out.push(entry(secondLast, companyFromLine(last), lines[d]));
      groupCompany = null;
    } else if (groupCompany) {
      out.push(entry(last, groupCompany, lines[d]));
    } else if (secondLast && prevDate < 0) {
      out.push(entry(secondLast, companyFromLine(last), lines[d]));
    } else {
      out.push(entry(last, null, lines[d]));
    }
    prevDate = d;
  }
  return out;
}

export function readExperienceText(snapshot) {
  const section = findTextSection(snapshot, "experience");
  if (!section) return [];
  if (section.items?.length) {
    const out = section.items.flatMap((item) => parseExperienceItem(item, section.heading));
    if (out.some((e) => e.start)) return out.filter((e) => e.title || e.company);
  }
  return parseExperienceFlat(section.lines || [], section.heading).filter((e) => e.title || e.company);
}

// ── Umiejętności, informacje ────────────────────────────────────────────────

export function readSkillsText(snapshot) {
  const section = findTextSection(snapshot, "skills");
  if (!section) return [];
  const candidates = section.items?.length ? section.items.map((item) => bodyLines(section, item)[0]).filter(Boolean) : bodyLines(section);
  const out = [];
  for (const s of candidates) {
    if (s.length > 60 || isDateLine(s)) continue;
    if (!out.some((x) => x.toLowerCase() === s.toLowerCase())) out.push(s);
  }
  return out.slice(0, 30);
}

export function readAboutText(snapshot) {
  const section = findTextSection(snapshot, "about");
  if (!section) return "";
  return bodyLines(section).join("\n").slice(0, 4000);
}

// ── Karta górna ─────────────────────────────────────────────────────────────

/**
 * Zmierzone linie karty górnej profilu:
 * [„Enhance cover image”, imię, (zaimki), („· 2nd”), nagłówek, miasto, „·”,
 *  „Contact info”, firma obecna, uczelnia, „500+ connections”, przyciski…]
 */
export function parseTopCard(snapshot) {
  const name = cleanName(snapshot?.heading?.text || "");
  const lines = (snapshot?.top?.lines || []).map(clean).filter(Boolean);
  const i = name ? lines.findIndex((l) => cleanName(l) === name) : -1;
  const after = i >= 0 ? lines.slice(i + 1) : lines;
  const ci = after.findIndex((l) => CONTACT_INFO.test(l));
  const beforeContact = ci >= 0 ? after.slice(0, ci) : after;
  const meaningful = beforeContact.filter((l) => !isNoiseLine(l) && cleanName(l) !== name);

  const headline = meaningful[0] || "";
  // Miasto = ostatnia sensowna linia przed „Contact info”, o ile nie jest nagłówkiem.
  // Bez „Contact info” (Recruiter — niezmierzony): druga linia, jeśli wygląda na „Miasto, region”.
  const guessed = ci < 0 && meaningful[1] && /,/.test(meaningful[1]) && !/\s(at|@|w)\s/.test(meaningful[1]) ? meaningful[1] : "";
  const location = ci >= 0 && meaningful.length > 1 ? meaningful[meaningful.length - 1] : guessed;
  const companyAfterContact = ci >= 0 ? after.slice(ci + 1).find((l) => !isNoiseLine(l)) || "" : "";
  return { name: name || (i < 0 ? "" : name), headline, location, companyAfterContact };
}

// ── Profil publiczny ────────────────────────────────────────────────────────

export function readProfileText(snapshot, url) {
  const top = parseTopCard(snapshot);
  const experience = readExperienceText(snapshot);
  const current = experience.find((e) => e.current) || null;
  const fromHeadline = splitTitleCompany(top.headline);
  const profile = {
    page_kind: "profile",
    page_url: url,
    public_url: publicUrlFromSlug(slugFromHref(url)),
    full_name: top.name || null,
    headline: top.headline || null,
    location: top.location || null,
    current_company: current?.company || top.companyAfterContact || fromHeadline.company || null,
    current_title: current?.title || fromHeadline.title || null,
    experience,
    skills: readSkillsText(snapshot),
    about: readAboutText(snapshot) || null,
  };
  return { profile, missing: missingFields(profile) };
}

// ── Recruiter (niezmierzony — to samo podejście tekstowe) ───────────────────

export function publicUrlFromLinks(links, fullName) {
  const accept = (href) => {
    const slug = slugFromHref(href);
    return slug && !slugContradictsName(slug, fullName) ? publicUrlFromSlug(slug) : null;
  };
  const labels = PUBLIC_LINK_LABELS.map((l) => l.toLowerCase());
  const all = (links || []).filter((l) => slugFromHref(l.href));
  const labelled = all.find((l) => labels.some((x) => `${l.text} ${l.label}`.toLowerCase().includes(x)));
  if (labelled) return accept(labelled.href);
  const uniq = (list) => [...new Set(list.map((l) => slugFromHref(l.href)))];
  const inTop = uniq(all.filter((l) => l.inTop && !l.foreign));
  if (inTop.length === 1) return accept(`/in/${inTop[0]}`);
  const wide = uniq(all.filter((l) => !l.foreign));
  return wide.length === 1 ? accept(`/in/${wide[0]}`) : null;
}

export function readRecruiterText(snapshot, url) {
  const top = parseTopCard(snapshot);
  const experience = readExperienceText(snapshot);
  const current = experience.find((e) => e.current) || null;
  const fromHeadline = splitTitleCompany(top.headline);
  const profile = {
    page_kind: "recruiter_profile",
    page_url: url,
    public_url: publicUrlFromLinks(snapshot.links, top.name),
    full_name: top.name || null,
    headline: top.headline || null,
    location: top.location || null,
    current_company: current?.company || fromHeadline.company || null,
    current_title: current?.title || fromHeadline.title || null,
    experience,
    skills: readSkillsText(snapshot),
    about: readAboutText(snapshot) || null,
  };
  return { profile, missing: missingFields(profile) };
}

// ── Lista wyników ───────────────────────────────────────────────────────────

/**
 * Zmierzona pozycja wyników (search/results/people):
 * [imię, („• 2nd”), nagłówek, miasto, „Connect”|„Message”|„Follow”,
 *  („Current: Java Developer at Firma”), („X is a mutual connection”)]
 */
export function parseListItem(item) {
  const lines = (item.lines || []).map(clean).filter(Boolean);
  const fullName = cleanName(lines[0] || "");
  if (!fullName || UNKNOWN_MEMBER.test(fullName)) return null;
  const rest = lines.slice(1).filter((l) => !isNoiseLine(l) && cleanName(l) !== fullName);
  const currentLine = rest.find((l) => CURRENT_PREFIX.test(l)) || "";
  const plain = rest.filter((l) => !CURRENT_PREFIX.test(l) && !PAST_PREFIX.test(l) && !/^(Summary|Podsumowanie)\s*:/i.test(l));
  const headline = plain[0] || "";
  const location = plain[1] || "";
  const fromCurrent = splitTitleCompany(currentLine.replace(CURRENT_PREFIX, ""));
  const fromHeadline = splitTitleCompany(headline);
  const slug = (item.links || []).map(slugFromHref).find(Boolean);
  const person = {
    full_name: fullName,
    public_url: publicUrlFromSlug(slug),
    headline: headline || null,
    current_company: fromCurrent.company || fromHeadline.company || null,
    location: location || null,
  };
  person.missing = ["headline", "current_company"].filter((f) => !person[f]);
  return person;
}

export function readListText(snapshot, max) {
  const people = [];
  let skipped = 0;
  for (const item of snapshot?.listItems || []) {
    const p = parseListItem(item);
    if (!p) {
      skipped += 1;
      continue;
    }
    const dup = people.some((q) => (p.public_url && q.public_url === p.public_url) || (!p.public_url && q.full_name === p.full_name && q.headline === p.headline));
    if (!dup) people.push(p);
  }
  return { people: people.slice(0, max), truncated: people.length > max, skipped };
}
