// Recruiter renders the active slide-in outside [role=main]. Never let the
// background search result or project heading identify the selected person.
import { RECRUITER_PROFILE_ROOTS, RECRUITER } from "./selectors.js";
import { firstElement, mainRoot, safeQuery, safeQueryAll } from "./dom.js";

function hidden(el) {
  for (let p = el; p; p = p.parentElement) {
    if (p.hasAttribute?.("hidden") || p.getAttribute?.("aria-hidden") === "true") return true;
    if (/(?:^|;)\s*display\s*:\s*none\s*(?:;|$)/i.test(p.getAttribute?.("style") || "")) return true;
  }
  return false;
}

export function recruiterRoot(doc) {
  for (const selector of RECRUITER_PROFILE_ROOTS) {
    const all = safeQueryAll(doc, selector);
    if (!all.length) continue;
    const active = all.filter((el) => !hidden(el));
    return active.length === 1 ? active[0] : null;
  }
  const main = mainRoot(doc);
  if (safeQuery(main, "[data-test-paginated-list-item], article.profile-list-item") && !firstElement(main, RECRUITER.container)) return null;
  return main;
}

/** Only portals explicitly controlled/described by this profile are its data. */
export function profileScopes(doc, root) {
  const scopes = [root];
  for (const trigger of safeQueryAll(root, "[aria-controls], [aria-describedby]")) {
    const ids = `${trigger.getAttribute("aria-controls") || ""} ${trigger.getAttribute("aria-describedby") || ""}`.split(/\s+/).filter(Boolean);
    for (const id of ids) {
      const portal = doc.getElementById?.(id);
      if (portal && safeQuery(portal, "a[href*='/in/']") && !hidden(portal) && !scopes.includes(portal)) scopes.push(portal);
    }
  }
  return scopes;
}
