"use client";

/**
 * Harness wizualny uproszczonego ekranu „Kandydaci" (22.09.2026) — bez API
 * i bez logowania (wzorzec `preview/jobs-list-v3`): produkcyjny
 * `CandidatesListV2` + ZASIANY cache react-query. Klucz listy liczy ta sama
 * funkcja co komponent (`candidatesListApiParams`), więc zasiew nie może się
 * z nim rozjechać.
 *
 * Bezpiecznik sieci: rozwijane filtry i okna mają własne zapytania. Na czas
 * życia harnessu interceptor odrzuca KAŻDE żądanie axiosa lokalnie — nic nie
 * wychodzi do sieci ani nie przerzuca na /login.
 *
 * `?dialog=1` otwiera od razu okno „Szukaj z requestu" (do zrzutów ekranu).
 * Podpowiedzi słów kluczowych odpowiadają z lokalnego słownika (bez sieci);
 * zmiana filtra pokazuje pasek „czeka na Szukaj”.
 * `?embed=1` pokazuje listę tak, jak widzi ją okno „Szukaj ręcznie"
 * rekrutacji (tryb osadzony, 25.09.2026) — w ramce szerokości okna;
 * `?embed=champion` — ta sama rekrutacja z wymaganiami do wyszukiwania
 * z sekcji 2 Championa (start od wierszy DL-a).
 * Spis miast (`/api/candidates/places/suggest`) też odpowiada lokalnie —
 * słowo-miasto w wierszu pokazuje podpowiedź „Ustaw lokalizację”.
 * Lista rekrutacji bloku „Rekrutacje” („Rekrutacje i historia”) odpowiada z lokalnej,
 * fikcyjnej listy: szukanie po nazwie, kliencie i numerze, status, „cały klient”.
 * Okno „Dodaj kandydata” też odpowiada lokalnie (12.10.2026), żeby dało się
 * przeklikać regułę „ta sama osoba = ten sam e-mail”:
 *  - e-mail `anna.przykladowa@example.com` → „Ten kandydat już jest w bazie”;
 *  - plik z „anna” w nazwie → odczyt odmawia po e-mailu, z „kopia” → po
 *    identycznym pliku, z „dlugi” → przekroczenie czasu odczytu;
 *  - każdy inny plik → odczyt wypełnia pola, zapis „zakłada” kandydata.
 * D5/D6 (19.10.2026): `?rate_max=55&locs=Warszawa:25|Łódź|Kraków:50` pokazuje
 * licznik „2 spełniają filtr · 23 bez danych”, kreskę nad osobami bez stawki
 * albo miasta, plakietki „brak …” i „Pruszków · 16 km (Warszawa)”; okienko
 * „Lokalizacja” ma wtedy trzy miasta z promieniami.
 * Dane są fikcyjne — repo jest publiczne.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import {
  CANDIDATES_BASE_TOTAL_QUERY_KEY,
  CandidatesListV2,
  candidatesListApiParams,
  candidatesListFiltersForQuery,
  candidatesListQueryKey,
} from "@/components/v2/pages/CandidatesListV2";
import { jobListFilters } from "@/components/v2/recruitment/ManualSearchPanel";
import { RequestSearchDialog } from "@/components/v2/candidates/RequestSearchDialog";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { candidateContactQueryKeys } from "@/lib/candidate-contact";
import { cloudTalkStatusQueryKey } from "@/hooks/useCloudTalkEnabled";
import { DEFAULT_FILTERS, decodeFilters } from "@/lib/url-filters";
import {
  KEYWORD_SUGGEST_ENDPOINT,
  foldKeyword,
  type KeywordSuggestion,
} from "@/lib/keyword-suggest";
import {
  RECRUITMENT_LOOKUP_ENDPOINT,
  type RecruitmentLookupItem,
  type RecruitmentLookupResponse,
} from "@/lib/recruitment-lookup";
import { useAuthStore } from "@/store/auth";

const daysAgo = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
};
const inDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

// Nazwy jak w nagłówku rekrutacji (16.10.2026): numer u klienta i tytuł dla
// rekrutera; `job_title` to nazwa od klienta.
const recruitment = (job_id: number, stage: string, movedDaysAgo: number) => ({
  job_id,
  job_title: `Rekrutacja #${job_id}`,
  job_working_title: `Java Developer · Spring, Kafka · ${job_id - 6}+ lat`,
  job_client_reference: `ZOB-29${job_id}`,
  client_name: "Klient Demo",
  stage,
  moved_at: daysAgo(movedDaysAgo),
  moved_by_name: "Rekruterka Demo",
});

const CANDIDATES = [
  {
    id: 501,
    name: "Marta",
    lastname: "Przykładowa",
    status: "active",
    phone: "+48 000 000 103",
    linkedin_current_title: "Senior Java Developer",
    linkedin_current_company: "Firma Alfa",
    skills: ["Java", "Spring", "Kafka", "Docker"],
    city: "Warszawa",
    availability_date: inDays(9),
    // 07.10.2026: data dostępności wpisana z notatki — lista pokazuje „stan na”.
    availability_from_notes: { as_of: daysAgo(400).slice(0, 10), basis: "notice" },
    expected_rate_hourly: 160,
    // „Stawka od” (0414): rok temu zgodziła się na 125 na inną rolę.
    rate_from_hourly: 125,
    rate_from_at: daysAgo(300),
    rate_latest_hourly: 160,
    rate_latest_at: daysAgo(12),
    rate_observation_count: 3,
    competence_category_id: 2,
    competence_category: "software_development",
    last_contacted_at: daysAgo(1),
    last_talk_at: daysAgo(1),
    last_talk_by: "Ola Nowak",
    last_talk_preview: "Szuka projektu z Javą 21 i Kafką, nie chce samego utrzymania.",
    contact_attempts: 1,
    cv_filename: "CV_przykladowe.pdf",
    active_recruitments: [recruitment(11, "verified", 6), recruitment(12, "cv_sent", 2)],
  },
  {
    id: 502,
    name: "Tomasz",
    lastname: "Testowy",
    status: "active",
    phone: "+48 000 000 104",
    linkedin_current_title: "Java Developer",
    linkedin_current_company: "Firma Beta",
    skills: ["Java", "Spring", "AWS"],
    city: "Kraków",
    availability_status: "actively_looking",
    expected_rate_hourly: 140,
    rate_from_hourly: 140,
    rate_latest_hourly: 140,
    rate_observation_count: 1,
    last_contacted_at: daysAgo(3),
    last_talk_at: null,
    contact_attempts: 3,
    cv_filename: "CV_przykladowe.pdf",
    active_recruitments: [],
  },
  {
    id: 503,
    name: "Anna",
    lastname: "Fikcyjna",
    status: "passive",
    phone: null,
    linkedin_current_title: "Backend Engineer",
    skills: ["Kotlin", "Spring", "SQL"],
    city: "Gdańsk",
    notice_period: 1,
    notice_period_unit: "months",
    expected_rate_hourly: 155,
    last_contacted_at: daysAgo(8),
    last_talk_at: daysAgo(8),
    last_talk_by: null,
    last_talk_preview: "Stawka 155 zł/h, miesiąc wypowiedzenia.",
    contact_attempts: 0,
    cv_filename: "CV_przykladowe.pdf",
    active_recruitments: [recruitment(13, "client_interview", 4)],
  },
  {
    id: 504,
    name: "Piotr",
    lastname: "Wzorcowy",
    status: "active",
    phone: "+48 000 000 105",
    linkedin_current_title: "Tech Lead",
    linkedin_current_company: "Firma Gamma",
    skills: ["Java", "Microservices"],
    city: "Katowice",
    availability_status: "open_to_offers",
    active_recruitments: [],
  },
  {
    id: 505,
    name: "Katarzyna",
    lastname: "Demonstracyjna",
    status: "active",
    phone: "+48 000 000 106",
    linkedin_current_title: "Senior Java Developer",
    skills: ["Java", "Spring", "Docker"],
    availability_status: "actively_looking",
    availability_date: "2026-08-01",
    expected_rate_hourly: 150,
    last_contacted_at: daysAgo(30),
    cv_filename: "CV_przykladowe.pdf",
    employment: { state: "employed_at_client", client_name: "Klient Omega" },
    // Znacznik „Pracuje u nas” pod nazwiskiem (12.10.2026).
    employment_marker: {
      phase: "working",
      source: "contract",
      clients: [
        {
          client_id: 9,
          client_name: "Klient Omega",
          contract_id: 90,
          phase: "working",
          order_end_date: "2026-12-31",
          delivery_lead_name: "Karol Wzorcowy",
        },
      ],
      // 15.10.2026: termin z umowy — lista mówi „od 01.01” zamiast daty
      // ze screeningu, a „Szuka aktywnie” znika.
      free_from: "2027-01-01",
      free_from_basis: "work_end",
    },
    active_recruitments: [],
  },
  {
    id: 506,
    name: "Michał",
    lastname: "Bezdanych",
    status: "active",
    active_recruitments: [],
  },
];

/**
 * D5/D6: lista przy „Stawka do 55 zł/h” + trzech miastach — dwie osoby
 * z danymi, potem osoby, które przeszły filtr na brak stawki albo miasta.
 */
const UNKNOWN_SPLIT_ITEMS = [
  {
    ...CANDIDATES[0],
    expected_rate_hourly: 50,
    rate_from_hourly: 50,
    rate_latest_hourly: 50,
    unknown_fields: [],
  },
  {
    ...CANDIDATES[1],
    city: "Pruszków",
    expected_rate_hourly: 45,
    rate_from_hourly: 45,
    rate_latest_hourly: 45,
    location_distance: { place: "Pruszków", km: 16, center: "Warszawa" },
    unknown_fields: [],
  },
  {
    ...CANDIDATES[2],
    city: "Łódź",
    expected_rate_hourly: null,
    unknown_fields: ["rate"],
  },
  { ...CANDIDATES[3], city: "Kraków", unknown_fields: ["rate"] },
  { ...CANDIDATES[5], unknown_fields: ["location", "rate"] },
];

const QUICK_VIEW = {
  candidate: {
    id: 501,
    name: "Marta",
    lastname: "Przykładowa",
    email: "marta.przykladowa@example.com",
    phone: "+48 000 000 107",
    city: "Warszawa",
    location: "Warszawa",
    status: "active",
    employment: { state: "unknown" },
    competence_category_id: 2,
    competence_category: "software_development",
    contact_case: null,
  },
  current_position: { title: "Senior Java Developer", started_at: null, precision: "unknown" },
  availability: {
    status: "open_to_offers",
    available_from: inDays(9),
    notice_period: null,
    notice_period_unit: null,
  },
  current_recruitments: [
    {
      job_id: 12,
      job_title: "Java Developer (ZOB-2912)",
      job_working_title: "Java Developer · Spring, Kafka · 5+ lat",
      job_client_reference: "ZOB-2912",
      client_name: "Klient Demo",
      stage_id: 1,
      stage_name: "CV wysłane",
      moved_at: daysAgo(2),
      moved_by_name: "Rekruterka Demo",
    },
    {
      job_id: 11,
      job_title: "Backend Engineer",
      client_name: "Klient Beta",
      stage_id: 2,
      stage_name: "Zweryfikowany",
      moved_at: daysAgo(6),
      moved_by_name: "Rekruterka Demo",
    },
  ],
  recent_notes: [
    {
      id: 1,
      content: "Szuka projektu od października, woli hybrydę 2 dni w biurze. Zna Kafkę produkcyjnie.",
      created_at: daysAgo(1),
      author_name: "Ola Demo",
    },
  ],
  cv_highlights: { years_experience: 8 },
  capabilities: {
    can_assign: true,
    can_view_documents: true,
    can_open_full_profile: true,
  },
};

/** Zakresy pogrubień wszystkich wystąpień słów (całe słowa) — tylko do danych harnessu. */
function bold(text: string, words: string[]): number[][] {
  const out: number[][] = [];
  for (const word of words) {
    const re = new RegExp(`(?<![\\p{L}\\p{N}_])${word}(?![\\p{L}\\p{N}_])`, "giu");
    for (const m of text.matchAll(re)) out.push([m.index ?? 0, (m.index ?? 0) + m[0].length]);
  }
  return out.sort((x, y) => x[0] - y[0]);
}

function snippet(field: string, text: string) {
  return { field, text, highlights: bold(text, ["java", "kafka"]) };
}

/** `?q_all=java|kafka` — wiersze z wycinkami po polach (jak w Traffit). */
const SNIPPETS: Record<number, Array<{ field: string; text: string; highlights: number[][] }>> = {
  501: [
    snippet("Treść CV", "…Backend: Java 17, Spring Boot, Kafka, PostgreSQL. Projekty bankowe…"),
    snippet("Stanowisko", "Senior Java Developer · Java Developer"),
    snippet("Umiejętności", "Java · Spring · Kafka · Docker"),
    snippet("Notatka", "Szuka projektu od października. Zna Kafkę produkcyjnie, Java od 8 lat."),
  ],
  502: [snippet("Treść CV", "…JavaScript, TypeScript i Java 11 w projektach e-commerce, Kafka Streams…")],
};

/** Fikcyjny słownik podpowiedzi (kształt `GET /api/candidates/keywords/suggest`). */
const FAKE_SKILLS: Array<{ label: string; alias?: string; count: number; variants?: string[] }> = [
  { label: "Java", count: 4120, variants: ["j2ee"] },
  { label: "JavaScript", alias: "js", count: 5310 },
  { label: "Java EE", alias: "jee", count: 880, variants: ["j2ee", "jee"] },
  { label: "Kafka", count: 1640 },
  { label: "Kotlin", count: 930 },
  { label: "Kubernetes", alias: "k8s", count: 2480, variants: ["k8s"] },
  { label: "Spring", count: 3320 },
  { label: "Spring Boot", alias: "springboot", count: 2870, variants: ["spring-boot", "springboot"] },
  { label: "Python", alias: "py", count: 3950 },
  { label: "PostgreSQL", alias: "postgres", count: 2210, variants: ["postgres", "psql"] },
  { label: "React", count: 2740 },
];

/** Fikcyjny spis miejscowości (kształt `GET /api/candidates/places/suggest`). */
const FAKE_PLACES = [
  { name: "Warszawa", voivodeship: "mazowieckie", population: 1702139 },
  { name: "Kraków", voivodeship: "małopolskie", population: 816614 },
  { name: "Gdańsk", voivodeship: "pomorskie", population: 486022 },
  // „Kotlin” to wieś — podpowiedź o mieście pojawia się dopiero od 20 tys.
  { name: "Kotlin", voivodeship: "wielkopolskie", population: 1300 },
];

function fakePlaces(q: string) {
  const t = foldKeyword(q);
  return {
    items: FAKE_PLACES.filter((p) => foldKeyword(p.name).startsWith(t)).slice(0, 5),
    voivodeships: ["dolnośląskie", "małopolskie", "mazowieckie", "pomorskie", "śląskie"],
    max_radius_km: 300,
  };
}

const FAKE_RECRUITMENTS: RecruitmentLookupItem[] = [
  { id: 2160, title: "UX Designer", client_id: 4, client_name: "Klient Omega", status: "open" },
  { id: 2150, title: "Data Engineer", client_id: 1, client_name: "Klient Demo", status: "open" },
  { id: 2143, title: "Java Developer", client_id: 1, client_name: "Klient Demo", status: "open" },
  { id: 2101, title: "QA Engineer", client_id: 2, client_name: "Klient Beta", status: "open" },
  { id: 2088, title: "DevOps Engineer", client_id: 2, client_name: "Klient Beta", status: "open" },
  { id: 1764, title: "Java Developer", client_id: 1, client_name: "Klient Demo", status: "closed" },
  {
    id: 1502,
    title: "Analityk biznesowy",
    client_id: 2,
    client_name: "Klient Beta",
    status: "closed",
  },
];

const numberList = (value: unknown): number[] =>
  (Array.isArray(value) ? value : value == null ? [] : [value]).map(Number);

/** Lokalna odpowiedź `GET /api/jobs-lookup/search` — te same dwa tryby co serwer. */
function fakeRecruitmentLookup(params: Record<string, unknown>): RecruitmentLookupResponse {
  const clients = [...new Set(FAKE_RECRUITMENTS.map((r) => r.client_id))].map((id) => {
    const jobs = FAKE_RECRUITMENTS.filter((r) => r.client_id === id);
    return { id: id ?? 0, name: jobs[0].client_name ?? "", jobs_count: jobs.length };
  });
  const ids = numberList(params.ids);
  const clientIds = numberList(params.client_ids);
  if (ids.length > 0 || clientIds.length > 0) {
    const items = FAKE_RECRUITMENTS.filter((r) => ids.includes(r.id));
    return {
      items,
      clients: clients.filter((c) => clientIds.includes(c.id)),
      total: items.length,
    };
  }
  const q = foldKeyword(String(params.q ?? ""));
  const status = String(params.status ?? "open");
  const items = FAKE_RECRUITMENTS.filter(
    (r) =>
      (status === "all" || r.status === status) &&
      (!q || foldKeyword(`${r.title} ${r.client_name} ${r.id}`).includes(q)),
  );
  return {
    items,
    clients: q.length >= 2 ? clients.filter((c) => foldKeyword(c.name).includes(q)) : [],
    total: items.length,
  };
}

function fakeKeywordSuggestions(q: string) {
  const t = foldKeyword(q);
  const items: KeywordSuggestion[] = FAKE_SKILLS.filter(
    (s) =>
      foldKeyword(s.label).startsWith(t) ||
      foldKeyword(s.label).split(" ").some((w) => w.startsWith(t)) ||
      (s.alias ?? "").startsWith(t),
  )
    .slice(0, 5)
    .map((s) => ({
      label: s.label,
      kind: "skill" as const,
      insert: s.label,
      alias: s.alias && !foldKeyword(s.label).startsWith(t) ? s.alias : null,
      category: "language",
      count: s.count,
      variants: s.variants ?? [],
    }));
  if (t.length >= 3 && "java developer".startsWith(t.slice(0, 4))) {
    items.push({ label: "java developer", kind: "title", insert: "java developer", alias: null, category: null, count: 2150 });
  }
  return {
    items,
    wildcard: t.length >= 3 ? { label: `${q}*`, kind: "prefix" as const, insert: `${q}*`, count: 9100 } : null,
  };
}

/** Rekrutacja, z której harness otwiera „Szukaj ręcznie" (`?embed=1`). */
const EMBED_JOB = {
  id: 42,
  title: "Klient Demo: Senior Java Developer (DEMO-101)",
  must_skills: ["Java", "Spring", "Kafka"],
  location: "Warszawa",
  remote_policy: "hybrid",
  competence_category_id: 2,
};
const EMBED_FILTERS = jobListFilters(EMBED_JOB, null);
/** Ta sama rekrutacja z wymaganiami do wyszukiwania ustawionymi przez DL-a. */
const EMBED_CHAMPION_FILTERS = jobListFilters(
  {
    ...EMBED_JOB,
    champion_profile: {
      search: {
        requirements: [["Java", "Kotlin"], ["Kafka", "RabbitMQ"], ["bankowość", "finanse"]],
        exclude: ["junior"],
      },
    },
  },
  null,
);

function searchParamsNow(): URLSearchParams {
  return new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
}

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
      },
    },
  });
  qc.setQueryData(
    candidatesListQueryKey(candidatesListApiParams(DEFAULT_FILTERS, 1, 50)),
    { items: CANDIDATES, total: 248, page: 1, page_size: 50 },
  );
  const fromUrl = decodeFilters(searchParamsNow());
  if (fromUrl.qAll.length || fromUrl.qAny.length) {
    qc.setQueryData(candidatesListQueryKey(candidatesListApiParams(fromUrl, 1, 50)), {
      items: CANDIDATES.map((c) => ({ ...c, match_snippets: SNIPPETS[c.id] ?? [] })),
      total: 14071,
      page: 1,
      page_size: 50,
    });
  }
  if (fromUrl.locationPlaces.length || fromUrl.rateMax !== null) {
    qc.setQueryData(candidatesListQueryKey(candidatesListApiParams(fromUrl, 1, 50)), {
      items: UNKNOWN_SPLIT_ITEMS,
      total: 25,
      page: 1,
      page_size: 50,
      known_match_count: 2,
    });
  }
  qc.setQueryData(["places-suggest", fromUrl.location.trim()], {
    items: [
      { name: "Warszawa", voivodeship: "mazowieckie", population: 1702139 },
      { name: "Kraków", voivodeship: "małopolskie", population: 816614 },
    ],
    voivodeships: ["dolnośląskie", "małopolskie", "mazowieckie", "pomorskie", "śląskie"],
    max_radius_km: 300,
  });
  qc.setQueryData(
    candidatesListQueryKey(
      candidatesListApiParams(
        candidatesListFiltersForQuery(EMBED_FILTERS, { jobId: EMBED_JOB.id }),
        1,
        50,
      ),
    ),
    { items: CANDIDATES, total: 143, page: 1, page_size: 50, text_mode_applied: "semantic" },
  );
  qc.setQueryData(
    candidatesListQueryKey(
      candidatesListApiParams(
        candidatesListFiltersForQuery(EMBED_CHAMPION_FILTERS, { jobId: EMBED_JOB.id }),
        1,
        50,
      ),
    ),
    {
      items: CANDIDATES.map((c) => ({ ...c, match_snippets: SNIPPETS[c.id] ?? [] })),
      total: 37,
      page: 1,
      page_size: 50,
      text_mode_applied: "literal",
    },
  );
  qc.setQueryData(CANDIDATES_BASE_TOTAL_QUERY_KEY, {
    items: [],
    total: 12481,
    page: 1,
    page_size: 1,
  });
  qc.setQueryData(["saved-searches", "candidates"], []);
  qc.setQueryData(["candidate-pins"], []);
  qc.setQueryData(["competence-categories-active"], [
    { id: 2, slug: "software_development", name_pl: "Wytwarzanie oprogramowania", is_active: true },
  ]);
  qc.setQueryData(candidateContactQueryKeys.status(), { enabled: false });
  qc.setQueryData(cloudTalkStatusQueryKey, { enabled: false });
  qc.setQueryData(candidateQueryKeys.quickView(501), QUICK_VIEW);
  qc.setQueryData(candidateQueryKeys.risk(501), { level: "low" });
  qc.setQueryData(["clients-lookup-talent-radar"], [
    { id: 1, name: "Klient Demo" },
    { id: 2, name: "Klient Beta" },
  ]);
  qc.setQueryData(["job-picker", "mine"], {
    items: [
      { id: 11, title: "Backend Engineer", client_name: "Klient Beta" },
      { id: 12, title: "Java Developer", client_name: "Klient Demo" },
    ],
  });
  qc.setQueryData(["clients-lookup"], []);
  qc.setQueryData(["users-directory"], []);
  return qc;
}

const EXISTING_CANDIDATE = {
  candidate_id: 9001,
  name: "Anna",
  lastname: "Przykładowa",
  email: "anna.przykladowa@example.com",
  match_score: 1,
  match_reasons: ["email_exact"],
};

/** Lokalna odpowiedź dla żądań okna „Dodaj kandydata”; `null` = nie to żądanie. */
function fakeAddCandidateAdapter(config: InternalAxiosRequestConfig): AxiosAdapter | null {
  if (config.method !== "post") return null;
  const url = String(config.url ?? "");
  const ok = (data: unknown, status = 200): AxiosAdapter => async () => ({
    data,
    status,
    statusText: "OK",
    headers: {},
    config,
  });
  const conflict = (match: typeof EXISTING_CANDIDATE): AxiosAdapter => async () => {
    throw new AxiosError("Conflict", "ERR_BAD_REQUEST", config, null, {
      data: {
        detail: {
          detail: "Kandydat wygląda na duplikat istniejącego rekordu.",
          existing_candidate_id: match.candidate_id,
          matches: [match],
        },
      },
      status: 409,
      statusText: "Conflict",
      headers: {},
      config,
    });
  };

  if (url === "/api/candidates/check-duplicates") {
    const email = String((config.data as { email?: string } | undefined)?.email ?? "");
    return ok(email.trim().toLowerCase() === EXISTING_CANDIDATE.email ? [EXISTING_CANDIDATE] : []);
  }
  if (url.startsWith("/api/candidates/cv/preview")) {
    const file = config.data instanceof FormData ? config.data.get("file") : null;
    const fileName = file instanceof File ? file.name.toLowerCase() : "";
    const forced = url.includes("force=true");
    // Bez lokalnej odpowiedzi żądanie odbija się od blokady sieci jak
    // przekroczenie czasu — dokładnie ten stan chcemy pokazać.
    if (fileName.includes("dlugi")) return null;
    if (!forced && fileName.includes("kopia")) {
      return conflict({ ...EXISTING_CANDIDATE, match_reasons: ["identical_file"] });
    }
    if (!forced && fileName.includes("anna")) return conflict(EXISTING_CANDIDATE);
    return ok({
      cv_sha256: "0".repeat(64),
      name: "Jan",
      lastname: "Fikcyjny",
      email: fileName.includes("anna") ? EXISTING_CANDIDATE.email : "jan.fikcyjny@example.com",
      phone: "+48 500 600 700",
      city: "Poznań",
      linkedin: null,
      current_position: "Tester",
      confidence: {},
      source: "preview",
    });
  }
  if (url.startsWith("/api/candidates/from-cv")) return ok({ candidate: { id: 9002 } }, 201);
  if (/^\/api\/candidates\/\d+\/documents$/.test(url)) return ok({}, 201);
  if (url === "/api/candidates") return ok({ id: 9002 }, 201);
  return null;
}

export default function CandidatesListPreview() {
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [embedMode, setEmbedMode] = useState<"off" | "job" | "champion">("off");

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) => {
      // Podpowiedzi słów kluczowych odpowiadają lokalnie ze słownika harnessu.
      if (config.url === KEYWORD_SUGGEST_ENDPOINT) {
        const q = String((config.params as { q?: string } | undefined)?.q ?? "");
        config.adapter = async () => ({
          data: fakeKeywordSuggestions(q),
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      // Spis miast — podpowiedź „Ustaw lokalizację” przy słowie-mieście.
      if (config.url === "/api/candidates/places/suggest") {
        const q = String((config.params as { q?: string } | undefined)?.q ?? "");
        config.adapter = async () => ({
          data: fakePlaces(q),
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      // Lista rekrutacji w bloku „Rekrutacje” filtra „Rekrutacje i historia”.
      if (config.url === RECRUITMENT_LOOKUP_ENDPOINT) {
        const params = (config.params as Record<string, unknown> | undefined) ?? {};
        config.adapter = async () => ({
          data: fakeRecruitmentLookup(params),
          status: 200,
          statusText: "OK",
          headers: {},
          config,
        });
        return config;
      }
      const addCandidate = fakeAddCandidateAdapter(config);
      if (addCandidate) {
        config.adapter = addCandidate;
        return config;
      }
      return Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config));
    });
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Rekruterka",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      hydrated: true,
    });
    setDialogOpen(new URLSearchParams(window.location.search).get("dialog") === "1");
    const embed = new URLSearchParams(window.location.search).get("embed");
    setEmbedMode(embed === "champion" ? "champion" : embed === "1" ? "job" : "off");
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <div className="min-h-dvh bg-background p-4 sm:p-6">
          {embedMode !== "off" ? (
            <div className="ml-auto max-w-[min(1100px,92vw)] rounded-xl border border-border bg-card p-5 shadow-lg">
              <h2 className="text-lg font-semibold">Szukaj ręcznie</h2>
              <p className="mb-4 text-sm text-muted-foreground">
                Filtry wypełnione z rekrutacji „{EMBED_JOB.title}”. Osoby, które już w niej są, nie
                pojawią się w wynikach.
              </p>
              <CandidatesListV2
                embed={{
                  jobId: EMBED_JOB.id,
                  jobTitle: EMBED_JOB.title,
                  initialFilters:
                    embedMode === "champion" ? EMBED_CHAMPION_FILTERS : EMBED_FILTERS,
                  keywordsNote:
                    embedMode === "champion"
                      ? "Wymagania ustawione przy tworzeniu rekrutacji. Zmiany tutaj nie zmieniają rekrutacji."
                      : undefined,
                }}
              />
            </div>
          ) : (
            <CandidatesListV2 onRequestSearch={() => undefined} />
          )}
          <RequestSearchDialog
            open={dialogOpen}
            onOpenChange={setDialogOpen}
            onSubmit={() => undefined}
          />
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}
