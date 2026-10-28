// Rodzaj strony z adresu i odczyt właściwym czytnikiem.

import { readProfile } from "./profile.js";
import { readRecruiterProfile } from "./recruiter-profile.js";
import { readSearchResults } from "./search-results.js";

export const PAGE_KINDS = Object.freeze({
  PROFILE: "profile",
  RECRUITER_PROFILE: "recruiter_profile",
  SEARCH_RESULTS: "search_results",
  UNSUPPORTED: "unsupported",
});

/**
 * @param {string | undefined} url
 * @returns {{kind: string, source?: string, key?: string}}
 * `key` = adres bez zapytania i kotwicy — po nim panel poznaje, że to ta sama strona.
 */
export function detectPage(url) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return { kind: PAGE_KINDS.UNSUPPORTED };
  }
  if (u.protocol !== "https:" || !/(^|\.)linkedin\.com$/.test(u.hostname)) return { kind: PAGE_KINDS.UNSUPPORTED };
  const p = u.pathname;

  const inMatch = p.match(/^\/in\/([^/]+)/);
  if (inMatch) return { kind: PAGE_KINDS.PROFILE, key: `in/${inMatch[1].toLowerCase()}` };

  if (/^\/talent\/profile\/[^/]+/.test(p) || /^\/talent\/hire\/[^/]+\/.*\/profile\/[^/]+/.test(p)) {
    const id = p.match(/\/profile\/([^/]+)/)[1];
    return { kind: PAGE_KINDS.RECRUITER_PROFILE, key: `talent/${id}` };
  }
  if (/^\/search\/results\/people\/?/.test(p)) {
    return { kind: PAGE_KINDS.SEARCH_RESULTS, source: "search", key: `${p}${u.search}` };
  }
  if (/^\/talent\/hire\/[^/]+\/discover\/recruiterSearch/.test(p)) {
    return { kind: PAGE_KINDS.SEARCH_RESULTS, source: "recruiter_search", key: `${p}${u.search}` };
  }
  if (/^\/talent\/hire\/[^/]+\/manage(\/|$)/.test(p)) {
    return { kind: PAGE_KINDS.SEARCH_RESULTS, source: "recruiter_project", key: `${p}${u.search}` };
  }
  return { kind: PAGE_KINDS.UNSUPPORTED };
}

/** Odczyt dokumentu strony; `doc` to `Document` (DOMParser w panelu, linkedom w testach). */
export function readPage(doc, url) {
  const page = detectPage(url);
  switch (page.kind) {
    case PAGE_KINDS.PROFILE:
      return { ...page, ...readProfile(doc, url) };
    case PAGE_KINDS.RECRUITER_PROFILE:
      return { ...page, ...readRecruiterProfile(doc, url) };
    case PAGE_KINDS.SEARCH_RESULTS:
      return { ...page, ...readSearchResults(doc) };
    default:
      return page;
  }
}
