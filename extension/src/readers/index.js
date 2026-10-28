// Odczyt strony właściwym czytnikiem.
//  - profil publiczny i lista wyników: najpierw zrzut tekstu (zmierzony
//    28.10.2026), brakujące pola uzupełnia czytnik HTML starszego układu,
//  - Recruiter (niezmierzony): najpierw atrybuty `data-test-*` z HTML,
//    braki uzupełnia zrzut tekstu.

import { PAGE_KINDS, detectPage } from "./kinds.js";
import { missingFields, readProfile } from "./profile.js";
import { readRecruiterProfile } from "./recruiter-profile.js";
import { MAX_PEOPLE, readSearchResults } from "./search-results.js";
import { readListText, readProfileText, readRecruiterText } from "./text.js";

export { PAGE_KINDS, detectPage };

const isEmpty = (v) => v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);

/** Pola puste w `primary` bierze z `secondary`. */
export function mergeProfiles(primary, secondary) {
  if (!primary) return secondary;
  if (!secondary) return primary;
  const out = { ...primary };
  for (const [k, v] of Object.entries(secondary)) if (isEmpty(out[k]) && !isEmpty(v)) out[k] = v;
  return out;
}

/**
 * Drugi czytnik uzupełnia braki tylko wtedy, gdy sam rozpoznał tę samą osobę —
 * heurystyki starszego układu na nowej stronie potrafią złapać przypadkową linię.
 */
function combine(page, first, second) {
  const a = first?.profile || null;
  const b = second?.profile || null;
  const sameOrUnknown = b?.full_name && (!a?.full_name || a.full_name.toLowerCase() === b.full_name.toLowerCase());
  const profile = mergeProfiles(a, sameOrUnknown ? b : null) || a || b;
  return { ...page, profile, missing: profile ? missingFields(profile) : [] };
}

/**
 * @param {{url: string, snapshot?: object | null, doc?: Document | null}} input
 * `snapshot` — zrzut tekstu z `capturePage`; `doc` — kopia HTML (zapas).
 */
export function readPage({ url, snapshot = null, doc = null }) {
  const page = detectPage(url);
  switch (page.kind) {
    case PAGE_KINDS.PROFILE:
      return combine(page, snapshot && readProfileText(snapshot, url), doc && readProfile(doc, url));
    case PAGE_KINDS.RECRUITER_PROFILE:
      return combine(page, doc && readRecruiterProfile(doc, url), snapshot && readRecruiterText(snapshot, url));
    case PAGE_KINDS.SEARCH_RESULTS: {
      const fromText = snapshot ? readListText(snapshot, MAX_PEOPLE) : null;
      if (fromText && (fromText.people.length || fromText.skipped)) return { ...page, ...fromText };
      return { ...page, ...(doc ? readSearchResults(doc) : { people: [], truncated: false, skipped: 0 }) };
    }
    default:
      return page;
  }
}

/** Sam czytnik HTML (starszy układ) — zapas i testy selektorów. */
export function readPageDom(doc, url) {
  return readPage({ url, doc });
}
