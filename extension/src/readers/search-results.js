// Czytnik list osób: wyniki wyszukiwania (search/results/people), wyszukiwanie
// w Recruiterze (talent/hire/…/discover/recruiterSearch) i lista projektu
// (talent/hire/…/manage). Odczyt tylko widocznych pozycji, najwyżej 50.

import { CURRENT_PREFIX, RESULTS, UNKNOWN_MEMBER } from "./selectors.js";
import {
  clean,
  firstText,
  inForeignRegion,
  isNoise,
  mainRoot,
  publicUrlFromSlug,
  safeQueryAll,
  slugFromHref,
  textBlocks,
  visibleText,
} from "./dom.js";
import { splitTitleCompany } from "./profile.js";

export const MAX_PEOPLE = 50;

function cleanName(text) {
  return clean(text)
    .replace(/\s*•\s*(1st|2nd|3rd\+?|1\.|2\.|3\.\+?).*$/i, "")
    .replace(/^(View|Zobacz)\s+/i, "")
    .replace(/[’']s profile$/i, "")
    .replace(/\s*(Status is|Status:).*$/i, "")
    .trim();
}

function findItems(main) {
  for (const sel of RESULTS.item) {
    const items = safeQueryAll(main, sel).filter((el) => !inForeignRegion(el));
    if (items.length) return items;
  }
  // Heurystyka: kontener (li/tr/article) wokół każdego linku do osoby.
  const out = [];
  for (const a of safeQueryAll(main, RESULTS.personLinks)) {
    if (inForeignRegion(a)) continue;
    const box = a.closest?.(RESULTS.itemContainers);
    if (box && !out.includes(box) && !out.some((o) => o.contains?.(box) || box.contains?.(o))) out.push(box);
  }
  return out;
}

function readItem(item) {
  const link = safeQueryAll(item, RESULTS.personLinks).find((a) => !inForeignRegion(a)) || null;
  const slug = safeQueryAll(item, "a[href*='/in/']")
    .map((a) => slugFromHref(a.getAttribute?.("href")))
    .find(Boolean);
  const fullName = cleanName(firstText(item, RESULTS.name) || (link ? visibleText(link) : ""));
  if (!fullName || UNKNOWN_MEMBER.test(fullName)) return null;

  const blocks = textBlocks(item)
    .map(cleanName)
    .filter((b) => b && b !== fullName && !isNoise(b));
  const headline = firstText(item, RESULTS.headline) || blocks[0] || "";
  const location = firstText(item, RESULTS.location) || "";
  const currentLine = clean(firstText(item, RESULTS.current)).replace(CURRENT_PREFIX, "");
  const fromCurrent = splitTitleCompany(currentLine);
  const fromHeadline = splitTitleCompany(headline);
  const company = fromCurrent.company || fromHeadline.company || null;

  const person = {
    full_name: fullName,
    public_url: publicUrlFromSlug(slug),
    headline: headline || null,
    current_company: company,
    location: location || null,
  };
  person.missing = ["headline", "current_company"].filter((f) => !person[f]);
  return person;
}

/**
 * @returns {{people: Array<object>, truncated: boolean, skipped: number}}
 * `skipped` = pozycje bez nazwiska („Członek LinkedIn”) — nie da się ich sprawdzić.
 */
export function readSearchResults(doc) {
  const main = mainRoot(doc);
  const people = [];
  let skipped = 0;
  for (const item of findItems(main)) {
    const p = readItem(item);
    if (!p) {
      skipped += 1;
      continue;
    }
    const dup = people.some((q) => (p.public_url && q.public_url === p.public_url) || (!p.public_url && q.full_name === p.full_name && q.headline === p.headline));
    if (!dup) people.push(p);
  }
  return { people: people.slice(0, MAX_PEOPLE), truncated: people.length > MAX_PEOPLE, skipped };
}
