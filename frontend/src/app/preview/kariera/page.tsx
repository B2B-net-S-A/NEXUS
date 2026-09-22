/**
 * Harness wizualny strony kariery — publiczny, ZERO zapytań.
 *
 * Renderuje prawdziwe komponenty `components/career/*` na danych fikcyjnych
 * (repo jest publiczne — żadnych prawdziwych nazwisk ani klientów). Formularze
 * mają wyłączoną wysyłkę (`preview.disableSubmit`), więc klik „wyślij" niczego
 * nie wysyła. Stany obok siebie: rekrutacja otwarta, formularz z błędami,
 * podziękowanie, rekrutacja zamknięta, stały link rekrutera.
 */
import type { Metadata } from "next";

import { CareerApplyForm } from "@/components/career/CareerApplyForm";
import { CareerJobView } from "@/components/career/CareerJobView";
import { CareerRecruiterView } from "@/components/career/CareerRecruiterView";
import { CareerTheme } from "@/components/career/CareerTheme";
import { TerminalChrome } from "@/components/career/TerminalChrome";
import { ThanksLog } from "@/components/career/ThanksLog";
import type { CareerJobResponse, CareerRecruiterResponse } from "@/lib/career/api";

export const metadata: Metadata = {
  title: "Podgląd — strona kariery",
  robots: { index: false, follow: false },
};

// Harness działa na hoście aplikacji (BASE `/kariera`), więc i stopka pokazuje taki adres.
const HOST = "nexus.dynaminds.pl";
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

const RECRUITER: CareerRecruiterResponse = {
  recruiter: { first_name: "Marta", slug: "marta-n" },
  jobs: [
    { slug: "senior-java-developer-7kq2", title: "Senior Java Developer", city: "Warszawa", remote_policy: "hybrid" },
    { slug: "devops-engineer-azure-p3x9", title: "DevOps Engineer Azure", city: null, remote_policy: "remote" },
    { slug: "analityk-biznesowy-q8m1", title: "Analityk biznesowy", city: "Kraków", remote_policy: "hybrid" },
  ],
};

const STATES = [
  { id: "otwarta", label: "rekrutacja otwarta" },
  { id: "bledy", label: "formularz z błędami" },
  { id: "dziekujemy", label: "podziękowanie" },
  { id: "zamknieta", label: "rekrutacja zamknięta" },
  { id: "rekruter", label: "stały link rekrutera" },
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

export default function CareerPreviewPage() {
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

      <State id="otwarta" label="rekrutacja otwarta">
        <CareerJobView data={OPEN_JOB} base={BASE} host={HOST} formPreview={{ disableSubmit: true }} />
      </State>

      <State id="bledy" label="formularz z błędami">
        <TerminalChrome path="~/dynaminds/kariera — zsh" />
        <div style={{ padding: "20px 0", maxWidth: 520 }}>
          <div className="kr-form-box">
            <div className="kr-form-bar">
              <span>
                <span className="kr-r">$</span> ./aplikuj.sh
              </span>
            </div>
            <CareerApplyForm
              linkSlug="senior-java-developer-7kq2"
              variant="job"
              rodoHref={`${BASE}/rodo`}
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
      </State>

      <State id="dziekujemy" label="podziękowanie">
        <ThanksLog
          variant="job"
          firstName="Jan"
          email="jan@example.com"
          recruiterFirstName="Marta"
          jobHandle="senior-java-developer"
          chromePath="~/dynaminds/kariera — zsh — senior-java-developer"
          recruiterPageHref={`${BASE}/p/marta-n`}
          recruiterPageSlug="marta-n"
        />
      </State>

      <State id="zamknieta" label="rekrutacja zamknięta">
        <CareerJobView data={CLOSED_JOB} base={BASE} host={HOST} />
      </State>

      <State id="rekruter" label="stały link rekrutera">
        <CareerRecruiterView data={RECRUITER} base={BASE} host={HOST} formPreview={{ disableSubmit: true }} />
      </State>
    </div>
  );
}
