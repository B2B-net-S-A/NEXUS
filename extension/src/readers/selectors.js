// WSZYSTKIE selektory i słowa-kotwice czytników w jednym miejscu.
//
// LinkedIn często zmienia DOM. Gdy panel zaczyna pokazywać „nie odczytano —
// wpisz” przy polu, które na stronie widać, popraw tylko ten plik: dopisz nowy
// selektor NA POCZĄTEK listy danego pola (stare zostaw — LinkedIn bywa w trakcie
// testów A/B i różni ludzie widzą różne wersje). Instrukcja w README.md.
//
// Każda lista to kolejne próby; wygrywa pierwszy selektor, który daje tekst.
// Gdy żaden nie trafi, czytnik przechodzi do heurystyki (np. imię = pierwszy
// `h1` w głównej treści) i dopiero potem zgłasza pole jako nieodczytane.

export const MAIN = ["main", "[role='main']", ".scaffold-layout__main", "#main", "body"];

// Regiony, w których link /in/ nigdy nie należy do oglądanej osoby
// (globalna nawigacja, „Inni oglądali też”, reklamy, podobne profile).
export const FOREIGN_REGIONS = [
  "nav",
  "aside",
  "header.global-nav",
  "[class*='global-nav']",
  "[class*='also-viewed']",
  "[class*='browsemap']",
  "[class*='similar']",
  "[class*='recommend']",
  "[data-view-name='profile-card-pymk']",
].join(", ");

// ── Profil publiczny: linkedin.com/in/<slug> ────────────────────────────────
export const PROFILE = {
  topCard: [
    "section[data-member-id]",
    ".pv-top-card",
    "section.artdeco-card:has(h1)",
    "[data-view-name='profile-top-card']",
  ],
  name: [
    "h1.text-heading-xlarge",
    "h1.inline.t-24",
    "[data-view-name='profile-top-card'] h1",
    ".pv-top-card h1",
  ],
  headline: [
    ".pv-text-details__left-panel .text-body-medium",
    "div.text-body-medium.break-words",
    "[data-generated-suggestion-target]",
    "[data-view-name='profile-top-card'] .text-body-medium",
  ],
  location: [
    ".pv-text-details__left-panel .text-body-small.inline.t-black--light",
    "span.text-body-small.inline.t-black--light.break-words",
    "[data-view-name='profile-top-card'] .text-body-small.t-black--light",
  ],
  // Przycisk/link „Obecna firma” w karcie górnej — aria-label niesie nazwę.
  currentCompanyAria: [
    "button[aria-label^='Current company']",
    "button[aria-label^='Obecna firma']",
    "a[aria-label^='Current company']",
    "a[aria-label^='Obecna firma']",
  ],
  currentCompanyAriaPrefix: /^(Current company|Obecna firma)\s*:\s*/i,
  currentCompanyAriaSuffix: /\.\s*(Click|Kliknij).*$/i,
};

// Sekcje profilu po kotwicach `<div id="experience">` (publiczny profil)
// i nagłówkach (Recruiter, nowy układ). `anchors` to id, `headings` to tekst h2.
export const SECTIONS = {
  experience: {
    anchors: ["experience", "experience-section"],
    headings: ["Experience", "Doświadczenie", "Work experience", "Doświadczenie zawodowe"],
    dataAttrs: ["[data-test-expandable-stack-position-list]", "[data-test-experience-section]", "[data-live-test-profile-experience]"],
  },
  skills: {
    anchors: ["skills", "skills-section"],
    headings: ["Skills", "Umiejętności", "Top skills", "Najważniejsze umiejętności"],
    dataAttrs: ["[data-test-skills-section]", "[data-live-test-profile-skills]"],
  },
  about: {
    anchors: ["about", "summary"],
    headings: ["About", "Informacje", "O mnie", "Summary", "Podsumowanie"],
    dataAttrs: ["[data-test-summary-section]", "[data-live-test-profile-summary]"],
  },
};

// Pozycje listy w sekcji (doświadczenie, umiejętności).
export const LIST_ITEMS = [
  "li.artdeco-list__item",
  "li.pvs-list__paged-list-item",
  "li[data-test-position-entity]",
  "li.background-entity",
  "li",
];

// Tekst „widoczny” — LinkedIn dubluje treść w span.visually-hidden dla czytników ekranu.
export const VISIBLE_TEXT = "span[aria-hidden='true']";
export const HIDDEN_TEXT = ".visually-hidden, .a11y-text, .sr-only";

// ── Recruiter: talent/profile/… i talent/hire/…/profile/… ────────────────────
export const RECRUITER = {
  container: [
    "[data-test-profile-header]",
    "[data-test-topcard]",
    ".profile-header",
    ".topcard",
    "[class*='topcard']",
    "section.artdeco-card:has(h1)",
  ],
  name: [
    "[data-test-row-lockup-full-name]",
    "[data-test-topcard-full-name]",
    ".artdeco-entity-lockup__title",
    "h1",
  ],
  headline: [
    "[data-test-row-lockup-headline]",
    "[data-test-topcard-headline]",
    ".topcard__headline",
    ".artdeco-entity-lockup__subtitle",
  ],
  location: [
    "[data-test-row-lockup-location]",
    "[data-test-topcard-location]",
    ".topcard__location",
    ".artdeco-entity-lockup__caption",
  ],
  position: {
    item: ["[data-test-position-entity]", "li.position-item", "li.background-entity"],
    title: ["[data-test-position-entity-title]", ".position-item__title", ".background-entity__summary-definition--title"],
    company: ["[data-test-position-entity-company-name]", "[data-test-position-entity-company-link]", ".position-item__company-link", ".background-entity__summary-definition--subtitle"],
    dates: ["[data-test-position-entity-date-range]", ".position-item__date-range", ".background-entity__date-range"],
  },
  skill: ["[data-test-skill-entity-name]", "[data-test-expandable-skill] span", ".skill-entity__skill-name"],
  // Link do profilu publicznego — po tekście linku albo po etykiecie.
  publicLinkLabels: ["Public profile", "Profil publiczny", "View public profile", "Zobacz profil publiczny", "LinkedIn profile", "Profil na LinkedInie"],
  publicLinkSelectors: ["a[data-test-public-profile-link]", "a[data-test-personal-info-profile-link]", "a.personal-info__link"],
};

// ── Listy wyników: search/results/people, recruiterSearch, projekt (manage) ──
export const RESULTS = {
  item: [
    "li.reusable-search__result-container",
    "[data-chameleon-result-urn]",
    "[data-view-name='search-entity-result-universal-template']",
    "li[data-test-search-result]",
    "[data-test-paginated-list-item]",
    "li.profile-list__border-bottom",
    "article.profile-list-item",
    "[data-test-pipeline-row]",
  ],
  name: [
    "[data-test-row-lockup-full-name]",
    ".entity-result__title-text a span[aria-hidden='true']",
    ".entity-result__title-text a",
    ".artdeco-entity-lockup__title",
  ],
  headline: [
    "[data-test-row-lockup-headline]",
    ".entity-result__primary-subtitle",
    ".artdeco-entity-lockup__subtitle",
  ],
  location: [
    "[data-test-row-lockup-location]",
    ".entity-result__secondary-subtitle",
    ".artdeco-entity-lockup__caption",
  ],
  // „Obecnie: …” w wynikach wyszukiwania i bieżące stanowisko w Recruiterze.
  current: [
    "[data-test-current-position]",
    "[data-test-history-group='current'] li",
    ".entity-result__summary--2-lines",
    ".entity-result__summary",
  ],
  // Linki do osób w liście (gdy żaden selektor pozycji nie trafi).
  personLinks: "a[href*='/in/'], a[href*='/talent/profile/'], a[href*='/profile/']",
  itemContainers: "li, tr, article, [data-chameleon-result-urn]",
};

// Teksty, które nie są imieniem, stanowiskiem ani firmą (przyciski, stopnie kontaktu).
export const NOISE_TEXT = [
  /^(•\s*)?(1st|2nd|3rd\+?|1\.|2\.|3\.\+?)$/i,
  /^(Connect|Message|Follow|Save|Nawiąż kontakt|Wiadomość|Obserwuj|Zapisz|Więcej|More|Pending|Oczekuje)$/i,
  /^(View|Zobacz)\b.*(profile|profil)/i,
  /^(Status is|Status:)/i,
  /^•$/,
];

export const UNKNOWN_MEMBER = /^(LinkedIn Member|Członek LinkedIn|Użytkownik LinkedIn)$/i;

// Prefiks „Obecnie:” w wynikach i słowa łączące stanowisko z firmą w nagłówku.
export const CURRENT_PREFIX = /^(Current|Obecnie|Aktualnie|Bieżące)\s*:\s*/i;
export const TITLE_COMPANY_SEPARATORS = [/\s+at\s+/i, /\s+@\s+/, /\s+w\s+(?=[A-ZŁŚŻŹĆŃÓ])/];

// Linia dat w doświadczeniu: „mar 2022 – obecnie · 2 lata 8 mies.”, „Jan 2020 - Dec 2021”.
export const PRESENT_WORDS = ["present", "obecnie", "teraz", "now", "dziś", "dzisiaj"];
export const MONTHS = {
  jan: 1, january: 1, sty: 1, stycznia: 1, styczeń: 1, styczen: 1,
  feb: 2, february: 2, lut: 2, lutego: 2, luty: 2,
  mar: 3, march: 3, marca: 3, marzec: 3,
  apr: 4, april: 4, kwi: 4, kwietnia: 4, kwiecień: 4, kwiecien: 4,
  may: 5, maj: 5, maja: 5,
  jun: 6, june: 6, cze: 6, czerwca: 6, czerwiec: 6,
  jul: 7, july: 7, lip: 7, lipca: 7, lipiec: 7,
  aug: 8, august: 8, sie: 8, sierpnia: 8, sierpień: 8, sierpien: 8,
  sep: 9, sept: 9, september: 9, wrz: 9, września: 9, wrzesień: 9, wrzesien: 9,
  oct: 10, october: 10, paź: 10, paz: 10, października: 10, październik: 10, pazdziernik: 10,
  nov: 11, november: 11, lis: 11, listopada: 11, listopad: 11,
  dec: 12, december: 12, gru: 12, grudnia: 12, grudzień: 12, grudzien: 12,
};
// Druga część linii firmy: „Comarch · Pełny etat” → typ zatrudnienia do odcięcia.
export const EMPLOYMENT_TYPES = /\s*·\s*(Full-time|Part-time|Contract|Self-employed|Freelance|Internship|Apprenticeship|Seasonal|Pełny etat|Niepełny etat|Kontrakt|Umowa o pracę|Samozatrudnienie|Działalność na własny rachunek|Freelancer|Staż|Praktyki|B2B)\s*$/i;
