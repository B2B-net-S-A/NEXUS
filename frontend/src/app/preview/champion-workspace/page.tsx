"use client";

/**
 * Harness `/preview/champion-workspace` — „Profil Championa” w czterech
 * zakładkach (04.10.2026) na danych fikcyjnych. Repo jest publiczne, więc
 * żadnych prawdziwych osób ani klientów.
 *
 * `?ptab=brief|tech|client|team` — zakładka, `?drawer=conditions|search|…`
 * — otwarta szuflada edycji bloku, `?as=dl|recruiter` (domyślnie `dl`) —
 * Delivery Lead widzi pasek „Do dopięcia” i przyciski „Edytuj”, rekruter czyta.
 *
 * ZERO zapytań: klucze, o które pytają zakładki, są zasiane w cache, a
 * interceptor odcina sieć — przyciski kończą się komunikatem o błędzie i nic
 * nie trafia do API.
 */

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { ChampionWorkspace, type ChampionWorkspaceJob } from "@/components/champion/ChampionWorkspace";
import { api, type ChampionProfileResponse } from "@/lib/api";
import { plainBriefQueryKey, type PlainBrief } from "@/lib/api/plainKnowledge";
import { jobPortalKeys } from "@/lib/api/jobPortals";
import { categoryRecruitersQueryKey } from "@/lib/api/requestAllocation";
import { clientQuestionPoolQueryKey } from "@/lib/api/interviewCycle";
import { CHAMPION_BLOCKS, resolveChampionTab, type ChampionBlock, type ChampionTab } from "@/lib/champion-blocks";
import { hiringManagerOptionsKey } from "@/lib/hiring-manager";
import { priorityWorkQueryKeys } from "@/lib/priority-work-api";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 1;
const CLIENT_ID = 1;
const CATEGORY_ID = 2;
const DAY_MS = 86_400_000;
const SEED_FRESH = { updatedAt: Date.now() + DAY_MS };
const isoDay = (offsetDays: number) =>
  new Date(Date.now() + offsetDays * DAY_MS).toISOString().slice(0, 10);

const DELIVERY_LEAD = { id: 61, name: "Gosia Delivery" };
const RECRUITER = { id: 31, name: "Anna Przykładowa" };

type Persona = "dl" | "recruiter";

const PERSONAS: Record<Persona, { label: string; role: string; user: { id: number; name: string } }> = {
  dl: { label: "Delivery Lead", role: "delivery_lead", user: DELIVERY_LEAD },
  recruiter: { label: "Rekruter", role: "recruiter", user: RECRUITER },
};

const JOB: ChampionWorkspaceJob = {
  title: "Senior Java Developer — płatności kartowe",
  client_id: CLIENT_ID,
  client_name: "Bank Przykładowy S.A.",
  client_reference: "ZAP-2026-117",
  deadline: isoDay(9),
  deadline_time: null,
  description:
    "Poszukujemy doświadczonego programisty Java do zespołu rozwijającego system autoryzacji płatności kartowych. Wymagane: Java 17, Spring Boot, Kafka, testy automatyczne. Mile widziane: Kubernetes, doświadczenie w bankowości.",
  status: "published",
  delivery_lead_id: DELIVERY_LEAD.id,
  delivery_lead_user: { name: DELIVERY_LEAD.name },
  hiring_manager_contact_id: 501,
  hiring_manager_name: "Tomasz Przykładowy",
  competence_category_id: CATEGORY_ID,
  priority_level: "p1",
  headcount: 1,
  primary_owner: {
    id: RECRUITER.id,
    name: RECRUITER.name,
    email: "anna@example.com",
    role: "recruiter",
    is_active: true,
  },
  recruiters: [
    { user_id: RECRUITER.id, name: RECRUITER.name, via: "owner", proposed: false, assigned_by_name: DELIVERY_LEAD.name },
  ],
};

const PROFILE: ChampionProfileResponse = {
  job_id: JOB_ID,
  job_title: JOB.title ?? "",
  champion_profile: {
    basics: {
      role_name: "Senior Java Developer",
      rate_value: 150,
      work_mode: "hybrydowo",
      onsite_days_per_month: 2,
      candidate_location_pref: "Warszawa",
      start_date: "listopad 2026",
      contract_length: "12 miesięcy z przedłużeniem",
      seniority_min_years: 5,
      language: "PL, EN B2",
    },
    stack: {
      must: [{ name: "Java 17" }, { name: "Spring Boot" }, { name: "Kafka" }, { name: "Testy automatyczne" }],
      nice: [{ name: "Kubernetes" }, { name: "PSD2" }],
      notes: "",
    },
    experience: {
      domains: [{ name: "płatności kartowe", min_years: 2, level: "nice" }],
      certifications: [],
      regulations: [],
      notes: "",
    },
    search: {
      keywords: "",
      target_companies: "",
      disqualifiers: [],
      notes: "",
      requirements: [["java"], ["spring", "spring boot"], ["kafka"]],
      exclude: ["junior"],
    },
    project: {
      about:
        "Rozwój systemu autoryzacji płatności kartowych — części, która w ułamku sekundy odpowiada terminalowi w sklepie, czy płatność przechodzi. Zespół 8 osób, praca w dwutygodniowych sprintach.",
      responsibilities: "nowe funkcje (płatności odroczone)\nutrzymanie i poprawki\nprzeglądy kodu",
    },
    screening_questions: [
      {
        id: "q1",
        question: "Opisz ostatni system w Spring Boocie, który rozwijałeś — co napisałeś sam?",
        ideal_answer: "Konkretny projekt, własny wkład, REST + testy integracyjne.",
        deal_breaker: "Wyłącznie utrzymanie aplikacji (L2/L3).",
      },
      {
        id: "q2",
        question: "Jak używałeś Kafki w produkcji?",
        ideal_answer: "Producent/konsument, obsługa błędów, ponowienia.",
        deal_breaker: "",
      },
      {
        id: "q3",
        question: "Od kiedy możesz zacząć?",
        ideal_answer: "Najpóźniej na początku listopada.",
        deal_breaker: "Okres wypowiedzenia dłuższy niż 2 miesiące.",
      },
      { id: "q4", question: "Jak testujesz kod przed wdrożeniem?", ideal_answer: "", deal_breaker: "" },
    ],
    client: {
      selling_points:
        "Stabilny projekt na lata, nowoczesny stack (Java 17, Spring Boot 3), dwa dni w biurze w miesiącu, budżet do 150 zł/h netto.",
      sectors: ["bankowość"],
      historical_questions: "",
    },
    insights: [
      { id: "n1", topic: "ask_client", text: "Czy React jest wymagany, czy wystarczy chęć nauki?", source: "manual", audience: "team" },
      { id: "n2", topic: "ask_client", text: "Ile dni w biurze na start?", source: "manual", audience: "team" },
    ],
    verification: {
      client: { status: "pending" },
      consultant: { status: "pending" },
    },
    briefing: { status: "pending" },
  } as never,
  critical_resolution: {
    stored: ["Java 17", "Spring Boot"],
    decided: true,
    effective: ["Java 17", "Spring Boot"],
    source: "dl",
    suggested: ["Java 17"],
  } as never,
};

const glossaryTerm = (
  display_name: string,
  summary: string,
  cv_hints: string[],
  confused_with: string | null = null,
) => ({
  term_key: display_name.toLowerCase(),
  display_name,
  level: "must" as const,
  level_label: "wymagane",
  status: "ready" as const,
  summary,
  does: null,
  cv_hints,
  confused_with,
  in_this_project: null,
  sources: [{ url: "https://example.com/slowniczek", title: "Słowniczek — przykład" }],
  origin: "seed" as const,
});

const BRIEF: PlainBrief = {
  job_id: JOB_ID,
  status: "ready",
  stale: false,
  is_open: true,
  can_refresh: false,
  can_change_role: false,
  generated_at: new Date(Date.now() - DAY_MS).toISOString(),
  message: null,
  one_liner:
    "Szukamy programisty Javy, który rozwija system płatności kartą w Banku Przykładowym — tę część, która w ułamku sekundy mówi sklepowi „płatność przyjęta”.",
  example:
    "Gdy płacisz kartą w sklepie, terminal pyta bank, czy masz środki. Ta osoba pisze program, który odbiera to pytanie i odpowiada, zanim kasjer zdąży zapakować zakupy.",
  day_to_day: [
    "Dopisuje nowe funkcje do systemu płatności (np. płatności odroczone).",
    "Poprawia błędy zgłoszone przez wsparcie i sprawdza, czy system wytrzyma ruch w święta.",
    "Omawia zmiany z analitykiem i testerem na krótkich spotkaniach zespołu.",
  ],
  pitch: null,
  candidate_qa: [],
  screening_plain: [
    {
      question_id: "q1",
      question: "„Opisz ostatni system w Spring Boocie, który rozwijałeś”",
      why: "Sprawdzasz, czy kandydat naprawdę pisał usługi w Springu, a nie tylko o nim czytał.",
      good: "Mówi, z jakich części składał się system, co sam napisał i jak to testował.",
      reject: "Pracował tylko przy utrzymaniu, bez pisania nowego kodu.",
      original: { ideal_answer: "Konkretny projekt, własny wkład.", deal_breaker: "Wyłącznie utrzymanie." },
    },
  ],
  glossary: [
    glossaryTerm("Java 17", "Język programowania, w którym bank pisze większość systemów. „17” to wersja z 2021 roku lub nowsza.", ["Java 21", "JVM"], "JavaScript to inny język (strony WWW)."),
    glossaryTerm("Spring Boot", "Narzędzie do szybkiego budowania aplikacji w Javie — na nim stoi backend banku.", ["Spring", "Spring MVC"]),
    glossaryTerm("Kafka", "Taśmociąg, po którym systemy banku przesyłają sobie wiadomości, np. „płatność przyjęta”.", ["Apache Kafka", "Kafka Streams"], "RabbitMQ robi podobną rzecz — plus, ale nie zamiennik."),
    { ...glossaryTerm("Kubernetes", "", []), level: "nice", level_label: "mile widziane", status: "researching", summary: null, sources: [] },
  ],
  role: null,
  client: {
    id: CLIENT_ID,
    name: "Bank Przykładowy",
    about:
      "Średni bank detaliczny z siedzibą w Warszawie. Rozwija własne systemy płatności i aplikację mobilną; kandydaci cenią stabilność i długie projekty.",
    origin: "manual",
    sources: [],
  },
};

function seededClient(persona: Persona): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
  });
  qc.setQueryData(["champion-profile", JOB_ID], PROFILE, SEED_FRESH);
  qc.setQueryData(plainBriefQueryKey(JOB_ID), BRIEF, SEED_FRESH);
  qc.setQueryData(["client-cv-rule", CLIENT_ID], { is_active: true, cv_language: "pl" }, SEED_FRESH);
  // Rekrutacja przekazana (od 04.10.2026 każda nowa jest) — pasek pokazuje
  // tylko weryfikację z klientem, konsultantem i briefing.
  qc.setQueryData(
    ["job-readiness", JOB_ID],
    { job_id: JOB_ID, ready: true, blockers: [], closed: false, already_handed_off: true },
    SEED_FRESH,
  );
  qc.setQueryData(["handoff-recruiters"], [], SEED_FRESH);
  // Klient i historia.
  qc.setQueryData(
    ["client-playbook", CLIENT_ID],
    {
      client_id: CLIENT_ID,
      client_name: "Bank Przykładowy S.A.",
      exists: true,
      version: 3,
      sla_business_days: 3,
      sla_min_candidates: 2,
      cv_limit_per_process: 3,
      hold_hours: 48,
      multi_project_cooldown_days: 90,
      rate_policy: "Stawka do klienta ustalana przez Delivery Leada.",
      about_for_candidate: "Średni bank detaliczny, projekty na lata.",
      priority_rules: null,
      process_rules_md: "Dwa etapy: rozmowa techniczna i spotkanie z kierownikiem zespołu.",
      onboarding_md: null,
      documents: [],
      seed_key: null,
      updated_at: "2026-09-20T10:00:00Z",
      updated_by_name: DELIVERY_LEAD.name,
    },
    SEED_FRESH,
  );
  qc.setQueryData(
    clientQuestionPoolQueryKey("job", JOB_ID, 50),
    [
      { id: 1, text: "Jak testujesz kod przed wdrożeniem?", created_at: "2026-09-12T10:00:00Z" },
      { id: 2, text: "Opisz ostatni incydent na produkcji.", created_at: "2026-09-02T10:00:00Z" },
    ],
    SEED_FRESH,
  );
  qc.setQueryData(
    ["request-history", JOB_ID, false],
    {
      closed: [
        {
          job_id: 901,
          title: "Java Developer — bankowość",
          train_name: null,
          same_train: false,
          seniority: "senior",
          status: "closed",
          is_in_progress: false,
          outcome: "filled",
          close_reason: "filled_by_us",
          similarity: 0.79,
          similarity_source: "voyage",
          closed_at: "2026-06-30T00:00:00Z",
          created_at: "2026-04-01T00:00:00Z",
          tth_days: 41,
          client_id: CLIENT_ID,
          client_name: "Bank Przykładowy S.A.",
          champion_name: null,
          champion_candidate_id: null,
          champions_count: 1,
          candidates_count: 14,
          fee_rate: null,
          fee_currency: null,
          rate_unit: null,
          tac_name: null,
          delivery_lead_name: DELIVERY_LEAD.name,
        },
      ],
      in_progress: [],
      skill_frequency: {},
      meta: { sql_count: 1, voyage_count: 0, total: 1, skill_freq_sample: 0 },
    } as never,
    SEED_FRESH,
  );
  // Zespół i ogłoszenie (te same zasiewy co `/preview/job-team-panel`).
  qc.setQueryData(
    ["users-directory"],
    [
      { id: RECRUITER.id, name: RECRUITER.name, email: "anna@example.com", role: "recruiter", roles: ["recruiter"] },
      { id: DELIVERY_LEAD.id, name: DELIVERY_LEAD.name, email: "gosia@example.com", role: "delivery_lead", roles: ["delivery_lead"] },
    ],
    SEED_FRESH,
  );
  qc.setQueryData(["users-directory", "delivery-lead-roles"], [DELIVERY_LEAD], SEED_FRESH);
  qc.setQueryData(
    ["client-team", CLIENT_ID],
    {
      tacs: [],
      delivery_leads: [
        { id: 1, user_id: DELIVERY_LEAD.id, name: DELIVERY_LEAD.name, email: "gosia@example.com", role: "delivery_lead", created_at: "2026-09-01T08:00:00Z", is_head: true },
      ],
    },
    SEED_FRESH,
  );
  qc.setQueryData(
    ["competence-categories-active"],
    [{ id: CATEGORY_ID, slug: "software_development", name_pl: "Development", name_en: "Development", description: "", keywords: [], display_order: 2 }],
    SEED_FRESH,
  );
  qc.setQueryData(categoryRecruitersQueryKey(CATEGORY_ID), [], SEED_FRESH);
  qc.setQueryData(["users", "directory", "admin,delivery_lead,recruiter"], [], SEED_FRESH);
  qc.setQueryData(
    hiringManagerOptionsKey(CLIENT_ID),
    [{ id: 501, name: "Tomasz Przykładowy", position: "Dyrektor IT" }],
    SEED_FRESH,
  );
  qc.setQueryData(
    priorityWorkQueryKeys.job(JOB_ID),
    { mode: "off", plan: null, assignments: [], carry_over_count: 0, blockers: [] },
    SEED_FRESH,
  );
  qc.setQueryData(["job-allocation", JOB_ID], null, SEED_FRESH);
  qc.setQueryData(jobPortalKeys.config, { portals: [], any_ready: false }, SEED_FRESH);
  qc.setQueryData(["job", String(JOB_ID)], { ...JOB, id: JOB_ID, can_edit: persona === "dl" }, SEED_FRESH);
  return qc;
}

function blockFrom(value: string | null | undefined): ChampionBlock | null {
  return value && value in CHAMPION_BLOCKS ? (value as ChampionBlock) : null;
}

function Harness() {
  const params = useSearchParams();
  const persona: Persona = params?.get("as") === "recruiter" ? "recruiter" : "dl";
  const [tab, setTab] = useState<ChampionTab>(resolveChampionTab(params?.get("ptab")) ?? "brief");
  const [block, setBlock] = useState<ChampionBlock | null>(blockFrom(params?.get("drawer")));
  const [client, setClient] = useState<QueryClient | null>(null);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    return () => api.interceptors.request.eject(blocker);
  }, []);

  useEffect(() => {
    const { user, role } = PERSONAS[persona];
    useAuthStore.setState({
      user: {
        id: user.id,
        email: "preview@example.com",
        name: user.name,
        role,
        roles: [role],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      realUser: null,
      hydrated: true,
    });
    setClient(seededClient(persona));
  }, [persona]);

  if (!client) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  const dl = persona === "dl";

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh bg-background p-4 text-foreground md:p-6">
          <header className="mb-4 space-y-1">
            <h1 className="text-lg font-semibold">Podgląd: Profil Championa</h1>
            <nav aria-label="Zalogowana osoba" className="flex flex-wrap gap-x-3 text-sm">
              <span className="text-muted-foreground">Patrzy:</span>
              {(Object.keys(PERSONAS) as Persona[]).map((key) => (
                <Link
                  key={key}
                  href={`/preview/champion-workspace?as=${key}`}
                  aria-current={key === persona ? "page" : undefined}
                  className={key === persona ? "font-semibold text-primary" : "hover:underline"}
                >
                  {PERSONAS[key].label}
                </Link>
              ))}
            </nav>
            <p className="text-sm text-muted-foreground">Dane fikcyjne. Przyciski niczego nie zapisują.</p>
          </header>
          <ChampionWorkspace
            key={persona}
            jobId={JOB_ID}
            job={JOB}
            tab={tab}
            onTabChange={setTab}
            editBlock={block}
            onEditBlockChange={setBlock}
            canEditChampion={dl}
            canWritePipeline
            canSeeGate={dl}
            canEditJob={dl}
            canEditJobContent
            onEditJob={() => undefined}
            onEditFull={() => undefined}
            onOpenManualSearch={() => undefined}
            onWriteAnnouncement={dl ? () => undefined : undefined}
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function ChampionWorkspacePreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
