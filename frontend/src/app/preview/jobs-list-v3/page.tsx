"use client";

/**
 * Harness wizualny listy rekrutacji v3 — bez API i bez logowania (wzorzec
 * `preview/contracts-consolidation`): produkcyjny `JobsListV2` + ZASIANY cache
 * react-query, żeby żaden `queryFn` nie wystartował przy ładowaniu (niezasiany
 * klucz → 401 → przerzut na /login).
 *
 * Klucze listy i liczników pochodzą z TYCH SAMYCH funkcji co w komponencie
 * (`jobsListQueryKey`, `jobsQuickCountsQueryKey`) — zasiew nie może się z nim
 * rozjechać. Zasiane są trzy zakresy: domyślne „Moje" (sort „Wymaga uwagi"),
 * „Otwarte" i „Wszystkie" (sort „Od najnowszej"), więc przełącznik zakresu
 * działa.
 *
 * Bezpiecznik sieci: dok „Podgląd" i rozwijane filtry mają własne zapytania,
 * których tu nie zasiewamy. Na czas życia harnessu interceptor odrzuca KAŻDE
 * żądanie axiosa lokalnie (bez wyjścia do sieci, bez ponowień) — dok pokazuje
 * wtedy swój stan błędu zamiast strzelić w API i przerzucić na /login.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError } from "axios";

import api from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import {
  JobsListV2,
  jobsListQueryKey,
  jobsQuickCountsQueryKey,
  type JobsListQueryState,
} from "@/components/v2/pages/JobsListV2";
import { useAuthStore } from "@/store/auth";

const column = (
  stage: string,
  name: string,
  count: number,
  order: number,
  extra: Record<string, unknown> = {},
) => ({ stage, name, count, order, category: "internal", ...extra });

const pipeline = (counts: number[]) => [
  column("new", "Nowy", counts[0], 0),
  column("prep_call", "Prep call", counts[1], 1),
  column("screening", "Screening", counts[2], 2),
  column("verified", "Zweryfikowany", counts[4], 3),
  column("interview", "QC CV", counts[3], 4),
  column("cv_sent", "CV Wysłane", counts[5], 5, { category: "external" }),
  column("client_interview", "Rozmowa z klientem", counts[6], 6, {
    category: "external",
  }),
  column("acceptance", "Akceptacja", counts[7], 7),
  column("hired", "Zatrudniony", counts[8], 8, {
    category: "terminal",
    terminal_type: "hired",
  }),
  column("rejected", "Odrzucony", counts[9], 9, {
    category: "terminal",
    terminal_type: "rejected",
  }),
];

const inDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const MINE = [
  {
    id: 901,
    request_status: "champion",
    similar: {
      linked_count: 1,
      linked_first: { id: 7712, title: "Java Developer (Spring)", reference_number: "REF-2026-0712" },
      reassigned_count: 3,
      suggested: null,
    },
    title: "Programista Java — płatności (ZOB 48213)",
    working_title: "Senior Java Developer · Java, Kafka · 5+ lat · Płatności",
    client_reference: "ZOB 48213",
    reference_number: "REF-2026-0901",
    location: "Warszawa",
    seniority: "Senior",
    client_name: "Bank Przykładowy",
    status: "published",
    tac_id: 3,
    primary_owner: { name: "Marta Kowalska" },
    deadline: inDays(5),
    created_at: inDays(-12),
    headcount: 2,
    candidate_count: 17,
    needs_action_count: 7,
    review_count: 431,
    open_proposals_count: 3,
    stage_columns: pipeline([4, 1, 3, 2, 2, 3, 1, 1, 0, 6]),
  },
  {
    id: 902,
    request_status: "searching",
    similar: {
      linked_count: 0,
      linked_first: null,
      reassigned_count: 0,
      suggested: { count: 2, sent_count: 5, first: { id: 7690, title: "Platform Engineer", reference_number: "REF-2026-0690" } },
    },
    title: "DevOps Engineer (Azure)",
    working_title: "DevOps Engineer · Azure, Terraform · 4+ lata",
    client_reference: "SAP 4500123456",
    reference_number: "REF-2026-0902",
    location: "Zdalnie",
    seniority: "Mid",
    client_name: "Ubezpieczenia Demo",
    status: "published",
    tac_id: null,
    needs_sourcing: true,
    primary_owner: { name: "Marta Kowalska" },
    deadline: inDays(-2),
    created_at: inDays(-30),
    headcount: 1,
    candidate_count: 6,
    needs_action_count: 2,
    open_proposals_count: 1,
    stage_columns: pipeline([2, 0, 1, 0, 1, 2, 0, 0, 0, 3]),
    priority_assignment: { id: 1, rank: "A", channel: "database" },
  },
  {
    id: 903,
    request_status: "contract",
    similar: { linked_count: 0, linked_first: null, reassigned_count: 0, suggested: null },
    title: "Analityk biznesowy",
    reference_number: "REF-2026-0903",
    location: "Kraków",
    client_name: "Telekom Demo",
    status: "published",
    tac_id: 3,
    primary_owner: null,
    deadline: null,
    created_at: inDays(-3),
    headcount: 1,
    candidate_count: 4,
    needs_action_count: 0,
    open_proposals_count: 0,
    stage_columns: pipeline([0, 0, 0, 0, 0, 3, 1, 0, 1, 0]),
  },
];

const OPEN = [
  ...MINE,
  {
    id: 904,
    request_status: "incomplete",
    similar: { linked_count: 0, linked_first: null, reassigned_count: 0, suggested: null },
    title: "Tester automatyzujący",
    reference_number: "REF-2026-0904",
    location: "Gdańsk",
    client_name: "Urząd Demo",
    status: "draft",
    tac_id: 5,
    primary_owner: { name: "Jan Nowak" },
    deadline: inDays(21),
    created_at: inDays(-1),
    headcount: 3,
    candidate_count: 0,
    needs_action_count: 0,
    open_proposals_count: 12,
    stage_columns: pipeline([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
  },
  {
    id: 905,
    request_status: "searching",
    similar: { linked_count: 0, linked_first: null, reassigned_count: 0, suggested: null },
    title: "Architekt rozwiązań (cudza, bez dostępu)",
    reference_number: "REF-2026-0905",
    client_name: "Bank Przykładowy",
    status: "published",
    tac_id: 5,
    can_open: false,
    primary_owner: { name: "Jan Nowak" },
    deadline: inDays(40),
    created_at: inDays(-60),
    headcount: 1,
    candidate_count: 9,
    needs_action_count: 4,
    open_proposals_count: 2,
    stage_columns: pipeline([1, 0, 2, 1, 1, 2, 1, 1, 0, 2]),
  },
];

const ALL = [
  ...OPEN,
  {
    id: 906,
    request_status: "closed",
    similar: { linked_count: 0, linked_first: null, reassigned_count: 0, suggested: null },
    title: "Frontend Developer React (zamknięta, z Traffita)",
    reference_number: "REF-2025-0142",
    client_name: "Bank Przykładowy",
    status: "closed",
    tac_id: 5,
    primary_owner: { name: "Jan Nowak" },
    deadline: inDays(-200),
    created_at: inDays(-400),
    headcount: 1,
    candidate_count: 11,
    needs_action_count: 0,
    open_proposals_count: 0,
    stage_columns: pipeline([0, 0, 0, 0, 0, 0, 0, 0, 1, 10]),
  },
];

const BASE: Omit<JobsListQueryState, "mine" | "openOnly" | "sort"> = {
  search: "",
  status: [],
  responsibleIds: [],
  clientIds: [],
  ccIds: [],
  needsSourcing: false,
  activeInSearch: false,
  deadline: "any",
  noOwnerOnly: false,
  priorityWork: "any",
  page: 1,
};

const page = (items: unknown[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 20,
});

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
    jobsListQueryKey({ ...BASE, mine: true, openOnly: false, sort: "attention" }),
    page(MINE),
  );
  qc.setQueryData(
    jobsListQueryKey({ ...BASE, mine: false, openOnly: true, sort: "newest" }),
    page(OPEN),
  );
  qc.setQueryData(
    jobsListQueryKey({ ...BASE, mine: false, openOnly: false, sort: "newest" }),
    page(ALL),
  );
  qc.setQueryData(jobsQuickCountsQueryKey(), {
    all: 4286,
    mine: MINE.length,
    open: 318,
    needs_sourcing: 41,
    active_in_search: 27,
    owner_missing: 63,
    deadline_7d: 9,
    request_status: {
      searching: 210,
      champion: 14,
      contract: 9,
      filled: 5,
      incomplete: 80,
      closed: 3968,
    },
    request_status_mine: {
      searching: 1,
      champion: 1,
      contract: 1,
      filled: 0,
      incomplete: 0,
      closed: 0,
    },
  });
  // Rozwijane filtry kolumny (klucze z samych literałów — pilnuje ich
  // `harness-seeds.test.ts`).
  qc.setQueryData(["clients-lookup"], []);
  qc.setQueryData(["users-directory"], []);
  qc.setQueryData(["competence-categories-active"], []);
  return qc;
}

export default function JobsListV3Preview() {
  const [ready, setReady] = useState(false);
  const [qc] = useState(seededClient);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(
        // `ECONNABORTED` = klasa „timeout po stronie przeglądarki", której
        // interceptor odpowiedzi nigdy nie ponawia.
        new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config),
      ),
    );
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Rekruter",
        // Wielorolowe: `admin` daje „Nowa rekrutacja", `recruiter` — domyślny
        // zakres „Moje" (`defaultScopeForUser`).
        role: "admin",
        roles: ["admin", "recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      } as never,
      hydrated: true,
    });
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <ToastProvider>
      <QueryClientProvider client={qc}>
        <div className="min-h-dvh bg-background p-6">
          <JobsListV2 />
        </div>
      </QueryClientProvider>
    </ToastProvider>
  );
}
