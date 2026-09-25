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
 * Dane są fikcyjne — repo jest publiczne.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import {
  CANDIDATES_BASE_TOTAL_QUERY_KEY,
  CandidatesListV2,
  candidatesListApiParams,
  candidatesListQueryKey,
} from "@/components/v2/pages/CandidatesListV2";
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

const recruitment = (job_id: number, stage: string, movedDaysAgo: number) => ({
  job_id,
  job_title: `Rekrutacja #${job_id}`,
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
    phone: "+48 601 204 118",
    linkedin_current_title: "Senior Java Developer",
    linkedin_current_company: "Firma Alfa",
    skills: ["Java", "Spring", "Kafka", "Docker"],
    city: "Warszawa",
    availability_date: inDays(9),
    expected_rate_hourly: 160,
    competence_category_id: 2,
    competence_category: "software_development",
    last_contacted_at: daysAgo(1),
    cv_filename: "CV_przykladowe.pdf",
    active_recruitments: [recruitment(11, "verified", 6), recruitment(12, "cv_sent", 2)],
  },
  {
    id: 502,
    name: "Tomasz",
    lastname: "Testowy",
    status: "active",
    phone: "+48 512 880 431",
    linkedin_current_title: "Java Developer",
    linkedin_current_company: "Firma Beta",
    skills: ["Java", "Spring", "AWS"],
    city: "Kraków",
    availability_status: "actively_looking",
    expected_rate_hourly: 140,
    last_contacted_at: daysAgo(3),
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
    cv_filename: "CV_przykladowe.pdf",
    active_recruitments: [recruitment(13, "client_interview", 4)],
  },
  {
    id: 504,
    name: "Piotr",
    lastname: "Wzorcowy",
    status: "active",
    phone: "+48 790 115 602",
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
    phone: "+48 603 447 290",
    linkedin_current_title: "Senior Java Developer",
    skills: ["Java", "Spring", "Docker"],
    availability_status: "actively_looking",
    expected_rate_hourly: 150,
    last_contacted_at: daysAgo(30),
    cv_filename: "CV_przykladowe.pdf",
    employment: { state: "employed_at_client", client_name: "Klient Omega" },
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

const QUICK_VIEW = {
  candidate: {
    id: 501,
    name: "Marta",
    lastname: "Przykładowa",
    email: "marta.przykladowa@example.com",
    phone: "+48 600 000 000",
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
      job_title: "Java Developer",
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
    can_mark_employed: true,
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
const FAKE_SKILLS: Array<{ label: string; alias?: string; count: number }> = [
  { label: "Java", count: 4120 },
  { label: "JavaScript", alias: "js", count: 5310 },
  { label: "Java EE", alias: "jee", count: 880 },
  { label: "Kafka", count: 1640 },
  { label: "Kotlin", count: 930 },
  { label: "Kubernetes", alias: "k8s", count: 2480 },
  { label: "Spring", count: 3320 },
  { label: "Spring Boot", alias: "springboot", count: 2870 },
  { label: "Python", alias: "py", count: 3950 },
  { label: "PostgreSQL", alias: "postgres", count: 2210 },
  { label: "React", count: 2740 },
];

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
    }));
  if (t.length >= 3 && "java developer".startsWith(t.slice(0, 4))) {
    items.push({ label: "java developer", kind: "title", insert: "java developer", alias: null, category: null, count: 2150 });
  }
  return {
    items,
    wildcard: t.length >= 3 ? { label: `${q}*`, kind: "prefix" as const, insert: `${q}*`, count: 9100 } : null,
  };
}

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
  qc.setQueryData(["places-suggest", fromUrl.location.trim()], {
    items: [
      { name: "Warszawa", voivodeship: "mazowieckie", population: 1702139 },
      { name: "Kraków", voivodeship: "małopolskie", population: 816614 },
    ],
    voivodeships: ["dolnośląskie", "małopolskie", "mazowieckie", "pomorskie", "śląskie"],
    max_radius_km: 300,
  });
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

export default function CandidatesListPreview() {
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);
  const [dialogOpen, setDialogOpen] = useState(false);

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
          <CandidatesListV2 onRequestSearch={() => undefined} />
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
