// Best-effort DOM extraction from a LinkedIn profile page. Supports:
//   - Public profile (linkedin.com/in/<slug>)
//   - Sales Navigator (linkedin.com/sales/lead/<id>, /sales/people/<id>)
//   - Recruiter (linkedin.com/talent/profile/<id>, /talent/people/<id>)
//
// For Sales Navigator and Recruiter pages, the LinkedIn URL we care about is
// the underlying `/in/<slug>` link that LinkedIn surfaces in the profile UI
// (usually as a "Public profile" or "View on LinkedIn" link). We extract
// THAT — not the /sales/ or /talent/ URL — because /in/<slug> is the only
// canonical form Proxycurl + dedup understand.
//
// We try multiple selectors per field because LinkedIn rotates class names.
// Server is the source of truth (Proxycurl) — these values just make the
// preview useful immediately so the user doesn't stare at empty fields.

function firstText(selectors) {
  for (const sel of selectors) {
    try {
      const el = document.querySelector(sel);
      const text = el?.textContent?.trim();
      if (text) return text;
    } catch (_err) {
      // invalid selector for current DOM — try next
    }
  }
  return null;
}

function firstAttr(selectors, attr) {
  for (const sel of selectors) {
    try {
      const el = document.querySelector(sel);
      const v = el?.getAttribute?.(attr);
      if (v && v.trim()) return v.trim();
    } catch (_err) {
      // try next
    }
  }
  return null;
}

function splitName(full) {
  if (!full) return { name: null, lastname: null };
  const parts = full.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { name: null, lastname: null };
  if (parts.length === 1) return { name: parts[0], lastname: null };
  return {
    name: parts[0],
    lastname: parts.slice(1).join(" "),
  };
}

function detectSurface() {
  const p = location.pathname;
  if (p.startsWith("/sales/")) return "sales_navigator";
  if (p.startsWith("/talent/")) return "recruiter";
  return "public";
}

// Find the canonical /in/<slug> URL — even when we're on a /sales/ or /talent/
// page. LinkedIn surfaces this as a "View public profile" / "Public profile"
// anchor in the profile sidebar/header.
function findCanonicalProfileUrl() {
  // Already on a public profile page → use the URL itself
  if (detectSurface() === "public") {
    try {
      const m = location.pathname.match(/\/in\/([^\/?#]+)/);
      if (m) return `https://www.linkedin.com/in/${m[1]}/`;
    } catch (_err) {}
  }

  // Search all anchors for any /in/<slug> link — LinkedIn typically includes
  // this in Sales Nav (profile detail panel) and Recruiter (profile header).
  const anchors = document.querySelectorAll('a[href*="/in/"]');
  for (const a of anchors) {
    const href = a.getAttribute("href") || "";
    const m = href.match(/linkedin\.com\/in\/([^\/?#]+)/);
    if (m) {
      return `https://www.linkedin.com/in/${m[1]}/`;
    }
    // Sometimes relative: /in/<slug>
    const m2 = href.match(/^\/in\/([^\/?#]+)/);
    if (m2) return `https://www.linkedin.com/in/${m2[1]}/`;
  }

  // Last-resort fallback — even though it's not a /in/ URL, send the
  // current URL so the server can attempt normalization (it'll 400 if
  // it can't, and the user can fix manually).
  return location.href;
}

export function getProfileUrl() {
  return findCanonicalProfileUrl();
}

// Extract candidate's display name from `<title>` — most stable signal across
// LinkedIn DOM rewrites. Format: "<First Last> | LinkedIn" or
// "<First Last> | LinkedIn — <Headline>".
function nameFromDocTitle() {
  const t = document.title || "";
  // Strip " | LinkedIn" suffix (and any tail after)
  const m = t.match(/^(.+?)\s*\|\s*LinkedIn/);
  if (!m) return null;
  const cleaned = m[1].trim();
  // Filter out non-profile titles ("Feed", "My Network", etc.)
  if (/^(feed|my network|messaging|notifications|jobs|home|sign in)$/i.test(cleaned)) {
    return null;
  }
  return cleaned || null;
}

// 2026-05 LinkedIn renders profile names in <h2> (was <h1> before), with
// hash-obfuscated classes. We look up structurally: the FIRST h2 inside main
// is the profile name. Headline/location are the FIRST few <p> children in
// the top-card area, in order: "· 3rd", headline, company, location.
function structuralPublicProfile() {
  const main = document.querySelector("main") || document.body;

  // Name — try h2 in main first (current DOM), fall back to h1 (legacy).
  let name = main.querySelector("h2")?.textContent?.trim() || null;
  if (!name) name = main.querySelector("h1")?.textContent?.trim() || null;
  if (!name) name = nameFromDocTitle();

  // Iterate top-N paragraphs in main; skip "· 3rd"-style connection markers.
  const ps = Array.from(main.querySelectorAll("p"))
    .slice(0, 12)
    .map((p) => p.textContent?.trim() || "")
    .filter(Boolean);

  const skipConnection = (s) => /^[·•\-]\s*(1st|2nd|3rd|3rd\+|out of network)$/i.test(s);
  const looksLikeLocation = (s) =>
    /,/.test(s) || /(area|region|metropolitan|greater)\b/i.test(s);

  let headline = null;
  let current_company = null;
  let location = null;
  for (const txt of ps) {
    if (skipConnection(txt)) continue;
    if (!headline && txt.length > 3 && !looksLikeLocation(txt)) {
      headline = txt;
      continue;
    }
    if (!current_company && headline && txt.length > 1 && txt !== "·" && !looksLikeLocation(txt)) {
      current_company = txt;
      continue;
    }
    if (!location && looksLikeLocation(txt)) {
      location = txt;
      break;
    }
  }
  return { name, headline, current_company, location };
}

// ── Public profile selectors (linkedin.com/in/<slug>) ────────────────────────
// Legacy class-based selectors — LinkedIn rotated these out in 2026-05 and
// obfuscated all class names. Kept as a fallback for legacy DOM and Recruiter
// embed iframes that haven't migrated yet.
const PUBLIC_NAME = [
  "main h2",
  "h1.text-heading-xlarge",
  "h1.inline.t-24",
  "main section.pv-top-card h1",
  "main h1",
];
const PUBLIC_HEADLINE = [
  ".text-body-medium.break-words",
  ".pv-text-details__left-panel .text-body-medium",
  "main section.pv-top-card .text-body-medium",
];
const PUBLIC_LOCATION = [
  ".text-body-small.inline.t-black--light.break-words",
  ".pv-text-details__left-panel--full-width .text-body-small",
];
const PUBLIC_COMPANY = [
  '[aria-label*="Current company"]',
  ".pv-text-details__right-panel-item-text",
];

// ── Sales Navigator selectors (linkedin.com/sales/...) ───────────────────────
const SALES_NAME = [
  '[data-anonymize="person-name"]',
  '[data-x--profile-name]',
  ".profile-topcard-person-entity__name",
  ".artdeco-entity-lockup__title",
  "h1.profile-topcard-person-entity__name",
  "main h1",
];
const SALES_HEADLINE = [
  '[data-anonymize="headline"]',
  '[data-x--profile-headline]',
  ".profile-topcard-person-entity__headline",
  ".profile-topcard__summary-position",
];
const SALES_LOCATION = [
  '[data-anonymize="location"]',
  '[data-x--profile-location]',
  ".profile-topcard__location-data",
];
const SALES_COMPANY = [
  '[data-anonymize="company-name"]',
  ".profile-topcard__current-position .profile-topcard__summary-position-info-company",
];

// ── Recruiter selectors (linkedin.com/talent/...) ────────────────────────────
const RECRUITER_NAME = [
  ".profile-info h1",
  ".profile-header__profile-info h1",
  ".topcard__title",
  "h1.profile-info__full-name",
  "main h1",
];
const RECRUITER_HEADLINE = [
  ".profile-info__headline",
  ".topcard__current-position",
  ".profile-header__headline",
];
const RECRUITER_LOCATION = [
  ".profile-info__location",
  ".topcard__location",
  ".profile-header__location",
];
const RECRUITER_COMPANY = [
  ".profile-info__current-company",
  ".topcard__current-position-company-name",
];

export function scrapeProfile() {
  const surface = detectSurface();
  let nameSel, headlineSel, locationSel, companySel;
  switch (surface) {
    case "sales_navigator":
      nameSel = SALES_NAME;
      headlineSel = SALES_HEADLINE;
      locationSel = SALES_LOCATION;
      companySel = SALES_COMPANY;
      break;
    case "recruiter":
      nameSel = RECRUITER_NAME;
      headlineSel = RECRUITER_HEADLINE;
      locationSel = RECRUITER_LOCATION;
      companySel = RECRUITER_COMPANY;
      break;
    default:
      nameSel = PUBLIC_NAME;
      headlineSel = PUBLIC_HEADLINE;
      locationSel = PUBLIC_LOCATION;
      companySel = PUBLIC_COMPANY;
  }

  // Structural pass first — works on 2026-05 obfuscated-class DOM where
  // every legacy selector returns null. For Sales Nav / Recruiter, run the
  // surface-specific selectors first (data-anonymize is still stable on
  // Sales Nav as of 2026-05) and fall back to structural.
  let structural = null;
  if (surface === "public") {
    structural = structuralPublicProfile();
  }

  const fullName =
    firstText(nameSel) ||
    structural?.name ||
    (surface !== "public" ? firstText(PUBLIC_NAME) || nameFromDocTitle() : null) ||
    nameFromDocTitle();
  const { name, lastname } = splitName(fullName);

  const headline =
    firstText(headlineSel) ||
    structural?.headline ||
    (surface !== "public" ? firstText(PUBLIC_HEADLINE) : null);

  const location =
    firstText(locationSel) ||
    structural?.location ||
    (surface !== "public" ? firstText(PUBLIC_LOCATION) : null);

  const current_company =
    firstText(companySel) ||
    structural?.current_company ||
    (surface !== "public" ? firstText(PUBLIC_COMPANY) : null);

  return {
    linkedin_url: findCanonicalProfileUrl(),
    name,
    lastname,
    headline,
    location,
    current_company,
    _surface: surface, // diagnostic only — not sent to server
  };
}
