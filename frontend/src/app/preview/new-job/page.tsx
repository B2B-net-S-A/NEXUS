"use client";

/**
 * Harness `/preview/new-job` — strona „Nowa rekrutacja” na danych fikcyjnych.
 *
 * `?state=request|review|gaps|portals`. Zero zapytań: klucze klientów,
 * rekruterów, konfiguracji portali i słownika RocketJobs są zasiane w cache
 * (patrz `app/preview/__tests__`), a baner podobnych rekrutacji nie renderuje
 * się w trybie podglądu. `portals` = krok „Ogłoszenie na portalach” z gotowym
 * szkicem (na produkcji portale są dziś wyłączone flagami).
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  NewJobPage,
  type NewJobPagePreview,
} from "@/components/v2/jobs/new/NewJobPage";
import { EMPTY_INTAKE_FORM, type IntakeForm } from "@/lib/job-request-intake";
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

Na rozmowie zapytamy o transakcyjność w systemach rozproszonych.

Pozdrawiam
Anna Przykładowa
Kierownik Zespołu Płatności`;

const FULL_FORM: IntakeForm = {
  ...EMPTY_INTAKE_FORM,
  title: "Senior Java Developer",
  clientTitle: "Programista Java — płatności kartowe (ZOB 48213)",
  clientReference: "ZOB 48213",
  must: ["Java 17+", "Spring Boot", "Kafka", "PostgreSQL"],
  nice: ["Kubernetes"],
  seniorityYears: 5,
  rateBudget: "170",
  remotePolicy: "hybrid",
  onsiteDays: "2",
  city: "Warszawa",
  startDate: "2026-11-01",
  about:
    "Migracja systemu płatności kartowych z monolitu na mikroserwisy. Projekt na ok. 12 miesięcy z opcją przedłużenia.",
  questions: [
    {
      key: "p1",
      question: "Jak zapewniałeś transakcyjność w systemie rozproszonym?",
      idealAnswer: "Saga / outbox, idempotencja, przykład z produkcji.",
      origin: "request",
    },
    {
      key: "p2",
      question: "Czy możesz pracować 2 dni w tygodniu z biura w Warszawie?",
      idealAnswer: "",
      origin: "ai",
    },
  ],
  // Propozycja v2 (23.09.2026): reszta profilu z chipami źródła.
  experience: {
    domains: [{ name: "płatności kartowe", level: "must", min_years: 2, note: "" }],
    certifications: [],
    regulations: [{ name: "PCI DSS", level: "nice", min_years: null, note: "" }],
    notes: "",
  },
  searchKeywords: "Senior Java Developer, Spring Boot, Kafka, płatności kartowe",
  // 25.09.2026: wymagania do wyszukiwania w bazie — propozycja Luny z maila.
  searchRequirements: [["Java"], ["Spring Boot"], ["Kafka"]],
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
    role: "request",
    must: "request",
    nice: "request",
    rate: "request",
    about: "request",
    experience: "request",
    search_requirements: "request",
    search_keywords: "ai",
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
  review: {
    step: "review",
    client: CLIENT,
    requestText: REQUEST,
    form: FULL_FORM,
    evidence: EVIDENCE,
    recruiterId: 31,
  },
  gaps: {
    step: "review",
    client: CLIENT,
    requestText: REQUEST.replace("Budżet do 170 zł/h netto B2B. ", ""),
    form: {
      ...FULL_FORM,
      rateBudget: "",
      questions: FULL_FORM.questions.slice(0, 1),
      // Luna nie znalazła wymagań do wyszukiwania — brak blokuje przekazanie.
      searchRequirements: [],
      provenance: Object.fromEntries(
        Object.entries(FULL_FORM.provenance).filter(([key]) => key !== "search_requirements"),
      ),
    },
    evidence: EVIDENCE.filter((e) => e !== "do 170 zł/h netto"),
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
    // Lista kontaktów klienta w polu „Hiring manager” (`hiringManagerOptionsKey`).
    qc.setQueryData(["hiring-manager-options", 1], [
      { id: 501, name: "Tomasz Przykładowy", position: "Dyrektor IT" },
      { id: 502, name: "Ewa Wzorcowa", position: null },
    ]);
    return qc;
  });
  return (
    <QueryClientProvider client={client}>
      <div className="min-h-dvh bg-background">
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
