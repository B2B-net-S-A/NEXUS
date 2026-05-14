// Best-effort DOM extraction from a LinkedIn profile page. We try multiple
// selectors per field because LinkedIn rotates class names. Server is the
// source of truth (Proxycurl) — these values just make the preview useful
// immediately so the user doesn't stare at empty fields.

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

export function getProfileUrl() {
  // Always use the current canonical URL (drop tracking params).
  try {
    const u = new URL(window.location.href);
    // Keep just the /in/<slug> path; drop everything else.
    const m = u.pathname.match(/\/in\/([^\/?#]+)/);
    if (m) {
      return `https://www.linkedin.com/in/${m[1]}/`;
    }
  } catch (_err) {
    // fall through
  }
  return window.location.href;
}

export function scrapeProfile() {
  const fullName = firstText([
    "h1.text-heading-xlarge",
    "h1.inline.t-24",
    "main section.pv-top-card h1",
    "main h1",
  ]);
  const { name, lastname } = splitName(fullName);

  const headline = firstText([
    ".text-body-medium.break-words",
    ".pv-text-details__left-panel .text-body-medium",
    "main section.pv-top-card .text-body-medium",
  ]);

  const location = firstText([
    ".text-body-small.inline.t-black--light.break-words",
    ".pv-text-details__left-panel--full-width .text-body-small",
    "main section.pv-top-card .pv-text-details__left-panel .text-body-small",
  ]);

  const current_company = firstText([
    '[aria-label*="Current company"]',
    ".pv-text-details__right-panel-item-text",
    "main section.pv-top-card button[aria-label*='company']",
  ]);

  return {
    linkedin_url: getProfileUrl(),
    name,
    lastname,
    headline,
    location,
    current_company,
  };
}
