// Stan okna „Ogłoszenie” do testów — dane fikcyjne.

import {
  NO_CAREER_PAGE,
  type AdCareerState,
  type AdReminders,
  type AdContent,
  type AdFinding,
  type AdPublication,
  type AdTechItem,
  type JobAdState,
  type PracujRequest,
} from "@/lib/api/jobAd";

export const CONTENT: AdContent = {
  title: "Senior Java Developer",
  lead: "Szukamy osoby do zespołu płatności.",
  about: "Zespół buduje mikroserwisy rozliczeniowe.",
  start: "listopad 2026",
  duration: "12 miesięcy",
  language: "polski",
  city: "",
  responsibilities: ["rozwój mikroserwisów", "przeglądy kodu"],
  requirements: ["min. 5 lat doświadczenia w Javie", "praktyka z Apache Kafka"],
  nice_to_have: ["Kubernetes i OpenShift"],
  offer: ["projekt na lata"],
};

export const TECH: AdTechItem[] = [
  { name: "Java", level: "critical" },
  { name: "Kafka", level: "must" },
  { name: "Kubernetes", level: "nice" },
];

const list = (key: string, label: string, items: string[], extra = {}) => ({
  key,
  label,
  kind: "list" as const,
  text: items.join("\n"),
  html: `<ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul>`,
  items,
  auto_count: 0,
  fixed_count: 0,
  ...extra,
});

export function adState(
  patch: {
    content?: AdContent;
    findings?: AdFinding[];
    source?: "ai" | "template";
    stale?: boolean;
    lang?: "pl" | "en";
    publications?: AdPublication[];
    career?: AdCareerState;
    reminders?: AdReminders | null;
    pracuj_request?: PracujRequest | null;
  } = {},
): JobAdState {
  const content = patch.content ?? CONTENT;
  const findings = patch.findings ?? [];
  return {
    ad: {
      lang: patch.lang ?? "pl",
      content,
      tech: TECH,
      source: patch.source ?? "ai",
      generated_at: "2026-10-12T09:15:00Z",
      updated_at: "2026-10-12T09:20:00Z",
      stale: patch.stale ?? false,
    },
    facts: [{ key: "city", label: "Miasto", value: "Warszawa" }],
    readiness: [
      { key: "about", label: "Opis projektu", present: true },
      { key: "duration", label: "Długość kontraktu", present: false },
    ],
    findings,
    can_copy: !findings.some((f) => f.severity === "block"),
    publications: patch.publications ?? [],
    career: patch.career ?? NO_CAREER_PAGE,
    reminders: patch.reminders ?? null,
    pracuj_request: patch.pracuj_request ?? null,
    rendered: {
      title: `${content.title} (k/m/x)`,
      pracuj: {
        params: ["kontrakt B2B", "praca hybrydowa"],
        fields: [
          {
            key: "title",
            label: "Tytuł stanowiska",
            kind: "text",
            text: `${content.title} (k/m/x)`,
            html: "",
            items: [],
            auto_count: 0,
            fixed_count: 0,
          },
          {
            key: "about",
            label: "O projekcie",
            kind: "text",
            text: content.about,
            html: `<p>${content.about}</p>`,
            items: [],
            auto_count: 0,
            fixed_count: 0,
          },
          list("requirements", "Nasze wymagania", content.requirements),
          list("offer", "To oferujemy", ["kontrakt B2B", ...content.offer, "opieka medyczna"], {
            auto_count: 1,
            fixed_count: 1,
          }),
          list("process", "Etapy rekrutacji", ["Rozmowa z rekruterem"], {
            kind: "ordered" as const,
            fixed_count: 1,
          }),
        ],
      },
      jjit: {
        form_fields: [
          { key: "title", label: "Tytuł", value: `${content.title} (k/m/x)` },
          { key: "experience", label: "Doświadczenie", value: "Senior" },
        ],
        tech_stack: [
          { name: "Java", level: 4, label: "Advanced", source: "critical" },
          { name: "Kafka", level: 3, label: "Regular", source: "must" },
          { name: "Kubernetes", level: 1, label: "Nice to have", source: "nice" },
        ],
        tech_overflow: 0,
        sections: [
          {
            key: "lead",
            heading: null,
            kind: "text",
            text: content.lead,
            items: [],
            fixed_count: 0,
          },
          {
            key: "requirements",
            heading: "Wymagania",
            kind: "list",
            text: "",
            items: content.requirements,
            fixed_count: 0,
          },
        ],
        body_html: "<p>opis html</p>",
        body_text: "opis tekst",
      },
    },
  };
}

export const EMPTY_STATE: JobAdState = {
  ad: null,
  facts: [{ key: "city", label: "Miasto", value: "Warszawa" }],
  readiness: [{ key: "about", label: "Opis projektu", present: true }],
  findings: [],
  rendered: null,
  can_copy: false,
  publications: [],
  career: NO_CAREER_PAGE,
  reminders: null,
  pracuj_request: null,
};

export const PRACUJ_URL = "https://www.pracuj.pl/praca/przyklad,oferta,1000000001";

export function publication(patch: Partial<AdPublication> = {}): AdPublication {
  return {
    portal: "pracuj",
    url: PRACUJ_URL,
    outdated: false,
    published_at: "2026-10-12T10:00:00Z",
    published_by_name: "Marta Przykładowa",
    removed_at: null,
    ...patch,
  };
}

export const CLIENT_FINDING: AdFinding = {
  code: "client_name",
  severity: "block",
  message: "Nazwa klienta w treści: „dla klienta Bank Przykładowy”. Klienta opisujemy branżą.",
  excerpt: "dla klienta Bank Przykładowy",
  field: "about",
};
