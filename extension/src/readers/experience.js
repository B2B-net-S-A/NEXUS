// Sekcja doświadczenia → [{title, company, start, end, current}].
// Dwa układy LinkedIna:
//  - pojedyncza pozycja: [stanowisko, „Firma · Pełny etat”, „mar 2022 – obecnie · 2 lata”, miasto…]
//  - kilka ról w jednej firmie: [Firma, „Pełny etat · 5 lat”, …] + podlista ról z datami.

import { EMPLOYMENT_TYPES, LIST_ITEMS } from "./selectors.js";
import { clean, safeQueryAll, textBlocks, topLevelItems } from "./dom.js";
import { isDateLine, isDurationLine, parseDateRange } from "./dates.js";

export function companyFromLine(line) {
  if (!line || isDateLine(line) || isDurationLine(line)) return null;
  const c = clean(line).replace(EMPLOYMENT_TYPES, "").trim();
  if (EMPLOYMENT_TYPES.test(` · ${c}`)) return null; // sama forma zatrudnienia, bez firmy
  return c || null;
}

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

function singlePosition(blocks) {
  const dateLine = blocks.find(isDateLine) || null;
  const title = blocks[0] && !isDateLine(blocks[0]) ? blocks[0] : null;
  const company = companyFromLine(blocks[1]);
  return entry(title, company, dateLine);
}

/** Podpozycje (role) w grupie jednej firmy — `li` w środku, które mają własną linię dat. */
function nestedRoles(item) {
  const inner = safeQueryAll(item, "li").filter((li) => li !== item && textBlocks(li).some(isDateLine));
  // tylko najwyższy poziom podlisty
  return inner.filter((li) => !inner.some((other) => other !== li && other.contains?.(li)));
}

export function parseExperienceSection(section) {
  if (!section) return [];
  const out = [];
  for (const item of topLevelItems(section, LIST_ITEMS)) {
    const roles = nestedRoles(item);
    if (roles.length) {
      const company = companyFromLine(textBlocks(item)[0]) || textBlocks(item)[0] || null;
      for (const role of roles) {
        const blocks = textBlocks(role);
        const dateLine = blocks.find(isDateLine) || null;
        out.push(entry(blocks[0] && !isDateLine(blocks[0]) ? blocks[0] : null, company, dateLine));
      }
      continue;
    }
    const blocks = textBlocks(item);
    if (!blocks.length) continue;
    const pos = singlePosition(blocks);
    if (pos.title || pos.start) out.push(pos);
  }
  return out;
}

/** Bieżąca pozycja: pierwsza „obecnie”, a gdy żadnej — najnowsza na liście. */
export function currentPosition(experience) {
  return experience.find((e) => e.current) || null;
}
