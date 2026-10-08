"use client";

/**
 * Harness `/preview/new-job` — strona „Nowa rekrutacja” na danych fikcyjnych.
 *
 * `?state=request|noclient|resume|manual|review|gaps|servererror|portals|shadow|passive|off`.
 * Zero zapytań: klucze klientów, rekruterów, konfiguracji portali i słownika
 * RocketJobs są zasiane w cache (patrz `app/preview/__tests__`), kategorie
 * i wiedza o wierszach wymagań przychodzą w stanie podglądu, a baner podobnych
 * rekrutacji nie renderuje się w trybie podglądu.
 *
 * `request` = krok 1 z wklejonym requestem, `noclient` = krok 1 bez klienta
 * (kliknięcie przycisku pokazuje komunikat przy polu klienta), `manual` = krok
 * 2 pusty, `gaps` = krok 2 z brakami (budżet, krytyczne, deal breaker,
 * kategoria). `portals` = krok „Ogłoszenie na portalach” z gotowym szkicem (na
 * produkcji portale są dziś wyłączone flagami). Automat przydziału jest
 * w podglądzie włączony w trybie „auto” („Przydzieli automat”); `shadow` =
 * automat tylko proponuje, `passive` = priorytet „Przyjmujemy kandydatów”
 * (automat wtedy nikogo nie przydziela), `off` = automat wyłączony. `gaps`
 * pokazuje też rekrutera wskazanego ręcznie. `resume` = krok 1 z listą
 * niedokończonych formularzy, `servererror` = krok 2 po odmowie serwera
 * (422 `job_not_ready`) z listą braków w stopce.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  NewJobPage,
  type NewJobPagePreview,
} from "@/components/v2/jobs/new/NewJobPage";
import type { CategoryOption } from "@/components/v2/jobs/new/NewJobTeamStep";
import { EMPTY_INTAKE_FORM, type IntakeForm } from "@/lib/job-request-intake";
import type { RequirementRowForm, RowCriticalState } from "@/lib/requirement-rows";
import {
  EMPTY_LISTING_OPTIONS,
  jobPortalKeys,
  type BoardDictionaries,
  type PortalConfigResponse,
} from "@/lib/api/jobPortals";

const CLIENT = { id: 1, name: "[Klient testowy]" };

const REQUEST = `Cześć,
zapytanie ZOB 48213 „Programista Java — płatności kartowe (ZOB 48213)”:
szukamy Senior Java Developera do zespołu płatności kartowych (projekt migracji core'u na mikroserwisy, ok. 12 miesięcy z opcją przedłużenia).

Wymagania: Java 17+, Spring Boot, Kafka, doświadczenie z PostgreSQL. Mile widziane: Kubernetes.
Min. 5 lat doświadczenia komercyjnego.

Praca hybrydowa — 2 dni w tygodniu w biurze w Warszawie.
Budżet do 170 zł/h netto B2B. Start najlepiej 1 listopada.
Potrzebujemy 2 osób, kandydatów prosimy do 20 października.

Na rozmowie zapytamy o transakcyjność w systemach rozproszonych.

Pozdrawiam
Anna Przykładowa
Kierownik Zespołu Płatności`;

// Wymagania jako słowa kluczowe (02.10.2026): wiersz = wymaganie, słowa =
// warianty. Krytyczne: DL użył podpowiedzi z historii.
const ROWS: RequirementRowForm[] = [
  { key: "r-java", words: ["Java"], level: "critical" },
  { key: "r-spring", words: ["Spring Boot"], level: "must" },
  { key: "r-kafka", words: ["Kafka", "RabbitMQ"], level: "must" },
  { key: "r-postgres", words: ["PostgreSQL"], level: "must" },
  { key: "r-payments", words: ["płatności", "płatnoś*", "payments"], level: "must" },
  { key: "r-k8s", words: ["Kubernetes", "k8s"], level: "nice" },
];

/** To, co serwer mówi o wierszach: etykieta, czy technologia, podpowiedź. */
const CRITICAL_INFO: RowCriticalState = {
  info: {
    "r-java": { label: "Java", eligible: true, suggested: true, stat: { rate: 0.96, jobs: 41 } },
    "r-spring": { label: "Spring Boot", eligible: true, suggested: false, stat: { rate: 0.71, jobs: 41 } },
    // RabbitMQ spoza słownika: wiersz wolno oznaczyć (08.10.2026), choć nie
    // jest „technologią ze słownika” dla podpowiedzi i tytułu.
    "r-kafka": { label: "Kafka lub RabbitMQ", eligible: false, selectable: true, suggested: false },
    "r-postgres": { label: "PostgreSQL", eligible: true, suggested: false },
    "r-payments": {
      label: "płatności",
      eligible: false,
      selectable: false,
      blockedReason: "To branża, nie technologia — daje punkty, nie ukrywa kandydatów.",
      suggested: false,
    },
  },
  isLoading: false,
  isError: false,
  retry: () => undefined,
};

const CATEGORIES: CategoryOption[] = [
  { id: 1, slug: "infrastructure_operations", name: "Infra & Operations & Security / Data & AI", participants: 7 },
  { id: 2, slug: "software_development", name: "Development", participants: 7 },
  { id: 4, slug: "security_quality", name: "QA", participants: 3 },
  { id: 5, slug: "management_delivery", name: "Management & Delivery (PM & BA)", participants: 3 },
];

const FULL_FORM: IntakeForm = {
  ...EMPTY_INTAKE_FORM,
  title: "Senior Java Developer",
  clientTitle: "Programista Java — płatności kartowe (ZOB 48213)",
  referenceHint: "ZOB 48213",
  rows: ROWS,
  descriptive: ["Min. 5 lat doświadczenia komercyjnego"],
  competenceCategoryId: 2,
  suggestedCategoryId: 2,
  categoryConfirmed: true,
  seniorityYears: 5,
  rateBudget: "170",
  remotePolicy: "hybrid",
  onsiteDays: "2",
  city: "Warszawa, Gdańsk",
  intakeNotes: ["„Min. 5 lat” zapisane w polu „Lata doświadczenia”."],
  // Audyt 06.10.2026 (N3): wiersze, które nie zmieściły się nawet w „mile widziane”.
  droppedRequirements: ["Terraform"],
  startDate: "2026-11-01",
  deadline: "2026-10-20",
  headcount: "2",
  about:
    "Migracja systemu płatności kartowych z monolitu na mikroserwisy. Projekt na ok. 12 miesięcy z opcją przedłużenia.",
  questions: [
    {
      key: "p1",
      question: "Jak zapewniałeś transakcyjność w systemie rozproszonym?",
      idealAnswer: "Saga / outbox, idempotencja, przykład z produkcji.",
      dealBreaker: "Nie zna pojęcia transakcji rozproszonej, zawsze jedna baza.",
      origin: "request",
      approved: true,
    },
    {
      key: "p2",
      question: "Czy możesz pracować 2 dni w tygodniu z biura w Warszawie albo Gdańsku?",
      idealAnswer: "Tak, mieszka w zasięgu dojazdu albo dojeżdża regularnie.",
      dealBreaker: "Tylko praca w pełni zdalna.",
      origin: "ai",
      approved: false,
    },
  ],
  // Propozycja v2 (23.09.2026): reszta profilu z chipami źródła.
  experience: {
    domains: [{ name: "płatności kartowe", level: "must", min_years: 2, note: "" }],
    certifications: [],
    regulations: [{ name: "PCI DSS", level: "nice", min_years: null, note: "" }],
    notes: "",
  },
  searchExclude: [],
  targetCompanies: "Asseco, Comarch, Nets",
  disqualifiers: [],
  sellingPoints: "Greenfield na mikroserwisach, projekt na 12 miesięcy z opcją przedłużenia.",
  language: "PL, EN B2",
  contractLength: "12 mies. z opcją przedłużenia",
  askClient: [
    { key: "a1", text: "Ile etapów ma rekrutacja i kto decyduje?" },
    { key: "a2", text: "Jak duży jest zespół i w jakim języku pracuje?" },
  ],
  // 25.09.2026: hiring manager z podpisu maila — nowa osoba dla klienta.
  hiringManager: {
    kind: "new",
    name: "Anna Przykładowa",
    position: "Kierownik Zespołu Płatności",
    email: null,
  },
  provenance: {
    hiring_manager: "request",
    deadline: "request",
    headcount: "request",
    role: "request",
    client_title: "request",
    requirements: "request",
    rate: "request",
    about: "request",
    experience: "request",
    questions: "ai",
    target_companies: "client_history",
    selling_points: "client_history",
    ask_client: "ai",
  },
};

const EVIDENCE = [
  "Senior Java Developera",
  "projekt migracji core'u na mikroserwisy",
  "Java 17+, Spring Boot, Kafka",
  "PostgreSQL",
  "Kubernetes",
  "5 lat",
  "hybrydowa — 2 dni",
  "Warszawie",
  "do 170 zł/h netto",
  "1 listopada",
  "Potrzebujemy 2 osób",
  "do 20 października",
  "transakcyjność w systemach rozproszonych",
];

const STATES: Record<string, NewJobPagePreview> = {
  request: {
    step: "request",
    client: CLIENT,
    requestText: REQUEST,
    form: EMPTY_INTAKE_FORM,
    evidence: [],
  },
  noclient: {
    step: "request",
    client: null,
    source: "manual",
    requestText: "",
    form: EMPTY_INTAKE_FORM,
    evidence: [],
  },
  manual: {
    step: "review",
    client: CLIENT,
    source: "manual",
    requestText: "",
    form: EMPTY_INTAKE_FORM,
    evidence: [],
    categories: CATEGORIES,
    criticalInfo: { ...CRITICAL_INFO, info: {} },
  },
  review: {
    step: "review",
    client: CLIENT,
    requestText: REQUEST,
    form: FULL_FORM,
    evidence: EVIDENCE,
    categories: CATEGORIES,
    criticalInfo: CRITICAL_INFO,
  },
  gaps: {
    step: "review",
    client: CLIENT,
    requestText: REQUEST.replace("Budżet do 170 zł/h netto B2B. ", ""),
    form: {
      ...FULL_FORM,
      rateBudget: "",
      // Brak decyzji o krytycznych — blokuje przekazanie do searchu.
      rows: ROWS.map((row) => (row.level === "critical" ? { ...row, level: "must" } : row)),
      // Pytanie bez odpowiedzi, która odpada, i niepotwierdzona kategoria.
      questions: FULL_FORM.questions.map((q, i) =>
        i === 1 ? { ...q, dealBreaker: "", approved: false } : q,
      ),
      categoryConfirmed: false,
      // Klient nie podał hiring managera ani terminu — DL jeszcze nie zdecydował.
      hiringManager: null,
      deadline: "",
    },
    evidence: EVIDENCE.filter((e) => e !== "do 170 zł/h netto"),
    categories: CATEGORIES,
    criticalInfo: CRITICAL_INFO,
    // Delivery Lead wskazał prowadzącego sam.
    recruiterId: 31,
  },
};

const PORTALS_OFF: PortalConfigResponse = {
  any_ready: false,
  portals: [
    { portal: "rocketjobs", label: "RocketJobs", state: "disabled", enabled: false },
    { portal: "justjoinit", label: "JustJoin.IT", state: "disabled", enabled: false },
  ],
};

const PORTALS_ON: PortalConfigResponse = {
  any_ready: true,
  portals: [
    { portal: "rocketjobs", label: "RocketJobs", state: "ready", enabled: true },
    { portal: "justjoinit", label: "JustJoin.IT", state: "ready", enabled: true },
  ],
};

const DICTIONARY: BoardDictionaries = {
  categories: [
    { key: "java", name: "Java" },
    { key: "devops", name: "DevOps" },
    { key: "testing", name: "Testing" },
  ],
  experience_levels: [
    { key: "junior", name: "Junior" },
    { key: "mid", name: "Mid" },
    { key: "senior", name: "Senior" },
  ],
  working_times: [
    { key: "full_time", name: "Pełny etat" },
    { key: "freelance", name: "Freelance" },
  ],
  workplace_types: [
    { key: "remote", name: "Zdalnie" },
    { key: "hybrid", name: "Hybrydowo" },
    { key: "office", name: "Biuro" },
  ],
};

STATES.portals = {
  ...STATES.review,
  portalPlan: {
    portals: ["rocketjobs", "justjoinit"],
    draft: {
      publicTitle: "Senior Java Developer — płatności kartowe",
      subtitle: "Migracja na mikroserwisy, 12 miesięcy, hybrydowo w Warszawie",
      about:
        "Dołączysz do zespołu, który przenosi system płatności kartowych z monolitu na mikroserwisy (Java 17, Spring Boot, Kafka). Projekt na ok. 12 miesięcy z opcją przedłużenia, 2 dni w tygodniu w biurze w Warszawie.",
    },
    options: {
      ...EMPTY_LISTING_OPTIONS,
      experience_level: "senior",
      working_time: "freelance",
      workplace_type: "hybrid",
      office_days: 2,
      city: "Warszawa",
    },
  },
  portalFindings: [
    {
      code: "money",
      message: "Opis zawiera kwotę — stawek nie publikujemy w treści ogłoszenia.",
      excerpt: "do 170 zł/h",
    },
  ],
};

STATES.resume = {
  ...STATES.request,
  requestText: "",
  unfinishedForms: [
    {
      id: 91,
      label: "Programista Java — płatności kartowe (ZOB 48213)",
      client_id: 1,
      client_name: "[Klient testowy]",
      source: "text",
      updated_at: "2026-10-03T14:12:00Z",
      expires_at: "2026-11-02T14:12:00Z",
      missing_count: 3,
    },
    {
      id: 92,
      label: "Analityk biznesowy",
      client_id: 1,
      client_name: "[Klient testowy]",
      source: "manual",
      updated_at: "2026-09-12T09:40:00Z",
      expires_at: "2026-10-12T09:40:00Z",
      missing_count: 6,
    },
  ],
};

STATES.servererror = {
  ...STATES.review,
  autosave: { status: "saved", at: "2026-10-04T10:42:00Z" },
  serverBlockers: [
    {
      code: "office_city",
      message: "Podaj miasto biura w lokalizacji oferty (tryb hybrydowy/stacjonarny).",
    },
    {
      code: "champion:rate_unresolved",
      message: "Stawka w profilu nie jest kwotą PLN/h — popraw ją w Profilu Championa.",
    },
  ],
};

STATES.review = {
  ...STATES.review,
  autosave: { status: "saved", at: "2026-10-04T10:42:00Z" },
};

// Bez `assignment`: Delivery Lead niczego nie zaznaczył, więc działa automat.
STATES.shadow = STATES.review;
STATES.off = STATES.review;

STATES.passive = {
  ...STATES.review,
  priorityLevel: "accepting",
};

/** Tryb automatu przydziału w danym stanie podglądu (`null` = wyłączony). */
function allocationMode(stateKey: string): "auto" | "shadow" | null {
  if (stateKey === "off") return null;
  return stateKey === "shadow" ? "shadow" : "auto";
}

function Harness() {
  const params = useSearchParams();
  const stateKey = params?.get("state") ?? "review";
  const state = STATES[stateKey] ?? STATES.review;
  const [client] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { staleTime: Infinity, retry: false } },
    });
    qc.setQueryData(["clients-lookup-new-job"], [CLIENT]);
    qc.setQueryData(
      ["handoff-recruiters"],
      [
        { id: 31, name: "[Rekruterka A]" },
        { id: 32, name: "[Rekruter B]" },
      ],
    );
    qc.setQueryData(
      jobPortalKeys.config,
      stateKey === "portals" ? PORTALS_ON : PORTALS_OFF,
    );
    qc.setQueryData(jobPortalKeys.dictionaries("rocketjobs"), DICTIONARY);
    // Pole „Rekruter prowadzący”: czy automat przydziału da się wybrać i w jakim trybie.
    qc.setQueryData(
      ["job-intake-handoff-options"],
      allocationMode(stateKey)
        ? { automatic_enabled: true, mode: allocationMode(stateKey) }
        : { automatic_enabled: false, mode: "off" },
    );
    // Lista kontaktów klienta w polu „Hiring manager” (`hiringManagerOptionsKey`).
    qc.setQueryData(["hiring-manager-options", 1], [
      { id: 501, name: "Tomasz Przykładowy", position: "Dyrektor IT" },
      { id: 502, name: "Ewa Wzorcowa", position: null },
    ]);
    return qc;
  });
  return (
    <QueryClientProvider client={client}>
      {/* Te same odstępy co `<main>` w `AppShellV2` (`p-4 md:p-6`) — stopka
          strony wychodzi na krawędź ujemnym marginesem liczonym pod nie;
          bez nich harness dawał poziomy scroll, którego na produkcji nie ma. */}
      <div className="min-h-dvh bg-background p-4 pb-24 md:p-6">
        <NewJobPage key={params?.get("state") ?? "review"} preview={state} />
      </div>
    </QueryClientProvider>
  );
}

export default function NewJobPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
