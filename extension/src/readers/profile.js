// Czytnik profilu publicznego: linkedin.com/in/<slug>.

import { LIST_ITEMS, PROFILE, TITLE_COMPANY_SEPARATORS } from "./selectors.js";
import {
  clean,
  findSection,
  firstElement,
  firstText,
  inForeignRegion,
  mainRoot,
  publicUrlFromSlug,
  safeQueryAll,
  slugFromHref,
  textBlocks,
  topLevelItems,
  visibleText,
} from "./dom.js";
import { currentPosition, parseExperienceSection } from "./experience.js";

const PRONOUNS = /^\(?(he\/him|she\/her|they\/them|on\/jego|ona\/jej|oni\/ich)\)?$/i;
const CONTACT_INFO = /^(Contact info|Dane kontaktowe|Informacje kontaktowe)$/i;

/** Pierwszy `h1` w głównej treści poza nawigacją. */
export function firstHeading(root) {
  for (const h of safeQueryAll(root, "h1")) {
    if (inForeignRegion(h)) continue;
    const t = visibleText(h);
    if (t) return { el: h, text: t };
  }
  return null;
}

/** Bloki tekstu karty górnej występujące po imieniu (nagłówek, miasto…). */
function blocksAfterName(container, name) {
  const blocks = textBlocks(container);
  const i = blocks.indexOf(name);
  return (i >= 0 ? blocks.slice(i + 1) : blocks).filter((b) => b !== name && !PRONOUNS.test(b));
}

export function headlineHeuristic(container, name) {
  return blocksAfterName(container, name)[0] || "";
}

export function locationHeuristic(container, name) {
  const after = blocksAfterName(container, name);
  const i = after.findIndex((b) => CONTACT_INFO.test(b));
  if (i > 0) return after[i - 1].replace(/\s*·\s*$/, "");
  return "";
}

/** „Senior Java Developer at Comarch” → {title, company}. */
export function splitTitleCompany(text) {
  const t = clean(text);
  for (const sep of TITLE_COMPANY_SEPARATORS) {
    const parts = t.split(sep);
    if (parts.length === 2 && parts[0] && parts[1]) {
      return { title: parts[0].trim(), company: parts[1].split(/\s*[|·]\s*/)[0].trim() };
    }
  }
  return { title: null, company: null };
}

export function readSkills(doc, extraSelectors = []) {
  const out = [];
  const push = (s) => {
    const v = clean(s);
    if (v && v.length <= 60 && !out.some((x) => x.toLowerCase() === v.toLowerCase())) out.push(v);
  };
  for (const sel of extraSelectors) for (const el of safeQueryAll(doc, sel)) push(visibleText(el));
  if (out.length) return out;
  const section = findSection(doc, "skills");
  for (const item of topLevelItems(section, LIST_ITEMS)) {
    const first = textBlocks(item)[0];
    if (first) push(first);
  }
  return out;
}

export function readAbout(doc) {
  const section = findSection(doc, "about");
  if (!section) return "";
  const blocks = textBlocks(section).filter((b) => !/^(About|Informacje|O mnie|Summary|Podsumowanie)$/i.test(b));
  const longest = blocks.reduce((a, b) => (b.length > a.length ? b : a), "");
  return longest.slice(0, 4000);
}

function companyFromAria(root) {
  for (const sel of PROFILE.currentCompanyAria) {
    for (const el of safeQueryAll(root, sel)) {
      const label = clean(el.getAttribute?.("aria-label"));
      const name = label.replace(PROFILE.currentCompanyAriaPrefix, "").replace(PROFILE.currentCompanyAriaSuffix, "").trim();
      if (name && name !== label) return name;
    }
  }
  return "";
}

/**
 * @param {Document} doc
 * @param {string} url adres karty
 * @returns {{profile: object, missing: string[]}}
 */
export function readProfile(doc, url) {
  const main = mainRoot(doc);
  const top = firstElement(main, PROFILE.topCard) || main;
  const heading = firstHeading(top) || firstHeading(main);
  const fullName = firstText(top, PROFILE.name) || heading?.text || "";
  const container = heading?.el?.closest?.("section") || top;

  const headline = firstText(top, PROFILE.headline) || headlineHeuristic(container, fullName);
  const location = firstText(top, PROFILE.location) || locationHeuristic(container, fullName);
  const experience = parseExperienceSection(findSection(doc, "experience"));
  const current = currentPosition(experience);
  const fromHeadline = splitTitleCompany(headline);

  const currentCompany = companyFromAria(top) || current?.company || fromHeadline.company || "";
  const currentTitle = current?.title || fromHeadline.title || "";

  const profile = {
    page_kind: "profile",
    page_url: url,
    public_url: publicUrlFromSlug(slugFromHref(url)),
    full_name: fullName || null,
    headline: headline || null,
    location: location || null,
    current_company: currentCompany || null,
    current_title: currentTitle || null,
    experience,
    skills: readSkills(doc),
    about: readAbout(doc) || null,
  };
  return { profile, missing: missingFields(profile) };
}

const REQUIRED = ["full_name", "headline", "current_title", "current_company", "location"];

export function missingFields(profile) {
  const missing = REQUIRED.filter((f) => !profile[f]);
  if (!profile.experience?.length) missing.push("experience");
  if (!profile.skills?.length) missing.push("skills");
  if (!profile.public_url) missing.push("public_url");
  return missing;
}
