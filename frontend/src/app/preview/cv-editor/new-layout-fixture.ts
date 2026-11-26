/**
 * `/preview/cv-editor?layout=new` (22.11.2026): fikcyjne CV w układzie „Nowe
 * CV” z zakładkami „Strona 1” i „Stanowiska”. Bez sieci: dodatki strony 1
 * zapisuje pamięć (`setPage1`), a podgląd PDF to statyczny plik
 * `public/preview/cv-editor/nowe-cv-przyklad.pdf` — render serwera
 * (`services/cv_new_layout`) z TEGO CV i tych dodatków, z nagłówkami jak
 * z trasy (`X-CV-Page1-Fits`, `X-CV-Page1-Font`). Po zmianie CV albo wyników
 * wygeneruj PDF ponownie (opis w `nowe-cv-drugi-uklad-obok-klasycznego.md`).
 */

import type { CvHighlightProposal, CvPage1Extras } from "@/lib/api";

const RODO =
  "Wyrażam zgodę na przetwarzanie moich danych osobowych zawartych w przekazanych przeze mnie " +
  "dokumentach przez Firmę Przykładową S.A. w celach związanych z moim udziałem w niniejszym " +
  "procesie rekrutacyjnym.";

export const NEW_LAYOUT_CV_HTML =
  "<h1>Senior Java Developer – Anna Przykładowa</h1>" +
  "<p><strong>Rozważany na stanowisko:</strong> Senior Java Developer — płatności kartowe</p><hr>" +
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad <strong>10 lat</strong> doświadczenia w <strong>Javie</strong>, w tym 5 lat w bankowości.</p></li>" +
  "<li><p>Praktyczne doświadczenie z <strong>Java 17</strong>, <strong>Spring Boot</strong>, " +
  "<strong>Kafka</strong> i <strong>PostgreSQL</strong> w systemach płatności kartowych.</p></li>" +
  "<li><p>Prowadzi przeglądy kodu i wdraża młodszych programistów.</p></li></ul>" +
  '<h2 data-cv-section="education">EDUKACJA</h2>' +
  "<p>2011 – 2016 <strong>Politechnika Przykładowa</strong> — Informatyka, mgr inż.</p>" +
  '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>' +
  "<p><strong>Języki programowania: </strong>Java 17, Kotlin, SQL</p>" +
  "<p><strong>Frameworki: </strong>Spring Boot, Hibernate, JUnit</p>" +
  "<p><strong>Narzędzia: </strong>Docker, Jenkins, Kafka, Git</p>" +
  '<h2 data-cv-section="languages">JĘZYKI</h2><p>polski – ojczysty</p><p>angielski – C1</p>' +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Java Developer</strong> 03.2021 – obecnie</p>' +
  '<p data-cv-section="employer">Bank Przykładowy S.A. · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Rozwój mikroserwisów płatności kartowych w <strong>Java 17</strong> i <strong>Spring Boot</strong>.</p></li>" +
  "<li><p>Optymalizacja zapytań w PostgreSQL dla raportów rozliczeń.</p></li>" +
  "<li><p>Przeglądy kodu i wdrażanie młodszych programistów.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 17, Spring Boot, Kafka, PostgreSQL, Docker</p>' +
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2018 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład sp. z o.o. · IT</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Tworzenie usług REST w Javie 11 i <strong>Spring Boot</strong>.</p></li>" +
  "<li><p>Integracje z systemami zewnętrznymi przez kolejki komunikatów.</p></li>" +
  "<li><p>Testy integracyjne dwunastu usług w Testcontainers.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 11, Spring Boot, JUnit, Jenkins</p>' +
  '<p data-cv-section="role"><strong>Junior Java Developer</strong> 07.2016 – 12.2017</p>' +
  '<p data-cv-section="employer">Fikcyjna Logistyka sp. z o.o. · Logistyka</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Rozwój modułu planowania tras w Javie 8.</p></li>" +
  "<li><p>Poprawki zgłoszeń wsparcia i testy jednostkowe.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 8, Hibernate, Oracle</p>' +
  `<p data-cv-section="rodo" style="font-size: 8pt; line-height: 1.35">${RODO}</p>`;

/** Wyniki „z odczytu CV” (fikcyjne); niesprawdzony nie trafia do „Inny wynik”. */
export const NEW_LAYOUT_EXTRAS: CvPage1Extras = {
  result_index: 0,
  results: [
    {
      text: "Przyspieszyła raporty rozliczeń o **40%** dzięki optymalizacji zapytań w PostgreSQL.",
      quote: "Optymalizacja zapytań w PostgreSQL dla raportów rozliczeń",
      company: "Bank Przykładowy S.A.",
      verified: true,
    },
    {
      text: "Objęła testami integracyjnymi **12 usług** w Testcontainers.",
      quote: "Testy integracyjne dwunastu usług w Testcontainers",
      company: "Software House Przykład sp. z o.o.",
      verified: true,
    },
    {
      text: "Skróciła wdrożenie nowych osób z 3 do 2 tygodni.",
      quote: null,
      company: "Bank Przykładowy S.A.",
      verified: false,
    },
  ],
};

/**
 * Propozycje AI wyróżnika po „Poszukaj w CV” (26.11.2026, fikcja). Harness nie
 * woła modelu ani kodu sprawdzającego cytat — pokazuje tylko wygląd sekcji;
 * PDF podglądu zostaje bez wyróżnika z propozycji.
 */
export const NEW_LAYOUT_HIGHLIGHT_PROPOSALS: CvHighlightProposal[] = [
  {
    kind: "award",
    label: "Wyróżnienie Programista Roku",
    token: "2023",
    text: "**Programista Roku 2023** w Banku Przykładowym za mikroserwisy płatności kartowych.",
    quote: "Wyróżnienie Programista Roku 2023 za mikroserwisy płatności kartowych",
    key: "preview-award",
    verified: true,
    source: "role",
    company: "Bank Przykładowy S.A.",
  },
];

export const NEW_LAYOUT_PDF = "/preview/cv-editor/nowe-cv-przyklad.pdf";

/** Nagłówki renderu, jakie trasa podglądu oddaje dla tego PDF-u. */
export const NEW_LAYOUT_HEADERS: Record<string, string> = {
  "X-CV-Layout": "new",
  "X-CV-Page1-Fits": "1",
  "X-CV-Page1-Font": "11",
  "X-CV-Unmapped-Sections": "0",
};
