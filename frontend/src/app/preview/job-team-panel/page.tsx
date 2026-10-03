"use client";

/**
 * Harness `/preview/job-team-panel` — zakładka „Zespół” panelu zlecenia
 * (decyzja Artura 02.10.2026: Delivery Lead · Rekruter · Kategoria) na danych
 * fikcyjnych. Repo jest publiczne, więc żadnych prawdziwych osób ani klientów.
 *
 * Trzy rekrutacje obok siebie, każda w ramce szerokości doku (360 px):
 * (a) nikt nie pracuje, jest propozycja automatu, (b) rekruter i druga osoba,
 * (c) nikt i bez propozycji. `?as=dl|hor|recruiter` (domyślnie `dl`) zmienia
 * zalogowaną osobę: Delivery Lead przydziela i dokłada ludzi, Head of
 * Recruitment dodatkowo rozstrzyga propozycje automatu, rekruter bierze
 * rekrutację albo do niej dołącza.
 *
 * ZERO zapytań: każdy klucz, o który pyta zakładka, jest zasiany w cache
 * (`app/preview/__tests__/harness-seeds.test.ts`), a interceptor odcina sieć —
 * przyciski kończą się komunikatem o błędzie i nic nie trafia do API.
 */

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import {
  JobTeamTab,
  type JobTeamTabJob,
} from "@/components/v2/jobs/JobReadinessDock";
import { api } from "@/lib/api";
import {
  categoryRecruitersQueryKey,
  type CategoryRecruiter,
} from "@/lib/api/requestAllocation";
import { hiringManagerOptionsKey } from "@/lib/hiring-manager";
import type { JobRecruiter } from "@/lib/job-team";
import { priorityWorkQueryKeys } from "@/lib/priority-work-api";
import { useAuthStore } from "@/store/auth";

const CLIENT_ID = 1;
const CATEGORY_ID = 2;
const DAY_MS = 86_400_000;
// Zasiew ma zostać „świeży” przez cały czas oglądania — komponenty mają własne
// `staleTime`, po którym sięgnęłyby po sieć. Doba, nie lata: licznik
// przeterminowania w przeglądarce mieści najwyżej ~24 dni.
const SEED_FRESH = { updatedAt: Date.now() + DAY_MS };

const isoDay = (offsetDays: number) =>
  new Date(Date.now() + offsetDays * DAY_MS).toISOString().slice(0, 10);

const DELIVERY_LEAD = { id: 61, name: "Gosia Delivery" };
const HEAD_OF_RECRUITMENT = { id: 62, name: "Henryk Pokazowy" };

const anna = { user_id: 31, name: "Anna Przykładowa" };
const bartek = { user_id: 32, name: "Bartek Testowy" };
const celina = { user_id: 33, name: "Celina Wzorcowa" };
const darek = { user_id: 34, name: "Darek Makietowy" };

type Persona = "dl" | "hor" | "recruiter";

/**
 * `flags` to pola, które serwer liczy dla zalogowanej osoby w `GET /api/jobs/{id}`:
 * treść rekrutacji redaguje każda rola wewnętrzna (`can_edit`), ludzi
 * przydziela i priorytet ustawia Delivery Lead oraz Head of Recruitment.
 */
const PERSONAS: Record<
  Persona,
  {
    label: string;
    sees: string;
    user: { id: number; name: string; role: string };
    flags: Pick<JobTeamTabJob, "can_staff" | "can_edit" | "can_set_priority">;
  }
> = {
  dl: {
    label: "Delivery Lead",
    sees: "Przydziela rekrutera, zmienia go i dokłada kolejne osoby. Propozycji automatu nie rozstrzyga.",
    user: { ...DELIVERY_LEAD, role: "delivery_lead" },
    flags: { can_staff: true, can_edit: true, can_set_priority: true },
  },
  hor: {
    label: "Head of Recruitment",
    sees: "Akceptuje, zmienia i odrzuca propozycje automatu, przydziela ludzi. Sam rekrutacji nie bierze.",
    user: { ...HEAD_OF_RECRUITMENT, role: "head_of_recruitment" },
    flags: { can_staff: true, can_edit: true, can_set_priority: true },
  },
  recruiter: {
    label: "Rekruter",
    sees: "Bierze wolną rekrutację („Biorę”) albo dołącza do zajętej („Dołącz”).",
    user: { id: 35, name: "Ewa Fikcyjna", role: "recruiter" },
    flags: { can_staff: false, can_edit: true, can_set_priority: false },
  },
};

function personaFrom(value: string | null | undefined): Persona {
  return value === "hor" || value === "recruiter" ? value : "dl";
}

const BASE_JOB: JobTeamTabJob = {
  client_id: CLIENT_ID,
  client_name: "Bank Przykładowy S.A.",
  delivery_lead_id: DELIVERY_LEAD.id,
  status: "published",
  primary_owner: null,
  hiring_manager_contact_id: null,
  hiring_manager_name: null,
};

const CASES: {
  heading: string;
  note: string;
  job: JobTeamTabJob & { id: number; recruiters: JobRecruiter[] };
}[] = [
  {
    heading: "Propozycja automatu",
    note: "Nikt jeszcze nie pracuje — propozycja czeka na akceptację.",
    job: {
      ...BASE_JOB,
      id: 101,
      title: "Senior Java Developer",
      competence_category_id: CATEGORY_ID,
      deadline: isoDay(8),
      deadline_time: null,
      priority_level: "p1",
      recruiters: [
        { ...anna, via: "assignment", proposed: true, assigned_by_name: null },
      ],
    },
  },
  {
    heading: "Rekruter i druga osoba",
    note: "Obie osoby pracują nad rekrutacją i liczą się w obłożeniu.",
    job: {
      ...BASE_JOB,
      id: 102,
      title: "Tester automatyzujący",
      competence_category_id: CATEGORY_ID,
      deadline: isoDay(21),
      deadline_time: "12:00:00",
      priority_level: "p2",
      primary_owner: {
        id: bartek.user_id,
        name: bartek.name,
        email: "bartek@example.com",
        role: "recruiter",
        is_active: true,
      },
      recruiters: [
        { ...bartek, via: "owner", proposed: false, assigned_by_name: DELIVERY_LEAD.name },
        { ...celina, via: "collaborator", proposed: false, assigned_by_name: null },
      ],
    },
  },
  {
    heading: "Bez rekrutera",
    note: "Nikogo przy rekrutacji i brak propozycji automatu; nie ma też kategorii ani terminu.",
    job: {
      ...BASE_JOB,
      id: 103,
      title: "Analityk biznesowy",
      competence_category_id: null,
      deadline: null,
      deadline_time: null,
      priority_level: "accepting",
      recruiters: [],
    },
  },
];

const DIRECTORY = [
  { id: anna.user_id, name: anna.name, email: "anna@example.com", role: "recruiter", roles: ["recruiter"] },
  { id: bartek.user_id, name: bartek.name, email: "bartek@example.com", role: "recruiter", roles: ["recruiter"] },
  { id: celina.user_id, name: celina.name, email: "celina@example.com", role: "recruiter", roles: ["recruiter"] },
  { id: darek.user_id, name: darek.name, email: "darek@example.com", role: "recruiter", roles: ["recruiter"] },
  { id: 35, name: "Ewa Fikcyjna", email: "ewa@example.com", role: "recruiter", roles: ["recruiter"] },
  { id: DELIVERY_LEAD.id, name: DELIVERY_LEAD.name, email: "gosia@example.com", role: "delivery_lead", roles: ["delivery_lead"] },
  { id: HEAD_OF_RECRUITMENT.id, name: HEAD_OF_RECRUITMENT.name, email: "henryk@example.com", role: "head_of_recruitment", roles: ["head_of_recruitment"] },
];

const CATEGORY_PEOPLE: CategoryRecruiter[] = [
  { user_id: anna.user_id, name: anna.name, email: "anna@example.com", role: "recruiter", is_primary: true, priority: 1 },
  { user_id: bartek.user_id, name: bartek.name, email: "bartek@example.com", role: "recruiter", is_primary: true, priority: 1 },
  { user_id: celina.user_id, name: celina.name, email: "celina@example.com", role: "recruiter", is_primary: false, priority: 2 },
  { user_id: darek.user_id, name: darek.name, email: "darek@example.com", role: "recruiter", is_primary: false, priority: 2 },
];

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false },
    },
  });
  // Listy „+ Dodaj osobę”, „Zmień” przy propozycji i pole „Kolejne osoby”.
  qc.setQueryData(["users-directory"], DIRECTORY, SEED_FRESH);
  // Wiersz „Delivery Lead”: lista do wyboru i główny DL klienta.
  qc.setQueryData(
    ["users-directory", "delivery-lead-roles"],
    [DELIVERY_LEAD, HEAD_OF_RECRUITMENT],
    SEED_FRESH,
  );
  qc.setQueryData(
    ["client-team", CLIENT_ID],
    {
      tacs: [],
      delivery_leads: [
        {
          id: 1,
          user_id: DELIVERY_LEAD.id,
          name: DELIVERY_LEAD.name,
          email: "gosia@example.com",
          role: "delivery_lead",
          created_at: "2026-09-01T08:00:00Z",
          is_head: true,
        },
      ],
    },
    SEED_FRESH,
  );
  // Wiersz „Kategoria”: nazwa z katalogu i osoby z kategorii (po rozwinięciu).
  qc.setQueryData(
    ["competence-categories-active"],
    [
      {
        id: CATEGORY_ID,
        slug: "software_development",
        name_pl: "Development",
        name_en: "Development",
        description: "",
        keywords: [],
        display_order: 2,
      },
    ],
    SEED_FRESH,
  );
  qc.setQueryData(categoryRecruitersQueryKey(CATEGORY_ID), CATEGORY_PEOPLE, SEED_FRESH);
  // Okno „Przypisz rekrutera” / „Zmień rekrutera” (`RecruiterPickerField`).
  qc.setQueryData(
    ["users", "directory", "admin,delivery_lead,recruiter"],
    DIRECTORY.filter((user) => user.role !== "head_of_recruitment"),
    SEED_FRESH,
  );
  // Hiring manager klienta pod kartą zespołu.
  qc.setQueryData(
    hiringManagerOptionsKey(CLIENT_ID),
    [{ id: 501, name: "Tomasz Przykładowy", position: "Dyrektor IT" }],
    SEED_FRESH,
  );
  for (const { job } of CASES) {
    // Kontekst Priority Work na dole zakładki — wyłączony, jak dziś na produkcji.
    qc.setQueryData(
      priorityWorkQueryKeys.job(job.id),
      { mode: "off", plan: null, assignments: [], carry_over_count: 0, blockers: [] },
      SEED_FRESH,
    );
    qc.setQueryData(["job-allocation", job.id], null, SEED_FRESH);
  }
  return qc;
}

function Harness() {
  const params = useSearchParams();
  const persona = personaFrom(params?.get("as"));
  const { label, sees, user, flags } = PERSONAS[persona];
  const [client] = useState(seededClient);
  const [readyFor, setReadyFor] = useState<Persona | null>(null);

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    return () => api.interceptors.request.eject(blocker);
  }, []);

  useEffect(() => {
    const current = PERSONAS[persona].user;
    useAuthStore.setState({
      user: {
        id: current.id,
        email: "preview@example.com",
        name: current.name,
        role: current.role,
        roles: [current.role],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      realUser: null,
      hydrated: true,
    });
    setReadyFor(persona);
  }, [persona]);

  if (readyFor !== persona) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="min-h-dvh bg-background p-4 text-foreground md:p-6">
          <header className="space-y-1">
            <h1 className="text-lg font-semibold">Podgląd: zakładka „Zespół” rekrutacji</h1>
            <nav aria-label="Zalogowana osoba" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="text-muted-foreground">Patrzy:</span>
              {(Object.keys(PERSONAS) as Persona[]).map((key) => (
                <Link
                  key={key}
                  href={`/preview/job-team-panel?as=${key}`}
                  aria-current={key === persona ? "page" : undefined}
                  className={
                    key === persona
                      ? "font-semibold text-primary"
                      : "text-foreground hover:underline"
                  }
                >
                  {PERSONAS[key].label}
                </Link>
              ))}
            </nav>
            <p className="text-sm text-muted-foreground">
              {label} ({user.name}): {sees} Przyciski niczego nie zapisują.
            </p>
          </header>

          {/* `key`: zmiana osoby montuje panele od nowa (otwarte listy, wybór priorytetu). */}
          <div key={persona} className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
            {CASES.map(({ heading, note, job }) => (
              <section key={job.id} aria-label={heading} className="min-w-0 space-y-2">
                <div>
                  <h2 className="text-sm font-semibold">{heading}</h2>
                  <p className="text-xs text-muted-foreground">{note}</p>
                </div>
                {/* Ramka jak dok na widoku „Zlecenie i Champion”: kolumna 360 px, treść `px-4 py-3`. */}
                <div className="w-full max-w-[360px] rounded-xl border border-border bg-card">
                  <div className="truncate border-b border-border px-4 py-2 text-[11px] text-muted-foreground">
                    {job.title} · zakładka „Zespół”
                  </div>
                  <div className="px-4 py-3">
                    <JobTeamTab jobId={job.id} job={{ ...job, ...flags }} />
                  </div>
                </div>
              </section>
            ))}
          </div>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function JobTeamPanelPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
