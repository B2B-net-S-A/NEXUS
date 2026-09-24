"use client";

/**
 * Harness `/preview/new-job` — strona „Nowa rekrutacja” na danych fikcyjnych.
 *
 * `?state=request|review|gaps`. Zero zapytań: klucze klientów i rekruterów są
 * zasiane w cache (patrz `app/preview/__tests__`), a baner podobnych
 * rekrutacji nie renderuje się w trybie podglądu.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  NewJobPage,
  type NewJobPagePreview,
} from "@/components/v2/jobs/new/NewJobPage";
import { EMPTY_INTAKE_FORM, type IntakeForm } from "@/lib/job-request-intake";

const CLIENT = { id: 1, name: "[Klient testowy]" };

const REQUEST = `Cześć,
szukamy Senior Java Developera do zespołu płatności kartowych (projekt migracji core'u na mikroserwisy, ok. 12 miesięcy z opcją przedłużenia).

Wymagania: Java 17+, Spring Boot, Kafka, doświadczenie z PostgreSQL. Mile widziane: Kubernetes.
Min. 5 lat doświadczenia komercyjnego.

Praca hybrydowa — 2 dni w tygodniu w biurze w Warszawie.
Budżet do 170 zł/h netto B2B. Start najlepiej 1 listopada.

Na rozmowie zapytamy o transakcyjność w systemach rozproszonych.

Pozdrawiam`;

const FULL_FORM: IntakeForm = {
  ...EMPTY_INTAKE_FORM,
  title: "Senior Java Developer",
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
  targetCompanies: "Asseco, Comarch, Nets",
  disqualifiers: [],
  sellingPoints: "Greenfield na mikroserwisach, projekt na 12 miesięcy z opcją przedłużenia.",
  language: "PL, EN B2",
  contractLength: "12 mies. z opcją przedłużenia",
  askClient: [
    { key: "a1", text: "Ile etapów ma rekrutacja i kto decyduje?" },
    { key: "a2", text: "Jak duży jest zespół i w jakim języku pracuje?" },
  ],
  provenance: {
    role: "request",
    must: "request",
    nice: "request",
    rate: "request",
    about: "request",
    experience: "request",
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
    },
    evidence: EVIDENCE.filter((e) => e !== "do 170 zł/h netto"),
  },
};

function Harness() {
  const params = useSearchParams();
  const state = STATES[params?.get("state") ?? "review"] ?? STATES.review;
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
