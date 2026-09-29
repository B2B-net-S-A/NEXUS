"use client";

// Publiczny harness „Po ludzku” (29.09.2026): blok na górze Podglądu Championa
// i „Ściąga do rozmowy” z doku osoby. Dane fikcyjne, ZERO zapytań: każde
// wyjaśnienie jest zasiane w cache pod tym samym kluczem, którego używa
// komponent (`plainBriefQueryKey`, `roleProfilesQueryKey`), a interceptor
// odcina sieć — „Odśwież” i „Dopisz do „Do dopytania”” kończą się błędem,
// nic nie trafia do API (pilnuje `harness-seeds.test.ts`).
//
// `?state=closed` — rekrutacja zamknięta bez wyjaśnienia (przycisk),
// `?state=failed` — generacja się nie udała (zapisane teksty + komunikat).

import { useEffect, useMemo, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { ToastProvider } from "@/components/Toast";
import { DockCallCheatsheet } from "@/components/v2/jobs/DockCallCheatsheet";
import { api } from "@/lib/api";
import {
  plainBriefQueryKey,
  roleProfilesQueryKey,
  type PlainBrief,
  type RoleProfileListItem,
} from "@/lib/api/plainKnowledge";

const JOB_ID = 1;

const READY: PlainBrief = {
  job_id: JOB_ID,
  status: "ready",
  stale: false,
  is_open: true,
  can_refresh: true,
  can_change_role: true,
  generated_at: "2026-09-29T08:12:00Z",
  message: null,
  one_liner:
    "Szukamy programisty Javy, który rozwija system płatności kartą w Banku Przykładowym — tę część, która w ułamku sekundy mówi sklepowi „płatność przyjęta”.",
  example:
    "Gdy płacisz kartą w sklepie, terminal pyta bank, czy masz środki. Ta osoba pisze program, który odbiera to pytanie, sprawdza konto i odpowiada — zanim kasjerka zdąży zapakować zakupy.",
  day_to_day: [
    "Dopisuje nowe funkcje do systemu obsługi płatności (np. płatności odroczone).",
    "Poprawia błędy zgłoszone przez zespół wsparcia i sprawdza, czy system wytrzymuje ruch w święta.",
    "Omawia zmiany z analitykiem i testerem na krótkich spotkaniach zespołu.",
  ],
  pitch:
    "Dzień dobry, dzwonię z B2B.net w sprawie projektu w Banku Przykładowym: rozwój systemu płatności kartą, Java i Spring Boot, praca zdalna z wizytą w biurze raz w miesiącu. Stawka do 150 zł/h netto na B2B. Czy ma Pan chwilę, żebym opowiedziała więcej?",
  candidate_qa: [
    {
      key: "client",
      question: "Co to za klient?",
      answer: "Bank Przykładowy — średni bank detaliczny, zespół płatności kartowych w Warszawie.",
      source: "karta klienta",
    },
    { key: "rate", question: "Jaka stawka?", answer: "Do 150 zł/h netto, B2B.", source: "sekcja 1" },
    {
      key: "mode",
      question: "Zdalnie czy w biurze?",
      answer: "Zdalnie, raz w miesiącu spotkanie w biurze w Warszawie.",
      source: "sekcja 1",
    },
    { key: "team", question: "Jak duży jest zespół?", answer: null, source: null },
    {
      key: "process",
      question: "Ile etapów rekrutacji?",
      answer: "Dwa: rozmowa techniczna i krótkie spotkanie z kierownikiem zespołu.",
      source: "sekcja 5",
    },
  ],
  screening_plain: [
    {
      question_id: "q1",
      question: "„Opisz ostatni system w Spring Boocie, który rozwijałeś”",
      why: "Sprawdzasz, czy kandydat naprawdę pisał usługi w Springu, a nie tylko o nim czytał.",
      good: "Mówi, z jakich części składał się system, co sam napisał i jak to testował.",
      reject: "Pracował tylko przy utrzymaniu, bez pisania nowego kodu w Springu.",
      original: {
        ideal_answer: "Konkretny projekt, własny wkład, REST + testy integracyjne.",
        deal_breaker: "Wyłącznie utrzymanie aplikacji (L2/L3).",
      },
    },
    {
      question_id: "q2",
      question: "„Jak używałeś Kafki?”",
      why: "Kafka to kolejka wiadomości — klient chce kogoś, kto ją zna z praktyki.",
      good: "Wie, co to temat i konsument, opowiada o konkretnej integracji.",
      reject: null,
      original: { ideal_answer: "Producent/konsument, obsługa błędów, retry.", deal_breaker: null },
    },
    {
      question_id: "q3",
      question: "„Od kiedy może Pan zacząć?”",
      why: "Klient chce startu w listopadzie.",
      good: "Najpóźniej na początku listopada.",
      reject: "Okres wypowiedzenia dłuższy niż 2 miesiące.",
      original: { ideal_answer: "Listopad", deal_breaker: "Wypowiedzenie > 2 mies." },
    },
  ],
  glossary: [
    {
      term_key: "java",
      display_name: "Java",
      level: "must",
      level_label: "wymagane",
      status: "ready",
      summary: "Język programowania, w którym bank pisze większość swoich systemów.",
      does: "Z niego powstają programy działające na serwerach banku.",
      cv_hints: ["Java 17", "Java 11", "JVM"],
      confused_with: "JavaScript to zupełnie inny język (strony WWW) — nie liczy się jako Java.",
      in_this_project: "Cały system płatności jest napisany w Javie.",
      sources: [{ url: "https://pl.wikipedia.org/wiki/Java", title: "Java — Wikipedia" }],
      origin: "seed",
    },
    {
      term_key: "kafka",
      display_name: "Kafka",
      level: "must",
      level_label: "wymagane",
      status: "ready",
      summary: "Taśmociąg, po którym systemy banku przesyłają sobie wiadomości, np. „płatność przyjęta”.",
      does: null,
      cv_hints: ["Apache Kafka", "Confluent", "Kafka Streams"],
      confused_with: "RabbitMQ robi podobną rzecz — to plus, ale nie zamiennik.",
      in_this_project: "Po niej płyną transakcje z terminali do księgowania.",
      sources: [{ url: "https://kafka.apache.org/intro", title: "Apache Kafka — wprowadzenie" }],
      origin: "ai",
    },
    {
      term_key: "kubernetes",
      display_name: "Kubernetes",
      level: "nice",
      level_label: "mile widziane",
      status: "researching",
      summary: null,
      does: null,
      cv_hints: ["K8s", "OpenShift"],
      confused_with: null,
      in_this_project: null,
      sources: [],
      origin: null,
    },
    {
      term_key: "psd2",
      display_name: "PSD2",
      level: "experience",
      level_label: "doświadczenie · min. 2 lata",
      status: "missing",
      summary: null,
      does: null,
      cv_hints: [],
      confused_with: null,
      in_this_project: null,
      sources: [],
      origin: null,
    },
  ],
  role: {
    id: 7,
    slug: "java-backend-bankowosc",
    name: "Java backend w bankowości",
    summary: "Programista, który pisze niewidoczną dla klienta część systemów bankowych.",
    example: null,
    day_to_day: [],
    candidate_questions: [],
    typical_skills: ["Java", "Spring Boot", "Kafka"],
    sources: [],
    origin: "seed",
    status: "ready",
    assignment: "auto",
    stats: {
      jobs: 38,
      clients: 9,
      hires: 11,
      hired_titles: [
        { title: "Java Developer", count: 6 },
        { title: "Backend Engineer", count: 3 },
      ],
    },
  },
  client: {
    id: 1,
    name: "Bank Przykładowy",
    about:
      "Średni bank detaliczny z siedzibą w Warszawie. Rozwija własne systemy płatności i aplikację mobilną.",
    origin: "web",
    sources: [{ url: "https://example.com/bank-przykladowy", title: "Bank Przykładowy — o nas" }],
  },
};

const STATES: Record<string, PlainBrief> = {
  ready: READY,
  closed: {
    ...READY,
    status: "none",
    stale: true,
    is_open: false,
    can_change_role: false,
    generated_at: null,
    one_liner: null,
    example: null,
    day_to_day: [],
    pitch: null,
    candidate_qa: [],
    screening_plain: [],
    glossary: [],
    role: null,
    client: null,
  },
  failed: {
    ...READY,
    status: "failed",
    can_change_role: false,
    message: "Nie udało się przygotować wyjaśnienia — spróbuj „Odśwież”.",
    example: null,
    screening_plain: READY.screening_plain.slice(0, 1),
  },
};

const ROLES: RoleProfileListItem[] = [
  {
    id: 7,
    slug: "java-backend-bankowosc",
    name: "Java backend w bankowości",
    summary: null,
    origin: "seed",
    status: "ready",
    jobs: 38,
    updated_at: "2026-09-20T10:00:00Z",
  },
  {
    id: 8,
    slug: "tester-automatyzujacy",
    name: "Tester automatyzujący",
    summary: null,
    origin: "ai",
    status: "ready",
    jobs: 14,
    updated_at: "2026-09-18T10:00:00Z",
  },
];

export default function PlainBriefPreviewPage() {
  const [state, setState] = useState<string>("ready");
  const [ready, setReady] = useState(false);

  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false },
        mutations: { retry: false },
      },
    });
    qc.setQueryData(roleProfilesQueryKey(""), { items: ROLES });
    return qc;
  }, []);

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("state");
    const key = requested && requested in STATES ? requested : "ready";
    queryClient.setQueryData(plainBriefQueryKey(JOB_ID), STATES[key]);
    setState(key);
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, [queryClient]);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto max-w-6xl space-y-4 px-4 py-6">
          <h1 className="text-lg font-semibold">Podgląd: „Po ludzku” i ściąga do rozmowy</h1>
          <nav className="flex flex-wrap gap-2 text-sm" aria-label="Stan">
            {Object.keys(STATES).map((key) => (
              <a
                key={key}
                href={`?state=${key}`}
                aria-current={state === key ? "page" : undefined}
                className={
                  state === key
                    ? "rounded-md bg-primary/10 px-2.5 py-1 font-medium text-primary"
                    : "rounded-md px-2.5 py-1 text-muted-foreground hover:bg-muted"
                }
              >
                {key}
              </a>
            ))}
          </nav>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <section className="min-w-0 space-y-2" aria-label="Podgląd Championa">
              <p className="text-xs text-muted-foreground">Zlecenie i Champion → Podgląd</p>
              <PlainBriefBlock jobId={JOB_ID} />
            </section>
            <section className="min-w-0 space-y-2" aria-label="Dok osoby">
              <p className="text-xs text-muted-foreground">Tablica → dok osoby → Screening</p>
              <div className="rounded-xl border border-border bg-card p-3">
                <DockCallCheatsheet jobId={JOB_ID} />
              </div>
            </section>
          </div>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
