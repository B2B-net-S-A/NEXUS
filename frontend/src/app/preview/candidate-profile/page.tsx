"use client";

/**
 * Harness wizualny profilu kandydata — produkcyjny `CandidateDetailV2` bez API
 * i bez logowania. Zakładki przełącza `?tab=` (np. `?tab=recruitments`,
 * `?tab=activity&activity=notes`, `?tab=documents&documents=contracts`,
 * stare `?tab=matching` / `?tab=emails` też działają). `?employed=1` pokazuje
 * osobę pracującą u naszego klienta (dopisek w karcie osoby).
 *
 * ZERO zapytań sieciowych:
 *   1. cache react-query jest zasiany tymi samymi kluczami co komponenty
 *      (`candidateQueryKeys`, klucze z samych literałów) — ekran rysuje się
 *      od razu;
 *   2. zapytania, które i tak startują (np. `refetchOnMount: "always"` przy
 *      historii rekrutacji), obsługują lokalne interceptory axiosa z tych
 *      samych danych — żądanie nigdy nie wychodzi z przeglądarki (także
 *      sonda `/api/health` interceptora aplikacji). Nieznany adres dostaje
 *      lokalne 404 (sekcja pokazuje swój stan błędu, bez przerzutu na /login).
 * Dane są fikcyjne.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AxiosError,
  AxiosHeaders,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";

import api, { type CandidateNotesFacts } from "@/lib/api";
import type { CandidateCardOverview } from "@/lib/api/candidateCards";
import type { CandidateScreeningAnswers } from "@/lib/api/screeningAnswers";
import { ToastProvider } from "@/components/Toast";
import { CandidateDetailV2 } from "@/components/v2/pages/CandidateDetailV2";
import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "@/components/v2/pages/candidate-query-keys";
import { useAuthStore } from "@/store/auth";
import type { RateOverview } from "@/lib/api/candidateRates";

const CANDIDATE_ID = 9001;

// Osoby do oznaczenia przez „@” w notatce i czacie (fikcyjne).
const MENTIONABLE_USERS = [
  { id: 7, name: "Marta Nowak", email: "marta@example.com", role: "recruiter" },
  { id: 8, name: "Piotr Zieliński", email: "piotr@example.com", role: "delivery_lead" },
  { id: 9, name: "Łucja Żak", email: "lucja@example.com", role: "head_of_recruitment" },
  { id: 10, name: "Adam Wrona", email: "adam@example.com", role: "recruiter" },
  { id: 11, name: "Ewa Lis", email: "ewa@example.com", role: "talent_community_manager" },
  { id: 12, name: "Olga Sowa", email: "olga@example.com", role: "finance" },
  { id: 13, name: "Igor Kruk", email: "igor@example.com", role: "admin" },
];
const BASE_PATH = "/preview/candidate-profile";

const PREVIEW_USER = {
  id: 1,
  email: "preview@example.com",
  name: "Ola Nowak",
  role: "admin",
  roles: ["admin", "recruiter"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
};

const daysAgo = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
};

const CANDIDATE = {
  id: CANDIDATE_ID,
  // „Stawka od” (0414): najniższa z 18 miesięcy, ostatnio podana wyżej.
  rate_from_hourly: "120.00",
  rate_from_at: daysAgo(400),
  rate_from_stale: false,
  rate_latest_hourly: "160.00",
  rate_latest_at: daysAgo(20),
  rate_observation_count: 4,
  name: "Marta",
  lastname: "Kowalczyk",
  email: "marta.kowalczyk@example.com",
  phone: "+48 000 000 107",
  linkedin: "https://www.linkedin.com/in/przyklad",
  status: "active",
  competence_category_id: 2,
  competence_category: "software_development",
  position: "Senior Java Developer",
  years_it_experience: 8,
  city: "Warszawa",
  country: "PL",
  availability_status: "open_to_offers",
  availability_date: "2026-10-01",
  preferences: { remote_modes: ["remote", "hybrid"] },
  max_onsite_days_per_week: 2,
  tags: ["java", "fintech"],
  cv_filename: "CV_Marta_Kowalczyk.pdf",
  cv_parsed_at: daysAgo(10),
  ai_summary:
    "Doświadczona programistka Java (8 lat), ostatnio w systemach płatności. Mocna w Spring Boot i Kafce, zna AWS.",
  // Warianty tej samej nazwy („Kafka” / „Apache Kafka”, „Clean Code i SOLID”
  // / „Clean Code / SOLID”) łączą się w widoku (D3, 04.10.2026).
  skills: [
    { name: "Java", level: "expert", years: 8 },
    { name: "Spring Boot", level: "senior", years: 6 },
    { name: "Kafka", level: "mid", years: 3 },
    { name: "Apache Kafka", years: 4 },
    { name: "Clean Code i SOLID" },
    { name: "Clean Code / SOLID" },
    { name: "PostgreSQL", level: "mid", years: 5 },
    { name: "AWS" },
    { name: "Docker" },
    { name: "Kubernetes" },
    { name: "Git", level: "senior", years: 8 },
    { name: "Hibernate", level: "mid", years: 5 },
    { name: "JUnit", level: "mid", years: 6 },
    { name: "REST API" },
  ],
  verified_tech: ["Java", "Spring Boot"],
  experience: [
    {
      role: "Senior Java Developer",
      company: "Ailleron",
      start: "2022-03",
      end: "present",
      desc: "Systemy płatności dla banków: Java 17, Spring Boot, Kafka, PostgreSQL.",
    },
    {
      role: "Java Developer",
      company: "Asseco Poland",
      start: "2019-01",
      end: "2022-02",
      desc: "Moduły core banking, migracja na mikroserwisy.",
    },
  ],
  education: [
    { school: "Politechnika Warszawska", degree: "Magister", field: "Informatyka", end_year: 2017 },
  ],
  about: "Lubię porządne API i czyste testy.",
  employment: { state: "external" },
  identity_sync: null,
  legal_name: null,
  nip: null,
};

const HISTORY = {
  jobs: [
    {
      job_id: 501,
      job_title: "Java Developer",
      client_name: "Bank Przykładowy",
      job_status: "published",
      latest_stage: "cv_sent",
      latest_stage_id: null,
      first_seen: daysAgo(18),
      last_seen: daysAgo(3),
      next_action_owner: "client",
      // Najnowsze pierwsze — tak oddaje je `/history`.
      stages: [
        { stage: "cv_sent", moved_at: daysAgo(3) },
        { stage: "verified", moved_at: daysAgo(10) },
        { stage: "screening", moved_at: daysAgo(14) },
        { stage: "new", moved_at: daysAgo(18) },
      ],
      client_rate: { value: 185, unit: "hourly", currency: "PLN" },
      expected_rate: { value: 160, unit: "hourly", currency: "PLN" },
    },
    {
      job_id: 502,
      job_title: "Backend Engineer",
      client_name: "Ubezpieczenia Demo",
      job_status: "published",
      latest_stage: "verified",
      latest_stage_id: null,
      first_seen: daysAgo(18),
      last_seen: daysAgo(5),
      next_action_owner: "recruiter",
      stages: [
        { stage: "verified", moved_at: daysAgo(5) },
        { stage: "new", moved_at: daysAgo(18) },
      ],
      client_rate: null,
      expected_rate: { value: 160, unit: "hourly", currency: "PLN" },
    },
    {
      job_id: 480,
      job_title: "Java Tech Lead",
      client_name: "Telekom Demo",
      job_status: "closed",
      latest_stage: "rejected",
      latest_stage_id: null,
      first_seen: daysAgo(120),
      last_seen: daysAgo(100),
      rejection_reason: "Klient wybrał innego kandydata",
      next_action_owner: null,
      stages: [
        { stage: "rejected", moved_at: daysAgo(100) },
        { stage: "client_interview", moved_at: daysAgo(108) },
        { stage: "cv_sent", moved_at: daysAgo(112) },
        { stage: "verified", moved_at: daysAgo(118) },
      ],
      client_rate: null,
      expected_rate: null,
    },
    {
      job_id: 455,
      job_title: "Senior Java Developer",
      client_name: "Logistyka Demo",
      job_status: "closed",
      latest_stage: "withdrawn",
      latest_stage_id: null,
      first_seen: daysAgo(220),
      last_seen: daysAgo(205),
      next_action_owner: null,
      stages: [
        { stage: "withdrawn", moved_at: daysAgo(205) },
        { stage: "verified", moved_at: daysAgo(215) },
      ],
      client_rate: null,
      expected_rate: null,
    },
  ],
  contracts: [],
};

const TIMELINE = {
  timeline: [
    {
      type: "note",
      id: 71,
      timestamp: daysAgo(0),
      author_name: "Ola Nowak",
      content: "Potwierdziła dostępność od 01.10. Druga rozmowa w czwartek.",
    },
    {
      type: "stage_change",
      id: 72,
      job_id: 501,
      job_title: "Java Developer",
      stage: "cv_sent",
      moved_by_name: "Ola Nowak",
      timestamp: daysAgo(3),
    },
    {
      type: "stage_change",
      id: 73,
      job_id: 501,
      job_title: "Java Developer",
      stage: "verified",
      moved_by_name: "Ola Nowak",
      timestamp: daysAgo(5),
    },
  ],
};

// 0399: przypięta notatka, odpowiedź, długa notatka zwinięta, wpis automatu
// schowany za „Pokaż systemowe”, dwie rekrutacje w filtrze.
const NOTES = {
  items: [
    {
      id: 70,
      created_at: daysAgo(12),
      author_id: 2,
      author_name: "Kamil Wiśniewski",
      content: "Nie dzwonić przed 10:00 — prowadzi daily o 9:30.",
      pinned_at: daysAgo(3),
      pinned_by_name: "Ola Nowak",
      job_id: null,
      replies: [],
    },
    {
      id: 71,
      created_at: daysAgo(0),
      author_id: 1,
      author_name: "Ola Nowak",
      content: "Potwierdziła dostępność od 01.10. Druga rozmowa w czwartek.",
      job_id: 501,
      job_title: "Java Developer",
      replies: [
        {
          id: 75,
          created_at: daysAgo(0),
          author_id: 2,
          author_name: "Kamil Wiśniewski",
          content: "Klient potwierdził czwartek 14:00.",
          parent_note_id: 71,
          replies: [],
        },
      ],
    },
    {
      id: 72,
      created_at: daysAgo(20),
      author_id: 2,
      author_name: "Kamil Wiśniewski",
      content:
        "Rozmowa telefoniczna (25 min).\nObecnie: Java 17 + Spring Boot w projekcie bankowym, zespół 8 osób.\nSzuka projektu z większą odpowiedzialnością za architekturę.\nB2B, oczekiwania 160–170 zł/h netto, elastyczna przy dłuższym projekcie.\nHybryda do 2 dni w biurze w Warszawie.\nOkres wypowiedzenia: miesiąc.\nZna Kafkę produkcyjnie, K8s tylko od strony deploymentów.",
      job_id: 502,
      job_title: "Backend Engineer",
      replies: [],
    },
    {
      id: 73,
      created_at: daysAgo(25),
      author_id: null,
      author_name: null,
      content:
        "Auto-match 86/100 — kandydat dodany automatycznie po odczycie CV. Must-have: 3/3.",
      job_id: 502,
      job_title: "Backend Engineer",
      external_source: "system",
      is_system: true,
      group: "automat",
      replies: [],
    },
    // 03.10.2026: każdy rodzaj wpisu ma swoją zakładkę Historii.
    {
      id: 76,
      created_at: daysAgo(8),
      author_id: 1,
      author_name: "Ola Nowak",
      content: "Nie odebrał.",
      kind: "contact_attempt",
      group: "contact",
      job_id: null,
      replies: [],
    },
    {
      id: 77,
      created_at: daysAgo(9),
      author_id: 1,
      author_name: "Ola Nowak",
      content: "nie odbiera, poszedł mail",
      kind: "contact_attempt",
      group: "contact",
      job_id: null,
      replies: [],
    },
    {
      id: 78,
      created_at: daysAgo(4),
      author_id: 3,
      author_name: "Piotr Zieliński",
      content: "Dopisz do CV projekt płatności z 2024 r. i wróć do mnie.",
      kind: "dl_review",
      group: "delivery",
      job_id: 501,
      job_title: "Java Developer",
      replies: [],
    },
    {
      id: 79,
      created_at: daysAgo(4),
      author_id: 3,
      author_name: "Piotr Zieliński",
      content: "Notatka Delivery Leada o stawce do klienta — niewidoczna dla Twojej roli.",
      content_hidden: true,
      kind: "dl_rate",
      group: "delivery",
      job_id: 501,
      job_title: "Java Developer",
      replies: [],
    },
    {
      // Notatka z Traffita: HTML z pustymi akapitami `<p>&nbsp;</p>` —
      // zwinięty podgląd ma pokazać tekst, nie same wzmianki i „…”.
      id: 74,
      created_at: daysAgo(30),
      author_id: null,
      author_name: null,
      content:
        "<p>@Ola Nowak</p><p>&nbsp;</p><p>&nbsp;</p><p>Rozmowa po prezentacji projektu — kandydatka zainteresowana.</p><p>&nbsp;</p><p>Pyta o skład zespołu i o to, jak wygląda wdrożenie.</p><p>&nbsp;</p><p>Oczekiwania bez zmian: 165 zł/h netto B2B.</p><p>&nbsp;</p><p>Wraca z decyzją w poniedziałek.</p><p>Do sprawdzenia: referencje z poprzedniego projektu.</p>",
      job_id: 502,
      job_title: "Backend Engineer",
      external_source: "traffit",
      replies: [],
    },
  ],
  total: 9,
  // Liczniki zakładek liczy serwer dla całej historii.
  group_counts: { talks: 4, contact: 2, delivery: 2, email: 0, automat: 1 },
};

const DOCUMENTS = [
  {
    id: 11,
    filename: "CV_Marta_Kowalczyk.pdf",
    document_kind: "cv",
    is_primary: true,
    content_type: "application/pdf",
    size_bytes: 182_000,
    created_at: daysAgo(10),
  },
  {
    id: 13,
    filename: "Marta_Kowalczyk_B2B_Bank_Przykladowy.docx",
    document_kind: "cv",
    is_primary: false,
    content_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: 64_000,
    created_at: daysAgo(4),
  },
  {
    id: 12,
    filename: "Certyfikat_OCP_Java17.pdf",
    document_kind: "certificate",
    is_primary: false,
    content_type: "application/pdf",
    size_bytes: 90_000,
    created_at: daysAgo(10),
  },
];

const RISK = {
  candidate_id: CANDIDATE_ID,
  level: "medium",
  score: 12,
  breakdown: { early: 1, interview: 1, post_accept: 0 },
  last_updated_at: daysAgo(1),
  recent_events: [],
  profile_exists: true,
};

const AI_PROFILE = {
  screening_count: 2,
  verified_skills_aggregate: [
    { skill: "Kafka", level: "confirmed" },
    { skill: "Kubernetes", level: "confirmed" },
  ],
};

/**
 * Karta „Odpowiedzi z rozmów screeningowych”: dwie rozmowy — najnowsza
 * z pominiętą odpowiedzią, pytaniem usuniętym z profilu Championa i pozycjami
 * „sprawdzone w rozmowie”, starsza zwinięta.
 */
const SCREENING_ANSWERS: CandidateScreeningAnswers = {
  candidate_id: CANDIDATE_ID,
  conversations: [
    {
      stage_id: 7101,
      job_id: 501,
      job_title: "Java Developer",
      client_name: "Bank Przykładowy",
      answered_at: daysAgo(3),
      answered_by_name: "Ola Nowak",
      overall_fit: "fit",
      match_percent: 80,
      answers: [
        {
          question_id: "q1",
          question_text: "Czy pracowałaś na mikroserwisach? Na jakiej skali?",
          response: "Tak, 3 lata: 12 usług w systemie płatności, Kafka i Spring Boot. Sama projektowała dwie z nich.",
          deal_breaker_hit: false,
          skipped: false,
        },
        {
          question_id: "q2",
          question_text: "Od kiedy możesz zacząć?",
          response: "Miesięczny okres wypowiedzenia, realnie od listopada.",
          deal_breaker_hit: false,
          skipped: false,
        },
        {
          question_id: "q3",
          question_text: "Ile dni w tygodniu możesz być w biurze w Warszawie?",
          response: "",
          deal_breaker_hit: false,
          skipped: true,
        },
        {
          question_id: "q4",
          question_text: null,
          response: "Tylko B2B, faktura raz w miesiącu.",
          deal_breaker_hit: false,
          skipped: false,
        },
      ],
      experience_checks: [
        { kind: "domains", name: "Bankowość", status: "confirmed", note: "4 lata w systemach płatności" },
        { kind: "certifications", name: "AWS Solutions Architect", status: "not_confirmed", note: "" },
      ],
      notes: "Konkretna, podaje liczby. Angielski swobodny.",
      internal_note: null,
    },
    {
      stage_id: 7002,
      job_id: 502,
      job_title: "Backend Engineer",
      client_name: "Ubezpieczenia Demo",
      answered_at: daysAgo(47),
      answered_by_name: "Ola Nowak",
      overall_fit: "uncertain",
      match_percent: 50,
      answers: [
        {
          question_id: "q1",
          question_text: "Jakie masz doświadczenie z Kubernetesem?",
          response: "Wdraża przez gotowe pipeline'y, klastra sama nie stawiała.",
          deal_breaker_hit: false,
          skipped: false,
        },
        {
          question_id: "q2",
          question_text: "Jaka stawka?",
          response: "170–180 zł/h netto na B2B.",
          deal_breaker_hit: false,
          skipped: false,
        },
      ],
      experience_checks: [],
      notes: "",
      internal_note: null,
    },
  ],
};

const ACTIVITY_SUMMARY = {
  candidate_id: CANDIDATE_ID,
  summary:
    "Szuka projektu od października, preferuje hybrydę do 2 dni w biurze. Klient ocenił rozmowę techniczną wysoko.",
  model: "preview",
  generated_at: daysAgo(1),
  source_version: "v1",
  current_source_version: "v1",
  is_stale: false,
  visibility_scope_hash: "preview",
  source_manifest: { content_policy_version: "1", sources: [] },
};

const LANGUAGES = {
  candidate_id: CANDIDATE_ID,
  version: 1,
  languages: [
    {
      id: 1,
      language_code: "pl",
      language_name: "Polski",
      cefr_level: null,
      is_native: true,
      is_level_unknown: false,
      provenance: "manual",
      manual_lock: true,
      version: 1,
    },
    {
      id: 2,
      language_code: "en",
      language_name: "Angielski",
      cefr_level: "C1",
      is_native: false,
      is_level_unknown: false,
      provenance: "manual",
      manual_lock: true,
      version: 1,
    },
  ],
};

// Historia stawek (0414) — fikcyjne rekrutacje i klienci.
const RATE_OVERVIEW: RateOverview = {
  candidate_id: CANDIDATE_ID,
  enabled: true,
  window_start: daysAgo(548).slice(0, 10),
  rate_from: {
    amount: "120.00",
    at: daysAgo(400),
    source: "card",
    stale: false,
    key: "card:3",
    job_id: 202,
    job_title: "Tester manualny",
    client_name: "Bank Przykładowy",
  },
  latest_amount: "160.00",
  latest_at: daysAgo(20),
  count: 4,
  observations: [
    {
      key: "profile:11", amount_hourly: "160.00", raw: null, at: daysAgo(20),
      source: "profile_manual", job_id: null, job_title: null, client_name: null,
      author_name: "Anna Rekruterka", explicit_minimum: false, reason: "counts",
      excluded_by_name: null,
    },
    {
      key: "card:5", amount_hourly: "160.00", raw: "160 zł/h netto", at: daysAgo(60),
      source: "card", job_id: 201, job_title: "Senior QA Engineer",
      client_name: "Ubezpieczenia Testowe", author_name: "Anna Rekruterka",
      explicit_minimum: false, reason: "counts", excluded_by_name: null,
    },
    {
      key: "card:3", amount_hourly: "120.00", raw: "120 zł/h", at: daysAgo(400),
      source: "card", job_id: 202, job_title: "Tester manualny",
      client_name: "Bank Przykładowy", author_name: "Paweł Rekruter",
      explicit_minimum: false, reason: "minimum", excluded_by_name: null,
    },
    {
      key: "stage:9", amount_hourly: "95.00", raw: "95 PLN/h", at: daysAgo(900),
      source: "stage", job_id: 203, job_title: "Junior QA", client_name: "Bank Przykładowy",
      author_name: null, explicit_minimum: false, reason: "outside_window",
      excluded_by_name: null,
    },
  ],
  paid: [
    {
      kind: "contract", client_name: "Bank Przykładowy",
      start_date: daysAgo(800).slice(0, 10), end_date: daysAgo(450).slice(0, 10),
      amount_hourly: "110.00", redacted: false,
    },
  ],
};

const PROFILE_RATE = {
  candidate_id: CANDIDATE_ID,
  amount: "160.00",
  currency: "PLN",
  unit: "hour",
  tax_basis: "net",
  contract_type: "b2b",
  version: 1,
  updated_at: daysAgo(20),
};

const job = (id: number, title: string, score: number) => ({
  job: {
    id,
    title,
    client_id: null,
    location: "Warszawa",
    salary_min: null,
    salary_max: null,
    remote_policy: "hybrid",
    status: "published",
    priority: null,
    seniority: "Senior",
    industry: null,
    deadline: null,
  },
  total_score: score,
  breakdown: null,
});
const RECOMMENDATIONS = {
  matches: [job(601, "Senior Java Dev", 79), job(602, "Kafka Engineer", 76)],
  meta: null,
};

const CONTRACTS = { items: [] };

// Karty rekomendacji osoby: ustalenia z datą i źródłem, odpowiedzi z notatki
// (rekrutacja bez arkusza screeningu) i co z której notatki trafiło do karty.
const CARD_OVERVIEW: CandidateCardOverview = {
  candidate_id: CANDIDATE_ID,
  facts: [
    {
      key: "rate",
      label: "Stawka",
      raw: "160–170 zł/h netto",
      value: null,
      level: null,
      at: daysAgo(20),
      source: "note",
      author_name: "Kamil Wiśniewski",
      job_id: 502,
      job_title: "Backend Engineer",
    },
    {
      key: "availability",
      label: "Dostępność",
      raw: "1 miesiąc wypowiedzenia",
      value: null,
      level: null,
      at: daysAgo(20),
      source: "note",
      author_name: "Kamil Wiśniewski",
      job_id: 502,
      job_title: "Backend Engineer",
    },
    {
      key: "work_mode",
      label: "Tryb pracy",
      raw: "hybrydowo, do 2 dni w biurze w Warszawie",
      value: null,
      level: null,
      at: daysAgo(20),
      source: "note",
      author_name: "Kamil Wiśniewski",
      job_id: 502,
      job_title: "Backend Engineer",
    },
    {
      key: "nationality",
      label: "Narodowość",
      raw: "polska",
      value: null,
      level: null,
      at: daysAgo(5),
      source: "manual",
      author_name: "Ola Nowak",
      job_id: 501,
      job_title: "Java Developer",
    },
  ],
  conversations: [
    {
      job_id: 503,
      job_title: "Senior Java Developer",
      client_name: "Telekom Demo",
      answered_at: daysAgo(110),
      author_name: null,
      note_id: 74,
      from_traffit: true,
      question_count: 3,
      answers: [
        { number: 1, question: "Opisz ostatni projekt.", answer: "System bilingowy, Java 11 i Oracle." },
        { number: 2, question: "", answer: "Mikroserwisy od 2022 r., Kafka do zdarzeń." },
      ],
    },
  ],
  note_links: [
    {
      note_id: 72,
      job_id: 502,
      job_title: "Backend Engineer",
      fields: ["rate", "availability", "work_mode"],
      field_labels: ["Stawka", "Dostępność", "Tryb pracy"],
      answers: 0,
    },
  ],
};

// Screening rekrutacji z notatki 72 — okno tylko do odczytu w „Notatkach i historii”.
const NOTE_SCREENING = {
  candidate_id: CANDIDATE_ID,
  job_id: 502,
  version: 0,
  versions_count: 0,
  state_token: "podglad-502",
  editable: false,
  read_only_reason: "process_closed",
  read_only_message: "Proces tej osoby jest zakończony — formularz jest tylko do odczytu.",
  stage_id: null,
  board_column: "closed",
  process_state_version: 0,
  claim: null,
  champion_profile: {},
  sheet: null,
  sheet_source_stage_id: null,
  legacy_notes: null,
  note_answers: [],
  questions: [
    {
      number: 1,
      question: "Doświadczenie z mikroserwisami?",
      answer: "Pięć lat, ostatnio system rozliczeń.",
      source: "note",
      question_id: null,
      deal_breaker: null,
      deal_breaker_hit: false,
    },
  ],
  card: {
    fields: {
      availability: { raw: "1 miesiąc", source: "note", note_id: 72 },
      work_mode: { raw: "hybrydowo, 2 dni w tygodniu", source: "note", note_id: 72 },
    },
    previous: {},
    suggestions: {},
    completeness: {
      status: "partial",
      filled: 3,
      total: 10,
      missing: ["location", "english", "recommendation", "motivation", "red_flags"],
    },
    labels: {
      availability: "Dostępność",
      work_mode: "Tryb pracy",
      location: "Lokalizacja",
      english: "Angielski",
      recommendation: "Dlaczego ten kandydat",
      motivation: "Motywacja",
      red_flags: "Red flags",
    },
    editable_fields: ["availability", "work_mode", "location", "english", "recommendation", "motivation", "red_flags"],
  },
  rate: null,
  rate_text: "130–150 zł/h",
  rate_hints: { card: null, rate_from: null },
  rate_change_notifies: false,
  can_edit_rate: false,
  suggestions_from_notes: {},
  assist_enabled: false,
  phrase_language: "pl",
};
const NOTE_SCREENING_LEGACY =
  "Stawka: 130–150 zł/h\nDostępność: 1 miesiąc\nTryb pracy: hybrydowo, 2 dni w tygodniu\n\nP1: Doświadczenie z mikroserwisami?\nO: Pięć lat, ostatnio system rozliczeń.";

// Telefon po ciszy klienta (0372) — zaległy, „Teraz” w Przeglądzie.
const FOLLOWUP = {
  followup: {
    candidate_id: CANDIDATE_ID,
    state: "overdue",
    overdue_days: 2,
    due_on: daysAgo(2).slice(0, 10),
    caller_id: 1,
    caller_name: "Ola Nowak",
    caller_reason: "furthest",
    last_contact_at: daysAgo(16),
    last_contact_by: "Ola Nowak",
    last_contact_kind: "call",
    processes: [
      {
        job_id: 501,
        job_title: "Java Developer",
        client_name: "Bank Przykładowy",
        column: "cv_sent",
        silent_days: 16,
      },
    ],
  },
  history: [],
  meetings: [],
};

const SKILLS_DICTIONARY = [
  { id: 1, name: "Kafka", category: "messaging", aliases: ["Apache Kafka"] },
  { id: 2, name: "Spring Boot", category: "framework", aliases: ["springboot"] },
  { id: 3, name: "Java", category: "language", aliases: [] },
];

const GENERATED_CVS = [
  {
    id: 801,
    filename: "Marta_Kowalczyk_CV_PL.docx",
    status: "ready",
    candidate_id: CANDIDATE_ID,
    candidate_name: "Marta Kowalczyk",
    job_id: 501,
    job_title: "Java Developer",
    language: "pl",
    blind: false,
    mode: "polished",
    created_at: daysAgo(4),
    created_by_name: "Ola Nowak",
    can_download: true,
    can_delete: false,
  },
];

/** Skrzynka M365 niepodłączona — okno maila pokazuje drogę do Ustawień. */
const M365_CONNECTION = { connected: false };

/** Odpowiedzi lokalnego adaptera: [wzorzec ścieżki, dane]. */
const ROUTES: Array<[RegExp, (config: InternalAxiosRequestConfig) => unknown]> = [
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}$`), () => CANDIDATE],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/history$`), () => HISTORY],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/timeline`), () => TIMELINE],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/documents`), (config) =>
    String(config.url).includes("kind=cv")
      ? DOCUMENTS.filter((d) => d.document_kind === "cv")
      : DOCUMENTS],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/risk$`), () => RISK],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/ai-profile$`), () => AI_PROFILE],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/activity-summary$`), () => ACTIVITY_SUMMARY],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/screening-answers$`), () => SCREENING_ANSWERS],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/languages$`), () => LANGUAGES],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/profile-rate$`), () => PROFILE_RATE],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/recommendations$`), () => RECOMMENDATIONS],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/suggested-pools$`), () => []],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/rate-overview$`), () => RATE_OVERVIEW],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/conflicts$`), () => []],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/hiring-manager-vetoes$`), () => []],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/calls$`), () => []],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/pin$`), () => ({ pinned: false })],
  [/order-documents/, () => ({ documents: [] })],
  [new RegExp(`^/api/candidates/${CANDIDATE_ID}/recommendation-cards$`), () => CARD_OVERVIEW],
  // Okno „Screening tej rekrutacji” przy notatce (09.10.2026).
  [/^\/api\/screening-form$/, () => NOTE_SCREENING],
  [/^\/api\/recommendation-cards$/, () => ({ legacy_text: NOTE_SCREENING_LEGACY })],
  [/^\/api\/notes/, () => NOTES],
  [/^\/api\/contracts$/, () => CONTRACTS],
  [/^\/api\/presence\//, () => ({ viewers: [] })],
  [/^\/api\/users\/mentionable/, () => MENTIONABLE_USERS],
  [/^\/api\/clients-lookup/, () => []],
  [new RegExp(`^/api/candidate-followups/candidates/${CANDIDATE_ID}$`), () => FOLLOWUP],
  [/^\/api\/skills$/, () => ({ items: SKILLS_DICTIONARY, total: SKILLS_DICTIONARY.length })],
  [/^\/api\/cv-generator\/generated$/, () => GENERATED_CVS],
  [/^\/api\/microsoft365\/connection$/, () => M365_CONNECTION],
  [/^\/api\/interview-feedback$/, () => []],
];

/**
 * Lokalna odpowiedź dla żądania. Zwraca odpowiedź albo lokalny błąd 404.
 */
const NOTES_FACTS: CandidateNotesFacts = {
  candidate_id: CANDIDATE_ID,
  extracted_at: daysAgo(1),
  has_facts: true,
  rate: {
    value: "1400",
    currency: "PLN",
    period: "md",
    raw: "Oczekuje 1400 zł netto za dzień na B2B, do negocjacji.",
    as_of: "2026-09",
    hourly_pln: "175.00",
    flexibility: "Zejdzie do 1300 zł/MD przy dłuższym projekcie.",
    profile_amount: "160.00",
    profile_rate_version: 1,
    can_apply: true,
  },
  work_mode: {
    modes: ["remote", "hybrid"],
    max_onsite_days: 3,
    profile_modes: ["remote", "hybrid"],
    profile_max_onsite_days: 2,
    can_apply: true,
  },
  contract_form: { value: "b2b", profile_contract_types: [], can_apply: true },
  availability: {
    raw: "Okres wypowiedzenia 1 miesiąc.",
    notice_period_text: "1 miesiąc",
    available_from_text: null,
    notice_period: 1,
    notice_period_unit: "months",
    available_from: null,
    profile_notice_period: null,
    profile_notice_period_unit: null,
    profile_availability_date: "2026-10-01",
    can_apply: true,
  },
  office_cities: {
    cities: ["Warszawa"],
    profile_office_cities: ["Warszawa"],
    can_apply: false,
  },
  relocation: { willing: false, targets: [] },
  current_engagement: {
    employer: "Bank (przykład)",
    project: "system płatności",
    ends_at: "2026-12",
    raw: null,
  },
  not_looking_until: null,
  languages: [{ name: "angielski", level: "C1" }],
  sectors_prefer: ["fintech"],
  sectors_avoid: ["gambling"],
  client_vetoes: [],
  matching_facts:
    "Szuka projektu w Javie od stycznia; preferuje fintech, max 3 dni w biurze w Warszawie.",
};

function localResponse(config: InternalAxiosRequestConfig):
  | { ok: true; response: AxiosResponse }
  | { ok: false; error: AxiosError } {
  const path = String(config.url ?? "").split("?")[0];
  const route =
    (config.method ?? "get").toLowerCase() === "get"
      ? ROUTES.find(([pattern]) => pattern.test(path))
      : undefined;
  if (!route) {
    const error = new AxiosError("preview: brak danych", "ERR_BAD_REQUEST");
    error.response = {
      data: { detail: "Podgląd: brak danych dla tej sekcji" },
      status: 404,
      statusText: "Not Found",
      headers: new AxiosHeaders(),
      config,
    };
    return { ok: false, error };
  }
  return {
    ok: true,
    response: {
      data: route[1](config),
      status: 200,
      statusText: "OK",
      headers: new AxiosHeaders({ etag: '"preview-v1"' }),
      config,
    },
  };
}

const PREVIEW_MARK = "__candidateProfilePreview";

/**
 * Interceptor ŻĄDANIA (nie adapter): axios uruchamia interceptory żądań od
 * ostatnio dodanego, więc ten odrzuca wywołanie ZANIM ruszy interceptor
 * aplikacji — a ten przy pierwszym żądaniu sonduje `/api/health` zwykłym
 * `fetch`-em. Błąd nie niesie `config`, więc interceptory odpowiedzi aplikacji
 * go nie ponawiają; nasz interceptor odpowiedzi (dodany po nich) zamienia go
 * na odpowiedź z danych harnessu.
 */
function installLocalApi(): () => void {
  const requestId = api.interceptors.request.use((config) => {
    const result = localResponse(config);
    return Promise.reject(Object.assign(new Error("preview"), { [PREVIEW_MARK]: result }));
  });
  const responseId = api.interceptors.response.use(undefined, (error: unknown) => {
    const result = (error as Record<string, unknown> | null)?.[PREVIEW_MARK] as
      | ReturnType<typeof localResponse>
      | undefined;
    if (!result) return Promise.reject(error);
    return result.ok ? Promise.resolve(result.response) : Promise.reject(result.error);
  });
  return () => {
    api.interceptors.request.eject(requestId);
    api.interceptors.response.eject(responseId);
  };
}

function seededClient(employed: boolean): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        gcTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
      },
    },
  });
  const scope = candidateViewerScopeKey(PREVIEW_USER) ?? "unauthenticated";
  qc.setQueryData(
    candidateQueryKeys.detail(CANDIDATE_ID),
    employed
      ? {
          ...CANDIDATE,
          employment: {
            state: "employed_at_client",
            client_id: 31,
            client_name: "Bank Przykładowy",
            contract_id: 77,
            contract_end_date: null,
            source: "contract",
          },
        }
      : CANDIDATE,
  );
  qc.setQueryData(candidateQueryKeys.history(CANDIDATE_ID, scope), HISTORY);
  qc.setQueryData(candidateQueryKeys.timeline(CANDIDATE_ID, 50), TIMELINE);
  qc.setQueryData(candidateQueryKeys.notes(CANDIDATE_ID), NOTES);
  qc.setQueryData(candidateQueryKeys.documents(CANDIDATE_ID), DOCUMENTS);
  qc.setQueryData(
    candidateQueryKeys.cvDocuments(CANDIDATE_ID),
    DOCUMENTS.filter((d) => d.document_kind === "cv"),
  );
  qc.setQueryData(candidateQueryKeys.risk(CANDIDATE_ID), RISK);
  qc.setQueryData(candidateQueryKeys.aiProfile(CANDIDATE_ID), AI_PROFILE);
  qc.setQueryData(candidateQueryKeys.calls(CANDIDATE_ID), []);
  qc.setQueryData(candidateQueryKeys.contracts(CANDIDATE_ID), CONTRACTS);
  qc.setQueryData(candidateQueryKeys.activitySummary(CANDIDATE_ID, scope), ACTIVITY_SUMMARY);
  qc.setQueryData(candidateQueryKeys.screeningAnswers(CANDIDATE_ID, scope), SCREENING_ANSWERS);
  qc.setQueryData(candidateQueryKeys.cardOverview(CANDIDATE_ID, scope), CARD_OVERVIEW);
  qc.setQueryData(candidateQueryKeys.languages(CANDIDATE_ID), {
    data: LANGUAGES,
    etag: '"preview-v1"',
  });
  qc.setQueryData(candidateQueryKeys.notesFacts(CANDIDATE_ID), NOTES_FACTS);
  qc.setQueryData(candidateQueryKeys.rateOverview(CANDIDATE_ID), RATE_OVERVIEW);
  qc.setQueryData(candidateQueryKeys.profileRate(CANDIDATE_ID), {
    data: PROFILE_RATE,
    etag: '"preview-v1"',
  });
  qc.setQueryData(["candidate-followup", CANDIDATE_ID], FOLLOWUP);
  qc.setQueryData(["skills-dictionary", 500], SKILLS_DICTIONARY);
  qc.setQueryData(["candidate-generated-cvs", CANDIDATE_ID], GENERATED_CVS);
  qc.setQueryData(["m365-connection"], M365_CONNECTION);
  qc.setQueryData(["interview-feedback", "by-candidate", CANDIDATE_ID], []);
  qc.setQueryData(candidateQueryKeys.recommendations(CANDIDATE_ID, 10), RECOMMENDATIONS);
  qc.setQueryData(["suggested-pools", CANDIDATE_ID], []);
  qc.setQueryData(["candidate-pin-state", CANDIDATE_ID], { pinned: false });
  qc.setQueryData(["presence", "candidate", CANDIDATE_ID], []);
  qc.setQueryData(["competence-categories-active"], [
    { id: 2, slug: "software_development", name_pl: "Software Development" },
  ]);
  qc.setQueryData(["clients-lookup"], []);
  return qc;
}

export default function CandidateProfilePreviewPage() {
  return (
    <Suspense fallback={null}>
      <CandidateProfilePreview />
    </Suspense>
  );
}

function CandidateProfilePreview() {
  const employed = useSearchParams()?.get("employed") === "1";
  const [ready, setReady] = useState(false);
  const [qc] = useState(() => seededClient(employed));

  useEffect(() => {
    const uninstall = installLocalApi();
    useAuthStore.setState({ user: PREVIEW_USER as never, hydrated: true });
    setReady(true);
    return uninstall;
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <main className="min-h-dvh bg-background px-4 py-6 sm:px-6">
          <Suspense fallback={null}>
            <CandidateDetailV2 candidateId={CANDIDATE_ID} basePath={BASE_PATH} />
          </Suspense>
        </main>
      </QueryClientProvider>
    </ToastProvider>
  );
}
