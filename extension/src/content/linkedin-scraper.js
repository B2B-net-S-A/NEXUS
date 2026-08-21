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

// ── Rozwiązanie kanonicznego /in/<slug> ──────────────────────────────────────
//
// Na /sales/ i /talent/ URL strony NIE zawiera slugu, więc trzeba go znaleźć
// w DOM. Wersja sprzed tej poprawki brała PIERWSZĄ kotwicę `/in/` w całym
// dokumencie — czyli równie chętnie link do profilu samego operatora z
// globalnej nawigacji albo wpis z „People also viewed" / „Similar leads".
// Skutek był CICHY i najgorszy z możliwych: podgląd pokazywał właściwe
// nazwisko (idzie z innego źródła niż URL), a do bazy leciał `linkedin_url`
// obcej osoby — po czym Proxycurl nadpisywał firmę, stanowisko i historię
// zatrudnienia danymi tej obcej osoby. Nikt tego nie wychwytuje wzrokiem.
//
// Obrona jest dwuwarstwowa:
//   1. zawężenie do kontenera karty profilu (a dopiero potem szersze pasy),
//   2. kontrola krzyżowa slug ↔ nazwisko z podglądu — dostępna na tej samej
//      stronie, bez dodatkowego requestu.

// Kontenery karty profilu — pierwszy trafiony wygrywa. Kolejność od
// najbardziej jednoznacznego do najluźniejszego.
const SALES_PROFILE_CONTAINERS = [
  '[data-sn-view-name="feature-lead-profile-topcard"]',
  "#profile-card-section",
  ".profile-topcard",
  ".profile-topcard-person-entity",
  ".profile-detail",
  ".artdeco-entity-lockup",
];
const RECRUITER_PROFILE_CONTAINERS = [
  "[data-test-profile-header]",
  ".profile-header__profile-info",
  ".profile-info",
  ".profile-header",
  ".topcard",
];

// Regiony, w których kotwica `/in/` NIGDY nie należy do oglądanej osoby.
// Stosowane WYŁĄCZNIE w szerokich pasach (main / cały dokument) — wewnątrz
// wybranego kontenera profilu nic nie odsiewamy, bo np. karta w Recruiterze
// bywa sama w sobie `<header>`.
const FOREIGN_ANCHOR_REGIONS = [
  "nav",
  "aside",
  '[class*="global-nav"]',
  '[class*="also-viewed"]',
  '[class*="also_viewed"]',
  '[class*="similar"]',
  '[class*="recommend"]',
  '[class*="browsemap"]',
].join(", ");

function slugFromHref(href) {
  const raw = href || "";
  const m = raw.match(/linkedin\.com\/in\/([^\/?#]+)/);
  if (m) return decodeURIComponent(m[1]);
  // Czasem względny: /in/<slug>
  const m2 = raw.match(/^\/in\/([^\/?#]+)/);
  if (m2) return decodeURIComponent(m2[1]);
  return null;
}

/**
 * Zbierz slugi `/in/` z podanych korzeni, w kolejności dokumentu.
 *
 * Wydzielone z DOM-owej reszty, żeby dało się to przetestować bez
 * przeglądarki — `roots` to cokolwiek, co ma `querySelectorAll`.
 *
 * @param {Array<{querySelectorAll: Function}>} roots
 * @param {boolean} skipForeignRegions - odsiewaj nawigację/„podobne profile"
 */
export function collectSlugsFromRoots(roots, skipForeignRegions) {
  const out = [];
  for (const root of roots) {
    if (!root || typeof root.querySelectorAll !== "function") continue;
    let anchors;
    try {
      anchors = root.querySelectorAll('a[href*="/in/"]');
    } catch (_err) {
      continue;
    }
    for (const a of anchors) {
      if (skipForeignRegions && typeof a.closest === "function") {
        let foreign = false;
        try {
          foreign = Boolean(a.closest(FOREIGN_ANCHOR_REGIONS));
        } catch (_err) {
          foreign = false;
        }
        if (foreign) continue;
      }
      const slug = slugFromHref(a.getAttribute?.("href"));
      if (slug && !out.includes(slug)) out.push(slug);
    }
  }
  return out;
}

/** Zdejmij diakrytyki i sprowadź do [a-z0-9]. `ł`/`ø`/`đ` nie mają rozkładu NFD. */
function normalizeForMatch(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[Łł]/g, "l")
    .replace(/[Øø]/g, "o")
    .replace(/[Đđ]/g, "d")
    .toLowerCase();
}

/**
 * Tokeny nazwiska użyteczne do porównania ze slugiem.
 *
 * Próg 3 znaków celowo odrzuca inicjały i partykuły („de", „van", „von"), ale
 * także dwuznakowe nazwiska („Li", „Wu") — wtedy tokenów nie ma wcale i cała
 * kontrola milczy. To właściwy kierunek błędu: brak tokenów = brak DOWODU
 * sprzeczności, a nie dowód zgodności.
 */
export function nameTokens(fullName) {
  return normalizeForMatch(fullName)
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 3);
}

/**
 * Czy slug w ogóle może nieść nazwisko?
 *
 * Slug oparty o member-id („ACoAAABc…") i slug czysto numeryczny nie niosą
 * żadnej informacji o osobie — porównywanie ich z nazwiskiem dałoby wyłącznie
 * fałszywe alarmy.
 */
export function slugIsOpaque(slug) {
  const raw = String(slug || "");
  if (!raw) return true;
  if (/^AC[a-zA-Z]A/.test(raw)) return true;
  return !/[a-z]{3,}/.test(normalizeForMatch(raw));
}

/**
 * Twierdzi „ten slug NA PEWNO nie należy do tej osoby" — nigdy odwrotnie.
 * Brak tokenów, slug nieprzezroczysty → `false` (brak dowodu), bo domyślną
 * odpowiedzią przy niewiedzy musi być „nie blokuj".
 */
export function slugContradictsName(slug, fullName) {
  const tokens = nameTokens(fullName);
  if (tokens.length === 0) return false;
  if (slugIsOpaque(slug)) return false;
  const norm = normalizeForMatch(slug);
  return !tokens.some((t) => norm.includes(t));
}

/**
 * Wybierz slug, który wyślemy jako `linkedin_url`, albo `null` gdy nie da się
 * tego zrobić uczciwie.
 *
 * Reguła jednego kandydata: gdy w całym dokumencie jest DOKŁADNIE JEDEN slug,
 * przepuszczamy go nawet mimo sprzeczności z nazwiskiem — własny, nietypowy
 * vanity-slug („/in/annakowalska-dev", „/in/iamthebestdev") jest znacznie
 * częstszy niż podmiana osoby przy jednym jedynym linku, a fałszywe
 * odrzucenie kosztuje rekrutera ręczne wklejanie URL-a przy KAŻDYM profilu.
 * Sprzeczność blokuje dopiero wtedy, gdy kandydatów jest kilku i żaden nie
 * pasuje — czyli dokładnie w sytuacji, w której poprzedni kod losował.
 */
export function pickCanonicalSlug(slugs, fullName) {
  const unique = [];
  for (const s of slugs || []) {
    if (s && !unique.includes(s)) unique.push(s);
  }
  if (unique.length === 0) return null;
  const agreeing = unique.filter((s) => !slugContradictsName(s, fullName));
  if (agreeing.length > 0) return agreeing[0];
  if (unique.length === 1) return unique[0];
  return null;
}

function containerRootsFor(surface) {
  const selectors =
    surface === "sales_navigator"
      ? SALES_PROFILE_CONTAINERS
      : surface === "recruiter"
        ? RECRUITER_PROFILE_CONTAINERS
        : [];
  const roots = [];
  for (const sel of selectors) {
    try {
      const el = document.querySelector(sel);
      if (el) roots.push(el);
    } catch (_err) {
      // selektor nieobsługiwany przez ten DOM — próbuj dalej
    }
  }
  return roots;
}

// Find the canonical /in/<slug> URL — even when we're on a /sales/ or /talent/
// page. LinkedIn surfaces this as a "View public profile" / "Public profile"
// anchor in the profile sidebar/header.
function findCanonicalProfileUrl(expectedFullName) {
  const surface = detectSurface();

  // Already on a public profile page → use the URL itself
  if (surface === "public") {
    try {
      const m = location.pathname.match(/\/in\/([^\/?#]+)/);
      if (m) return `https://www.linkedin.com/in/${m[1]}/`;
    } catch (_err) {}
  }

  const fullName =
    expectedFullName === undefined ? resolveFullName(surface, null) : expectedFullName;

  // Pas 1: karta profilu (bez odsiewania — to już właściwy kontener).
  let slug = pickCanonicalSlug(
    collectSlugsFromRoots(containerRootsFor(surface), false),
    fullName,
  );
  if (!slug) {
    // Pas 2: <main>, potem cały dokument — z odsiewaniem nawigacji i
    // „podobnych profili".
    let main = null;
    try {
      main = document.querySelector("main");
    } catch (_err) {}
    slug = pickCanonicalSlug(
      collectSlugsFromRoots([main, document].filter(Boolean), true),
      fullName,
    );
  }
  if (slug) return `https://www.linkedin.com/in/${slug}/`;

  // Last-resort fallback — even though it's not a /in/ URL, send the
  // current URL so the server can attempt normalization (it'll 400 if
  // it can't, and the user can fix manually).
  //
  // Ten fallback jest tu ŚWIADOMIE także dla przypadku „slugi są, ale żaden
  // nie zgadza się z nazwiskiem": backend odpowiada wtedy czytelnym 400
  // („Expected a 'linkedin.com/in/<slug>' profile link"), czyli awarią, którą
  // widać. Wysłanie cudzego slugu byłoby zapisem, którego NIE widać.
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

/**
 * Rozwiązanie nazwiska z podglądu — WSPÓLNE dla `scrapeProfile()` i dla
 * kontroli krzyżowej slug ↔ nazwisko w `findCanonicalProfileUrl()`.
 *
 * Wydzielone celowo: gdyby URL rozstrzygał się z jednego źródła, a nazwisko
 * z innego (tak było wcześniej), kontrola porównywałaby coś innego niż to, co
 * rekruter widzi w modalu — i mogłaby przepuścić dokładnie ten rozjazd, który
 * ma łapać.
 */
function resolveFullName(surface, structural) {
  const nameSel =
    surface === "sales_navigator"
      ? SALES_NAME
      : surface === "recruiter"
        ? RECRUITER_NAME
        : PUBLIC_NAME;
  return (
    firstText(nameSel) ||
    structural?.name ||
    (surface !== "public" ? firstText(PUBLIC_NAME) || nameFromDocTitle() : null) ||
    nameFromDocTitle()
  );
}

export function scrapeProfile() {
  const surface = detectSurface();
  let headlineSel, locationSel, companySel;
  switch (surface) {
    case "sales_navigator":
      headlineSel = SALES_HEADLINE;
      locationSel = SALES_LOCATION;
      companySel = SALES_COMPANY;
      break;
    case "recruiter":
      headlineSel = RECRUITER_HEADLINE;
      locationSel = RECRUITER_LOCATION;
      companySel = RECRUITER_COMPANY;
      break;
    default:
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

  const fullName = resolveFullName(surface, structural);
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
    // Nazwisko przekazujemy JAWNIE: rozwiązanie URL-a ma zostać skonfrontowane
    // dokładnie z tym nazwiskiem, które trafi do podglądu i do payloadu.
    linkedin_url: findCanonicalProfileUrl(fullName),
    name,
    lastname,
    headline,
    location,
    current_company,
    _surface: surface, // diagnostic only — not sent to server
  };
}
