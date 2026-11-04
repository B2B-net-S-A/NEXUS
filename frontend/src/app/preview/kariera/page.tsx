/**
 * Harness wizualny strony kariery — publiczny, ZERO zapytań.
 *
 * Renderuje prawdziwe komponenty `components/career/*` na danych fikcyjnych
 * (repo jest publiczne — żadnych prawdziwych nazwisk ani klientów). Formularze
 * mają wyłączoną wysyłkę (`preview.disableSubmit`), więc klik „wyślij" niczego
 * nie wysyła. Stany obok siebie: tablica otwartych rekrutacji (strona główna,
 * etap 6) z pustą tablicą i awarią API, rekrutacja otwarta, formularz
 * z błędami, podziękowanie, rekrutacja zamknięta, stały link rekrutera.
 *
 * `?szablon=<id>` — rekrutacja otwarta i zamknięta w jednym z trzech
 * szablonów (`components/career/themes.ts`, układy w `components/career/layouts/`).
 */
import type { Metadata } from "next";
import { use } from "react";

import { brandStyles } from "@/components/career/brand/BrandShell";
import { CareerApplyForm } from "@/components/career/CareerApplyForm";
import { CareerBoardView } from "@/components/career/CareerBoardView";
import { CareerJobView } from "@/components/career/CareerJobView";
import { CareerRecruiterView } from "@/components/career/CareerRecruiterView";
import { CareerTheme } from "@/components/career/CareerTheme";
import { CareerThemeScope } from "@/components/career/CareerThemeScope";
import { CAREER_THEME_IDS, CAREER_THEMES, isCareerThemeId } from "@/components/career/themes";
import { ThanksLog } from "@/components/career/ThanksLog";
import type {
  CareerBoardJob,
  CareerBoardResponse,
  CareerJobResponse,
  CareerRecruiterResponse,
} from "@/lib/career/api";

export const metadata: Metadata = {
  title: "Podgląd — strona kariery",
  robots: { index: false, follow: false },
};

// Harness działa na hoście aplikacji (BASE `/kariera`), więc i stopka pokazuje taki adres.
const HOST = "nexus.b2bnetwork.pl";
const BASE = "/kariera" as const;

const OPEN_JOB: CareerJobResponse = {
  status: "open",
  recruiter: { first_name: "Marta", slug: "marta-n" },
  job: {
    slug: "senior-java-developer-7kq2",
    title: "Senior Java Developer",
    subtitle: "rozwój platformy płatności w dużym projekcie z sektora bankowego",
    about:
      "Dołączysz do zespołu, który przebudowuje platformę obsługującą płatności kartowe i przelewy natychmiastowe. System przechodzi z monolitu na architekturę mikroserwisów opartą o zdarzenia.\n\nZespół liczy 8 osób, dwutygodniowe sprinty. Na starcie przejmiesz moduł rozliczeń, z czasem współdecydujesz o architekturze.",
    must: [
      { name: "Java Spring Boot", note: "min. 5 lat komercyjnie, java 17+" },
      { name: "Kafka", note: "architektura zdarzeniowa" },
      { name: "PostgreSQL", note: "schemat i optymalizacja zapytań" },
      { name: "English", note: "codzienna praca zespołu" },
    ],
    nice: ["Kubernetes", "AWS", "płatności"],
    params: {
      city: "Warszawa",
      remote_policy: "hybrid",
      onsite_days_per_week: 2,
      seniority: "senior",
      contract: "B2B",
      start: "10.2026",
      duration: "12+ mies.",
    },
    show: { must: true, nice: true, params: true, process: true },
  },
};

const CLOSED_JOB: CareerJobResponse = {
  status: "closed",
  recruiter: { first_name: "Marta", slug: "marta-n" },
  job: {
    slug: "senior-java-developer-7kq2",
    title: "Senior Java Developer",
    subtitle: null,
    about: null,
    must: [],
    nice: [],
    params: null,
    show: null,
  },
};

// Etap 5: rekruterka bez stałego linku — ekran odsyła do jej innych rekrutacji.
const CLOSED_JOB_NO_LINK: CareerJobResponse = {
  ...CLOSED_JOB,
  recruiter: { first_name: "Marta", slug: null },
  other_jobs: [
    { slug: "devops-engineer-azure-p3x9", title: "DevOps Engineer Azure", city: null, remote_policy: "remote" },
    { slug: "analityk-biznesowy-q8m1", title: "Analityk biznesowy", city: "Kraków", remote_policy: "hybrid" },
  ],
};

// Etap 6 (makieta 6d): „O mnie”, szablon i kategoria każdej rekrutacji.
const RECRUITER: CareerRecruiterResponse = {
  recruiter: {
    first_name: "Marta",
    slug: "marta-n",
    about:
      "Szukam ludzi do projektów w bankowości i ubezpieczeniach — głównie Java, dane i chmura. Odzywam się do każdej osoby w ciągu dwóch dni roboczych.",
  },
  jobs: [
    {
      slug: "senior-java-developer-7kq2",
      title: "Senior Java Developer",
      city: "Warszawa",
      remote_policy: "hybrid",
      theme: "terminal",
      category: "development",
    },
    {
      slug: "devops-engineer-azure-p3x9",
      title: "DevOps Engineer Azure",
      city: null,
      remote_policy: "remote",
      theme: "terminal",
      category: "infra",
    },
    {
      slug: "analityk-biznesowy-q8m1",
      title: "Analityk biznesowy",
      city: "Kraków",
      remote_policy: "hybrid",
      theme: "jasny",
      category: "management",
    },
  ],
};

// Rekruterka bez „O mnie” i bez otwartych rekrutacji na stronie.
const RECRUITER_EMPTY: CareerRecruiterResponse = {
  recruiter: { first_name: "Ola", slug: "ola-k" },
  jobs: [],
};

// Tablica (etap 6): 14 kart, każdy szablon co najmniej raz, „pokaż kolejne” po 12.
/** Wymagania kart tablicy (podgląd sceny i szukanie, etap 7) — fikcyjne. */
const BOARD_SKILLS: Record<string, { must: string[]; nice: string[] }> = {
  "senior-java-developer-7kq2": { must: ["Java Spring Boot", "Kafka", "PostgreSQL", "English"], nice: ["Kubernetes"] },
  "analityk-systemowy-k2p8": { must: ["UML i BPMN", "REST i SOAP", "SQL"], nice: ["Jira"] },
  "tester-automatyzujacy-r4t1": { must: ["Playwright", "TypeScript", "CI w GitLabie"], nice: ["Appium"] },
  "data-engineer-m3n6": { must: ["Python", "Spark", "Airflow", "dbt"], nice: ["Snowflake"] },
  "architekt-rozwiazan-c4x2": { must: ["Azure", "C4 i ADR", "Mikroserwisy"], nice: ["TOGAF"] },
  "devops-engineer-azure-p3x9": { must: ["Kubernetes", "Terraform", "Azure", "Helm"], nice: ["ArgoCD"] },
  "analityk-biznesowy-q8m1": { must: ["Warsztaty", "User stories", "Jira"], nice: ["Bankowość"] },
  "project-manager-h5j3": { must: ["Prince2 albo PMP", "Budżet projektu", "English C1"], nice: ["CRM"] },
  "tester-manualny-w9e4": { must: ["Przypadki testowe", "Jira i Xray", "SQL"], nice: [] },
  "security-engineer-s7d2": { must: ["SIEM", "Splunk", "Linux"], nice: ["Reagowanie na incydenty"] },
  "frontend-developer-f6g8": { must: ["React", "TypeScript", "Testy komponentów"], nice: ["Dostępność"] },
  "administrator-linux-a1b5": { must: ["Linux", "Ansible", "Bash", "Sieci"], nice: [] },
};

const BOARD_JOB = (
  slug: string,
  title: string,
  subtitle: string | null,
  city: string | null,
  remote_policy: CareerBoardJob["remote_policy"],
  category: CareerBoardJob["category"],
  theme: string,
  recruiter_first_name: string,
): CareerBoardJob => ({
  slug,
  title,
  subtitle,
  city,
  remote_policy,
  category,
  theme,
  recruiter_first_name,
  ...(BOARD_SKILLS[slug] ?? { must: [], nice: [] }),
});

const BOARD: CareerBoardResponse = {
  cv: { slug: "olga-r", first_name: "Olga" },
  jobs: [
    BOARD_JOB("senior-java-developer-7kq2", "Senior Java Developer", "rozwój platformy płatności w dużym banku", "Warszawa", "hybrid", "development", "terminal", "Marta"),
    BOARD_JOB("analityk-systemowy-k2p8", "Analityk systemowy", "integracje systemu rozliczeń w sektorze ubezpieczeń", null, "remote", "management", "jasny", "Kasia"),
    BOARD_JOB("tester-automatyzujacy-r4t1", "Tester automatyzujący", "testy end-to-end aplikacji mobilnej", "Kraków", "hybrid", "qa", "terminal", "Tomasz"),
    BOARD_JOB("data-engineer-m3n6", "Data Engineer", "hurtownia danych i strumienie zdarzeń", null, "remote", "infra", "grafit", "Marta"),
    BOARD_JOB("architekt-rozwiazan-c4x2", "Architekt rozwiązań", "migracja systemów do chmury", "Warszawa", "onsite", "development", "grafit", "Kasia"),
    BOARD_JOB("devops-engineer-azure-p3x9", "DevOps Engineer Azure", "platforma Kubernetes dla zespołów produktowych", "Gdańsk", "hybrid", "infra", "terminal", "Tomasz"),
    BOARD_JOB("analityk-biznesowy-q8m1", "Analityk biznesowy", "warsztaty z biznesem i backlog produktu", "Kraków", "hybrid", "management", "jasny", "Marta"),
    BOARD_JOB("project-manager-h5j3", "Project Manager", "wdrożenie nowego CRM w 6 krajach", null, "remote", "management", "jasny", "Kasia"),
    BOARD_JOB("tester-manualny-w9e4", "Tester manualny", "testy regresji systemu bankowości internetowej", "Łódź", "onsite", "qa", "terminal", "Tomasz"),
    BOARD_JOB("security-engineer-s7d2", "Security Engineer", "monitoring i reagowanie na incydenty", "Wrocław", "hybrid", "infra", "grafit", "Marta"),
    BOARD_JOB("frontend-developer-f6g8", "Frontend Developer React", "nowy panel klienta w sektorze energetycznym", null, "remote", "development", "terminal", "Kasia"),
    BOARD_JOB("administrator-linux-a1b5", "Administrator Linux", "utrzymanie infrastruktury on-premise", "Poznań", "onsite", "infra", "grafit", "Tomasz"),
    BOARD_JOB("python-developer-y2u7", "Python Developer", null, null, "remote", "development", "terminal", "Marta"),
    BOARD_JOB("scrum-master-z8c3", "Scrum Master", "dwa zespoły produktowe w e-commerce", "Warszawa", "hybrid", "management", "jasny", "Kasia"),
  ],
};


const STATES = [
  { id: "tablica", label: "tablica otwartych rekrutacji" },
  { id: "tablica-pusta", label: "tablica bez rekrutacji" },
  { id: "tablica-awaria", label: "tablica — awaria API" },
  { id: "otwarta", label: "rekrutacja otwarta" },
  { id: "bledy", label: "formularz z błędami" },
  { id: "dziekujemy", label: "podziękowanie" },
  { id: "zamknieta", label: "rekrutacja zamknięta" },
  { id: "zamknieta-bez-linku", label: "zamknięta, bez stałego linku" },
  { id: "rekruter", label: "stały link rekrutera" },
  { id: "rekruter-pusty", label: "rekruter bez opisu i rekrutacji" },
];

function State({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-label={label} style={{ borderTop: "4px solid #9A142D" }}>
      <p
        style={{
          margin: 0,
          padding: "8px 16px",
          background: "#120407",
          color: "#F5F5F5",
          fontSize: 12,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
        }}
      >
        {"// stan: "}
        {label}
      </p>
      <CareerTheme>{children}</CareerTheme>
    </section>
  );
}

export default function CareerPreviewPage({
  searchParams,
}: {
  searchParams?: Promise<{ szablon?: string }>;
}) {
  // `use` wolno wołać warunkowo; test renderuje stronę bez parametrów.
  const { szablon } = searchParams ? use(searchParams) : {};
  const theme = isCareerThemeId(szablon) ? szablon : undefined;
  return (
    <div style={{ background: "#000" }}>
      <nav
        aria-label="Stany"
        style={{ display: "flex", flexWrap: "wrap", gap: 16, padding: 16, fontFamily: "monospace" }}
      >
        {STATES.map((s) => (
          <a key={s.id} href={`#${s.id}`} style={{ color: "#D14A5F" }}>
            #{s.id}
          </a>
        ))}
      </nav>
      <nav
        aria-label="Szablony"
        style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "0 16px 16px", fontFamily: "monospace", fontSize: 12 }}
      >
        {CAREER_THEME_IDS.map((id) => (
          <a
            key={id}
            href={`?szablon=${id}#otwarta`}
            style={{ color: id === (theme ?? "grafit") ? "#F5F5F5" : "#8B8B8B" }}
            aria-current={id === (theme ?? "grafit") ? "page" : undefined}
          >
            {CAREER_THEMES[id].label}
          </a>
        ))}
      </nav>

      <State id="tablica" label="tablica otwartych rekrutacji">
        <CareerBoardView
          data={BOARD}
          base={BASE}
          host={HOST}
          theme={theme}
          formPreview={{ disableSubmit: true }}
        />
      </State>

      <State id="tablica-pusta" label="tablica bez rekrutacji">
        <CareerBoardView
          data={{ ...BOARD, jobs: [] }}
          base={BASE}
          host={HOST}
          theme={theme}
          formPreview={{ disableSubmit: true }}
        />
      </State>

      <State id="tablica-awaria" label="tablica — awaria API">
        <CareerBoardView data={null} base={BASE} host={HOST} theme={theme} />
      </State>

      <State id="otwarta" label="rekrutacja otwarta">
        <CareerJobView
          data={{ ...OPEN_JOB, theme }}
          base={BASE}
          host={HOST}
          formPreview={{ disableSubmit: true }}
        />
      </State>

      <State id="bledy" label="formularz z błędami">
        <CareerThemeScope theme={theme}>
          <div className={`${brandStyles.root} ${brandStyles.wrap}`} style={{ padding: "32px 20px", maxWidth: 720 }}>
            <div className={`${brandStyles.apply} ${brandStyles.form}`}>
            <CareerApplyForm
              linkSlug="senior-java-developer-7kq2"
              variant="job"
              rodoHref={`${BASE}/rodo`}
              tone="plain"
              preview={{
                disableSubmit: true,
                values: { first_name: "Jan", last_name: "Kowalski", email: "jan@firma-.pl" },
                errors: {
                  email:
                    "sprawdź adres — po @ nie może być myślnika na początku ani na końcu części domeny",
                  cv: "dodaj CV — pdf, doc lub docx do 10 MB",
                  consent: "bez zgody nie możemy przyjąć zgłoszenia",
                },
              }}
            />
            </div>
          </div>
        </CareerThemeScope>
      </State>

      <State id="dziekujemy" label="podziękowanie">
        <CareerThemeScope theme={theme}>
          <ThanksLog
            variant="job"
            firstName="Jan"
            email="jan@example.com"
            recruiterFirstName="Marta"
            jobTitle="Senior Java Developer"
            homeHref={BASE}
            rodoHref={`${BASE}/rodo`}
            hostLabel={`${HOST}${BASE}/r/senior-java-developer-7kq2`}
            recruiterPageHref={`${BASE}/p/marta-n`}
          />
        </CareerThemeScope>
      </State>

      <State id="zamknieta" label="rekrutacja zamknięta">
        <CareerJobView data={{ ...CLOSED_JOB, theme }} base={BASE} host={HOST} />
      </State>

      <State id="zamknieta-bez-linku" label="zamknięta, bez stałego linku">
        <CareerJobView data={CLOSED_JOB_NO_LINK} base={BASE} host={HOST} />
      </State>

      <State id="rekruter" label="stały link rekrutera">
        <CareerRecruiterView data={RECRUITER} base={BASE} host={HOST} theme={theme} formPreview={{ disableSubmit: true }} />
      </State>

      <State id="rekruter-pusty" label="rekruter bez opisu i rekrutacji">
        <CareerRecruiterView
          data={RECRUITER_EMPTY}
          base={BASE}
          host={HOST}
          formPreview={{ disableSubmit: true }}
        />
      </State>
    </div>
  );
}
