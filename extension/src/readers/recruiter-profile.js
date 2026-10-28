// Czytnik profilu w LinkedIn Recruiter: talent/profile/… i talent/hire/…/profile/….
// URL strony nie zawiera publicznego /in/<slug>, więc szukamy linku
// „Profil publiczny” w karcie osoby — nigdy pierwszego lepszego /in/ w dokumencie
// (to bywa profil zalogowanego rekrutera z nawigacji albo „Inni oglądali też”).

import { RECRUITER } from "./selectors.js";
import {
  clean,
  findSection,
  firstElement,
  firstText,
  inForeignRegion,
  mainRoot,
  publicUrlFromSlug,
  safeQueryAll,
  slugContradictsName,
  slugFromHref,
} from "./dom.js";
import { parseDateRange } from "./dates.js";
import { currentPosition, parseExperienceSection } from "./experience.js";
import { firstHeading, headlineHeuristic, missingFields, readAbout, readSkills, splitTitleCompany } from "./profile.js";

function readPositions(root) {
  for (const sel of RECRUITER.position.item) {
    const items = safeQueryAll(root, sel);
    if (!items.length) continue;
    return items
      .map((item) => {
        const range = parseDateRange(firstText(item, RECRUITER.position.dates));
        return {
          title: firstText(item, RECRUITER.position.title) || null,
          company: clean(firstText(item, RECRUITER.position.company)).split(" · ")[0] || null,
          start: range?.start ?? null,
          end: range?.end ?? null,
          current: range?.current ?? false,
        };
      })
      .filter((p) => p.title || p.company);
  }
  return [];
}

function slugsFrom(anchors, { skipForeign }) {
  const out = [];
  for (const a of anchors) {
    if (skipForeign && inForeignRegion(a)) continue;
    const slug = slugFromHref(a.getAttribute?.("href"));
    if (slug && !out.includes(slug)) out.push(slug);
  }
  return out;
}

/** Link do profilu publicznego; null, gdy nie ma pewności. */
export function findPublicUrl(doc, container, fullName) {
  const accept = (slug) => (slug && !slugContradictsName(slug, fullName) ? publicUrlFromSlug(slug) : null);

  for (const sel of RECRUITER.publicLinkSelectors) {
    const hit = accept(slugsFrom(safeQueryAll(doc, sel), { skipForeign: false })[0]);
    if (hit) return hit;
  }
  const labels = RECRUITER.publicLinkLabels.map((l) => l.toLowerCase());
  const labelled = safeQueryAll(doc, "a[href*='/in/']").filter((a) => {
    const t = `${clean(a.textContent)} ${clean(a.getAttribute?.("aria-label"))} ${clean(a.getAttribute?.("title"))}`.toLowerCase();
    return labels.some((l) => t.includes(l));
  });
  const fromLabel = accept(slugsFrom(labelled, { skipForeign: false })[0]);
  if (fromLabel) return fromLabel;

  if (container) {
    const inCard = slugsFrom(safeQueryAll(container, "a[href*='/in/']"), { skipForeign: false });
    if (inCard.length === 1) {
      const hit = accept(inCard[0]);
      if (hit) return hit;
    }
  }
  // Szeroko tylko wtedy, gdy w treści jest dokładnie jeden kandydat na link.
  const wide = slugsFrom(safeQueryAll(mainRoot(doc), "a[href*='/in/']"), { skipForeign: true });
  return wide.length === 1 ? accept(wide[0]) : null;
}

export function readRecruiterProfile(doc, url) {
  const main = mainRoot(doc);
  const container = firstElement(main, RECRUITER.container) || main;
  const heading = firstHeading(container) || firstHeading(main);
  const fullName = firstText(container, RECRUITER.name) || heading?.text || "";
  const headline = firstText(container, RECRUITER.headline) || headlineHeuristic(container, fullName);
  const location = firstText(container, RECRUITER.location);

  let experience = readPositions(main);
  if (!experience.length) experience = parseExperienceSection(findSection(doc, "experience"));
  const current = currentPosition(experience);
  const fromHeadline = splitTitleCompany(headline);

  const profile = {
    page_kind: "recruiter_profile",
    page_url: url,
    public_url: findPublicUrl(doc, container, fullName),
    full_name: fullName || null,
    headline: headline || null,
    location: location || null,
    current_company: current?.company || fromHeadline.company || null,
    current_title: current?.title || fromHeadline.title || null,
    experience,
    skills: readSkills(main, RECRUITER.skill),
    about: readAbout(doc) || null,
  };
  return { profile, missing: missingFields(profile) };
}
