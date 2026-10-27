/**
 * Dane fikcyjne i API okna „Ogłoszenie” w pamięci — wspólne dla harnessów
 * `/preview/job-ad` i `/preview/career-queue` (nic nie wychodzi do sieci).
 * Osobny plik, bo `page.tsx` może eksportować tylko pola trasy Next.js.
 */

import type { JobAdWindowApi } from "@/components/v2/job-ad/JobAdWindow";
import {
  NO_CAREER_PAGE,
  type AdCareerState,
  type AdContent,
  type AdFinding,
  type AdLang,
  type AdPublication,
  type AdTechItem,
  type JobAdState,
  type RenderedAd,
  type RenderedField,
  type RenderedSection,
} from "@/lib/api/jobAd";

const FACTS = [
  { key: "seniority", label: "Poziom", value: "Senior" },
  { key: "workplace", label: "Tryb", value: "hybrydowo, 2 dni w tygodniu w biurze" },
  { key: "city", label: "Miasto", value: "Warszawa" },
  { key: "contract", label: "Współpraca", value: "B2B" },
  { key: "start", label: "Start", value: "listopad 2026" },
  { key: "language", label: "Język", value: "polski, angielski B2" },
  { key: "requirements", label: "Wymagania", value: "3 krytyczne, 2 wymagane, 2 mile widziane" },
];

const READINESS = [
  { key: "about", label: "Opis projektu", present: true },
  { key: "responsibilities", label: "Zakres obowiązków", present: true },
  { key: "must", label: "Wymagania", present: true },
  { key: "nice", label: "Mile widziane", present: true },
  { key: "workplace", label: "Tryb pracy i miasto", present: true },
  { key: "seniority", label: "Poziom", present: true },
  { key: "language", label: "Język pracy", present: true },
  { key: "start", label: "Start projektu", present: true },
  { key: "duration", label: "Długość kontraktu", present: false },
];

export const CONTENT: AdContent = {
  title: "Senior Java Developer",
  lead: "Szukamy osoby na stanowisko Senior Java Developer do zespołu, który rozwija platformę płatności natychmiastowych w sektorze bankowym.",
  about:
    "Zespół ośmiu osób buduje nowe mikroserwisy rozliczeniowe i przenosi starszy moduł autoryzacji na architekturę zdarzeniową. Praca w Scrumie, wdrożenia co dwa tygodnie.",
  start: "listopad 2026",
  duration: "",
  language: "polski, angielski B2",
  responsibilities: [
    "projektowanie i rozwój mikroserwisów w Javie 21 i Spring Boot",
    "przenoszenie modułu autoryzacji płatności na komunikację przez Kafkę",
    "testy jednostkowe i integracyjne",
    "przeglądy kodu i udział w decyzjach architektonicznych",
  ],
  requirements: [
    "min. 5 lat komercyjnego doświadczenia w Javie",
    "Spring Boot i mikroserwisy w środowisku produkcyjnym",
    "praktyka z Apache Kafka",
    "relacyjne bazy danych: PostgreSQL lub Oracle",
    "angielski na poziomie B2",
  ],
  nice_to_have: ["Kubernetes i OpenShift", "znajomość standardu ISO 20022"],
  offer: ["projekt zaplanowany na kilka lat"],
};

export const TECH: AdTechItem[] = [
  { name: "Java", level: "critical" },
  { name: "Spring Boot", level: "critical" },
  { name: "Kafka", level: "critical" },
  { name: "PostgreSQL", level: "must" },
  { name: "Angielski", level: "must" },
  { name: "Kubernetes", level: "nice" },
  { name: "OpenShift", level: "nice" },
];

const FIXED_OFFER = [
  "prywatna opieka medyczna",
  "dofinansowanie zajęć sportowych",
  "wsparcie formalne od dokumentów po onboarding",
];
const FIXED_PROCESS = ["Rozmowa z rekruterem", "Rozmowa techniczna", "Rozmowa z klientem"];
const FIXED_ABOUT = "Firma Przykładowa łączy specjalistów IT z projektami, które do nich pasują.";

const JJIT_LEVEL = {
  critical: { level: 4, label: "Advanced" },
  must: { level: 3, label: "Regular" },
  nice: { level: 1, label: "Nice to have" },
} as const;

const esc = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const ul = (items: string[]) => `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;

/** Uproszczony odpowiednik `services/job_ad/render.py` — tylko dla harnessu. */
function renderForHarness(content: AdContent, tech: AdTechItem[]): RenderedAd {
  const title = `${content.title} (k/m/x)`;
  const terms = [
    "kontrakt B2B",
    "praca hybrydowa: 2 dni w tygodniu w biurze (Warszawa)",
    ...(content.start ? [`start: ${content.start}`] : []),
    ...(content.duration ? [`czas trwania: ${content.duration}`] : []),
    ...(content.language ? [`język pracy: ${content.language}`] : []),
  ];
  const list = (
    key: string,
    label: string,
    items: string[],
    extra: Partial<RenderedField> = {},
  ): RenderedField => ({
    key,
    label,
    kind: "list",
    text: items.join("\n"),
    html: items.length ? ul(items) : "",
    items,
    auto_count: 0,
    fixed_count: 0,
    ...extra,
  });
  const text = (key: string, label: string, value: string): RenderedField => ({
    key,
    label,
    kind: "text",
    text: value,
    html: value ? `<p>${esc(value)}</p>` : "",
    items: [],
    auto_count: 0,
    fixed_count: 0,
  });
  const section = (
    key: string,
    heading: string | null,
    items: string[] | string,
    extra: Partial<RenderedSection> = {},
  ): RenderedSection | null => {
    const isText = typeof items === "string";
    if (isText ? !items.trim() : items.length === 0) return null;
    return {
      key,
      heading,
      kind: isText ? "text" : "list",
      text: isText ? items : "",
      items: isText ? [] : items,
      fixed_count: 0,
      ...extra,
    };
  };
  const sections = [
    section("lead", null, content.lead),
    section("about", "O projekcie", content.about),
    section("terms", "Warunki współpracy", terms),
    section("responsibilities", "Twój zakres obowiązków", content.responsibilities),
    section("requirements", "Wymagania", content.requirements),
    section("nice_to_have", "Mile widziane", content.nice_to_have),
    section("offer", "Co oferujemy", [...content.offer, ...FIXED_OFFER], {
      fixed_count: FIXED_OFFER.length,
    }),
    section("process", "Jak wygląda proces", FIXED_PROCESS, {
      kind: "ordered",
      fixed_count: FIXED_PROCESS.length,
    }),
    section("company", null, FIXED_ABOUT),
  ].filter((item): item is RenderedSection => item !== null);
  const order = { critical: 0, must: 1, nice: 2 } as const;
  const stack = [...tech].sort((a, b) => order[a.level] - order[b.level]);
  return {
    title,
    pracuj: {
      params: [
        "starszy specjalista / starsza specjalistka (senior)",
        "kontrakt B2B",
        "pełny etat",
        "praca hybrydowa",
        "Warszawa",
      ],
      fields: [
        text("title", "Tytuł stanowiska", title),
        text("about", "O projekcie", content.about || content.lead),
        list("responsibilities", "Twój zakres obowiązków", content.responsibilities),
        list("requirements", "Nasze wymagania", content.requirements),
        list("nice_to_have", "Mile widziane", content.nice_to_have),
        list("offer", "To oferujemy", [...terms, ...content.offer, ...FIXED_OFFER], {
          auto_count: terms.length,
          fixed_count: FIXED_OFFER.length,
        }),
        list(
          "tech_required",
          "Technologie wymagane",
          stack.filter((t) => t.level !== "nice").map((t) => t.name),
        ),
        list(
          "tech_optional",
          "Technologie mile widziane",
          stack.filter((t) => t.level === "nice").map((t) => t.name),
        ),
        list("process", "Etapy rekrutacji", FIXED_PROCESS, {
          kind: "ordered",
          fixed_count: FIXED_PROCESS.length,
        }),
      ],
    },
    jjit: {
      form_fields: [
        { key: "title", label: "Tytuł", value: title },
        { key: "experience", label: "Doświadczenie", value: "Senior" },
        { key: "employment", label: "Zatrudnienie", value: "B2B · Full-time" },
        { key: "workplace", label: "Tryb pracy", value: "Hybrid" },
        { key: "office_days", label: "Dni w biurze", value: "2" },
        { key: "city", label: "Miasto", value: "Warszawa" },
      ],
      tech_stack: stack.slice(0, 10).map((t) => ({
        name: t.name,
        source: t.level,
        ...JJIT_LEVEL[t.level],
      })),
      tech_overflow: Math.max(0, stack.length - 10),
      sections,
      body_html: sections
        .map(
          (s) =>
            (s.heading ? `<h3>${esc(s.heading)}</h3>` : "") +
            (s.kind === "text" ? `<p>${esc(s.text)}</p>` : ul(s.items)),
        )
        .join(""),
      body_text: sections
        .map((s) =>
          [s.heading, s.kind === "text" ? s.text : s.items.map((i) => `• ${i}`).join("\n")]
            .filter(Boolean)
            .join("\n"),
        )
        .join("\n\n"),
    },
  };
}

export const ADVICE: AdFinding[] = [
  {
    code: "missing_duration",
    severity: "advise",
    message: "Brak długości współpracy.",
    excerpt: null,
    field: "duration",
  },
];

export const FINDINGS_CONTENT: AdContent = {
  ...CONTENT,
  about:
    "Rozwój platformy płatności natychmiastowych dla klienta Bank Przykładowy. Zespół ośmiu osób buduje nowe mikroserwisy rozliczeniowe.",
  requirements: ["min. 5 lat komercyjnego doświadczenia w Javie", "Kafka", "chmura"],
  offer: ["kontrakt B2B, stawka do 150 zł/h netto"],
};

export const FINDINGS: AdFinding[] = [
  {
    code: "client_name",
    severity: "block",
    message:
      "Nazwa klienta w treści: „Rozwój platformy płatności natychmiastowych dla klienta Bank Przykładowy.”. Klienta opisujemy branżą.",
    excerpt: "Rozwój platformy płatności natychmiastowych dla klienta Bank Przykładowy.",
    field: "about",
  },
  {
    code: "money",
    severity: "block",
    message:
      "Kwota w treści: „kontrakt B2B, stawka do 150 zł/h netto”. Widełki podajesz tylko w polu wynagrodzenia portalu.",
    excerpt: "kontrakt B2B, stawka do 150 zł/h netto",
    field: "offer",
  },
  {
    code: "short_requirement",
    severity: "advise",
    message:
      "Wymagania w jednym–dwóch słowach: „Kafka”, „chmura”. Kandydat nie wie, jakiego doświadczenia oczekujesz.",
    excerpt: null,
    field: "requirements",
  },
  ...ADVICE,
];

export type HarnessState = "ready" | "findings" | "template" | "empty" | "published";

const PRACUJ_LINK = "https://www.pracuj.pl/praca/senior-java-developer-warszawa,oferta,1000000001";

/** Ogłoszenie wisi na Pracuj.pl, a treść zmieniono po publikacji. */
const PUBLISHED: AdPublication[] = [
  {
    portal: "pracuj",
    url: PRACUJ_LINK,
    outdated: true,
    published_at: "2026-10-12T10:00:00Z",
    published_by_name: "Preview Rekruter",
    removed_at: null,
  },
];

/** Strona kariery z tej treści — adres fikcyjny. */
const CAREER_LIVE: AdCareerState = {
  status: "live",
  url: "https://kariera.b2bnetwork.pl/r/senior-java-developer-ab12",
  published_at: "2026-10-21T09:00:00Z",
  published_by_name: "Preview Rekruter",
};

export function stateOf(
  content: AdContent,
  tech: AdTechItem[],
  findings: AdFinding[],
  patch: {
    lang?: AdLang;
    source?: "ai" | "template";
    stale?: boolean;
    publications?: AdPublication[];
    career?: AdCareerState;
  } = {},
): JobAdState {
  return {
    ad: {
      lang: patch.lang ?? "pl",
      content,
      tech,
      source: patch.source ?? "ai",
      generated_at: "2026-10-12T09:15:00Z",
      updated_at: "2026-10-12T09:15:00Z",
      stale: patch.stale ?? false,
    },
    facts: FACTS,
    readiness: READINESS,
    findings,
    rendered: renderForHarness(content, tech),
    can_copy: !findings.some((f) => f.severity === "block"),
    publications: patch.publications ?? [],
    career: patch.career ?? NO_CAREER_PAGE,
    reminders: null,
    pracuj_request: null,
  };
}

function initial(state: HarnessState): JobAdState {
  if (state === "empty") {
    return {
      ad: null,
      facts: FACTS,
      readiness: READINESS,
      findings: [],
      rendered: null,
      can_copy: false,
      publications: [],
      career: NO_CAREER_PAGE,
      reminders: null,
      pracuj_request: null,
    };
  }
  if (state === "published") {
    return stateOf(CONTENT, TECH, ADVICE, {
      publications: PUBLISHED,
      career: { ...CAREER_LIVE, status: "outdated" },
    });
  }
  if (state === "findings") return stateOf(FINDINGS_CONTENT, TECH, FINDINGS);
  if (state === "template") {
    return stateOf({ ...CONTENT, lead: "" }, TECH, ADVICE, { source: "template", stale: true });
  }
  return stateOf(CONTENT, TECH, ADVICE);
}

/** API okna w pamięci: nic nie wychodzi do sieci. */
export function memoryApi(state: HarnessState): JobAdWindowApi {
  let current = initial(state);
  return {
    get: async () => current,
    generate: async (_jobId, lang) => {
      current = stateOf(CONTENT, TECH, ADVICE, {
        lang,
        career:
          current.career.status === "none"
            ? current.career
            : { ...current.career, status: "outdated" },
      });
      return current;
    },
    save: async (_jobId, input) => {
      const advice = input.content.duration ? [] : ADVICE;
      current = stateOf(input.content, input.tech, advice, {
        lang: current.ad?.lang,
        source: current.ad?.source,
        // Poprawka po publikacji = ogłoszenie na portalu do aktualizacji.
        publications: current.publications.map((item) =>
          item.removed_at ? item : { ...item, outdated: true },
        ),
        career:
          current.career.status === "none"
            ? current.career
            : { ...current.career, status: "outdated" },
      });
      return current;
    },
    markPublished: async (_jobId, portal, url, contentUpdated = false) => {
      const active = current.publications.find(
        (item) => item.portal === portal && !item.removed_at,
      );
      const next: AdPublication = active
        ? // Sama zmiana linku nie potwierdza treści ani nie zmienia, kto opublikował.
          { ...active, url, outdated: contentUpdated ? false : active.outdated }
        : {
            portal,
            url,
            outdated: false,
            published_at: "2026-10-13T09:00:00Z",
            published_by_name: "Preview Rekruter",
            removed_at: null,
          };
      current = {
        ...current,
        publications: [...current.publications.filter((item) => item.portal !== portal), next],
      };
      return current;
    },
    publishCareer: async () => {
      current = { ...current, career: CAREER_LIVE };
      return current;
    },
    markRemoved: async (_jobId, portal) => {
      current = {
        ...current,
        publications: current.publications.map((item) =>
          item.portal === portal ? { ...item, removed_at: "2026-10-13T09:30:00Z" } : item,
        ),
      };
      return current;
    },
  };
}
