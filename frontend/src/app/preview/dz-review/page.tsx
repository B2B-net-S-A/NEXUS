"use client";

// Publiczny harness przeglądu DZ i paska „Do Cpro wysyła” (0353). Dane
// fikcyjne, ZERO zapytań: przegląd renderuje `DzReviewBody` z propsów, klucz
// katalogu osób jest zasiany, a interceptor odcina sieć (pilnuje
// `harness-seeds.test.ts`).

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { DzReviewBody } from "@/components/v2/dashboard/DzReviewDialog";
import { CproSenderBar } from "@/components/v2/jobs/CproSenderBar";
import { api } from "@/lib/api";
import type { DzHints, DzReview } from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

const REVIEW: DzReview = {
  stage_id: 1,
  candidate_id: 1,
  candidate_name: "Jan Przykładowy",
  job_id: 1,
  job_title: "Senior Java Developer",
  client_name: "Bank Przykładowy",
  client_request: {
    must: ["Java", "Spring Boot", "Kubernetes", "Kafka"],
    nice: ["AWS", "Terraform"],
    description:
      "Zespół platformy płatności. Szukamy seniora Java ze Spring Boot, doświadczeniem w Kubernetes i systemach zdarzeniowych (Kafka). Praca hybrydowa, 2 dni w biurze w Warszawie.",
    project_about: "Przebudowa rozliczeń kartowych na mikroserwisy.",
  },
  generated_cv: {
    source: "branded_draft",
    stage_id: 1,
    generated_document_id: 10,
    updated_at: "2026-09-22T10:00:00Z",
    blocks: [
      { kind: "h", section: "summary", runs: [{ t: "Podsumowanie", b: false }] },
      {
        kind: "p",
        section: null,
        runs: [
          { t: "Programista ", b: false },
          { t: "Java", b: true },
          { t: " z 9 latami doświadczenia w bankowości; buduje mikroserwisy w ", b: false },
          { t: "Spring Boot", b: true },
          { t: " i utrzymuje je na Kubernetes.", b: false },
        ],
      },
      { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Senior Java Developer", b: true }, { t: " 2021 – obecnie", b: false }] },
      { kind: "p", section: "employer", runs: [{ t: "Bank Alfa · Bankowość", b: false }] },
      { kind: "li", section: null, runs: [{ t: "Mikroserwisy płatności w ", b: false }, { t: "Java", b: true }, { t: " i Spring Boot.", b: false }] },
      { kind: "li", section: null, runs: [{ t: "Wdrożenia na ", b: false }, { t: "Kubernetes", b: true }, { t: " (Helm).", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Java Developer", b: true }, { t: " 2017 – 2021", b: false }] },
      { kind: "p", section: "employer", runs: [{ t: "Ubezpieczenia Beta", b: false }] },
      { kind: "li", section: null, runs: [{ t: "Integracje REST, ", b: false }, { t: "React", b: true }, { t: " w panelu agenta.", b: false }] },
    ],
  },
  original_cv: {
    source: "snapshot",
    stage_id: 1,
    filename: "jan_przykladowy_cv.pdf",
    text:
      "Jan Przykładowy — Senior Java Developer\n\nBank Alfa (2021 – obecnie)\nMikroserwisy płatności: Java 17, Spring Boot, Kafka, Kubernetes, Helm.\n\nUbezpieczenia Beta (2017 – 2021)\nIntegracje REST w Java 11, Kafka, panel agenta w React.\n\nSoftware House Gamma (2015 – 2017)\nJava, SQL, Spring.",
  },
  checks: [
    { label: "Java", in_cv: true, bolded: true, in_original: true, original_roles: ["Bank Alfa", "Ubezpieczenia Beta", "Software House Gamma"], missing_in_roles: ["Java Developer · Ubezpieczenia Beta"], roles_absent: ["Software House Gamma"] },
    { label: "Spring Boot", in_cv: true, bolded: true, in_original: true, original_roles: ["Bank Alfa"], missing_in_roles: [], roles_absent: [] },
    { label: "Kubernetes", in_cv: true, bolded: true, in_original: true, original_roles: ["Bank Alfa"], missing_in_roles: [], roles_absent: [] },
    { label: "Kafka", in_cv: false, bolded: false, in_original: true, original_roles: ["Bank Alfa", "Ubezpieczenia Beta"], missing_in_roles: ["Senior Java Developer · Bank Alfa", "Java Developer · Ubezpieczenia Beta"], roles_absent: [] },
  ],
  extra_bold: ["React"],
  summary: { must_total: 4, must_in_cv: 3, must_bolded: 3, roles_missing: 3, generated_roles: 2 },
};

const HINTS: DzHints = {
  status: "ok",
  verdict: "fix",
  model: "gpt-6-luna",
  cached: false,
  hints: [
    { kind: "missing_must", severity: "high", must_have: "Kafka", message: "Kafka jest must-have i występuje w dwóch rolach oryginału, a w CV dla klienta nie ma jej wcale — dopisz ją w Bank Alfa i Ubezpieczenia Beta.", quote: "Java 17, Spring Boot, Kafka, Kubernetes, Helm." },
    { kind: "not_bolded", severity: "medium", must_have: null, message: "Pogrubione jest „React”, którego klient nie wymaga — zdejmij pogrubienie, żeby nie odciągało uwagi od must-have.", quote: null },
    { kind: "missing_in_role", severity: "medium", must_have: "Java", message: "W roli Ubezpieczenia Beta brakuje wzmianki o Java (oryginał: „Integracje REST w Java 11”).", quote: "Integracje REST w Java 11" },
  ],
};

export default function DzReviewPreviewPage() {
  const [ready, setReady] = useState(false);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    qc.setQueryData(["users-directory", "cpro-assignees"], [
      { id: 1, name: "Preview Rekruter" },
      { id: 2, name: "Marta Kowalska" },
    ]);
    return qc;
  });

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Rekruter",
        role: "head_of_recruitment",
        roles: ["head_of_recruitment"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
      },
      token: "preview",
    } as never);
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-6 sm:px-6">
          <div>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Przegląd przed DZ</p>
            <h1 className="text-lg font-semibold">
              {REVIEW.candidate_name}
              <span className="font-normal text-muted-foreground"> — {REVIEW.job_title} · {REVIEW.client_name}</span>
            </h1>
          </div>
          <DzReviewBody
            review={REVIEW}
            hints={HINTS}
            hintsLoading={false}
            hintsFailed={false}
            onRetryHints={() => undefined}
            onOpenOriginal={() => undefined}
          />
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">Tablica rekrutacji Nordei — pasek nad kolumnami</h2>
            <CproSenderBar jobId={1} senderId={2} senderName="Marta Kowalska" waiting={3} canChange />
          </section>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
