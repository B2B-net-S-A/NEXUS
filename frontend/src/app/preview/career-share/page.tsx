"use client";

/**
 * Harness okna „Udostępnij rekrutację" (Kariera Dynaminds).
 *
 * Renderuje PRODUKCYJNE zakładki okna na zasianym cache react-query — zero
 * zapytań przy ładowaniu, więc strona może stać w `PUBLIC_PATHS`. Klucze
 * zasiewu pochodzą z EKSPORTOWANYCH funkcji `lib/api/careerLinks.ts` (tych
 * samych, których używają hooki), więc zmiana klucza w hooku nie rozjedzie
 * się z harnessem. `updatedAt` daleko w przyszłości: hooki mają własne
 * `staleTime`, które nadpisuje domyślne `Infinity`.
 *
 * Kliknięcia wysyłające dane (szkic AI, zapis, zatwierdzenie, utworzenie
 * linku, sprawdzenie adresu) idą do prawdziwego API — bez sesji skończą się
 * błędem. To oczekiwane; harness pokazuje wygląd i stany.
 */

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { GeneralLinkTab } from "@/components/v2/career-share/GeneralLinkTab";
import { JobShareTab } from "@/components/v2/career-share/JobShareTab";
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2";
import {
  type CareerLinkState,
  type InviteLink,
  type JobPublicProfile,
  type PublishedJobLite,
  careerLinkQueryKey,
  inviteLinksQueryKey,
  jobPublicProfileQueryKey,
  shareableJobQueryKey,
  shareablePublishedJobsQueryKey,
} from "@/lib/api/careerLinks";

const JOBS: PublishedJobLite[] = [
  // Surowy tytuł z nazwą klienta i kodem — na stronie ma wyjść tytuł domyślny.
  { id: 101, title: "Nordea: Senior Java Developer (ZOB-3003)", status: "published" },
  { id: 102, title: "DevOps Engineer (Azure)", status: "published" },
  { id: 103, title: "Analityk biznesowy", status: "published" },
];

const PROFILE_WITH_FINDING: JobPublicProfile = {
  job_id: 101,
  status: "draft",
  public_title: null,
  default_title: "Senior Java Developer",
  effective_title: "Senior Java Developer",
  subtitle: "rozwój platformy płatności w dużym projekcie z sektora bankowego",
  about:
    "Dołączysz do zespołu, który przebudowuje platformę obsługującą płatności kartowe i przelewy natychmiastowe. System przechodzi z monolitu na architekturę mikroserwisów opartą o zdarzenia. Budżet do 180 zł/h.\n\nZespół liczy 8 osób, dwutygodniowe sprinty.",
  sections: { must: true, nice: true, params: true, process: true },
  show_on_recruiter_page: true,
  approved_at: null,
  approved_by_name: null,
  findings: [
    {
      code: "money",
      message: "Wykryto kwotę: „Budżet do 180 zł/h” — stawek nie publikujemy.",
      excerpt: "Budżet do 180 zł/h",
    },
  ],
  preview: {
    slug: "senior-java-developer-7kq2",
    title: "Senior Java Developer",
    subtitle: null,
    about: null,
    must: [],
    nice: [],
    params: {
      city: "Warszawa",
      remote_policy: "hybrid",
      onsite_days_per_week: 2,
      seniority: "senior",
      contract: "B2B",
      start: "10.2026",
      duration: "12+ mies.",
    },
    show: { must: true, nice: true, params: true, process: true },
  },
};

const INVITE_LINKS: InviteLink[] = [
  {
    token: "tok-1",
    url: "https://kariera.dynaminds.pl/r/devops-engineer-azure-p3x9",
    public_url: "https://kariera.dynaminds.pl/r/devops-engineer-azure-p3x9",
    kind: "job",
    slug: "devops-engineer-azure-p3x9",
    job: { id: 102, title: "DevOps Engineer (Azure)" },
    label: "Post LinkedIn 14.09",
    expires_at: null,
    revoked: false,
    use_count: 4,
    visit_count: 57,
    last_used_at: "2026-09-19T08:12:00Z",
    created_at: "2026-09-14T09:00:00Z",
    status: "used",
  },
  {
    token: "tok-2",
    url: "https://nexus.dynaminds.pl/apply/abc123",
    public_url: "https://nexus.dynaminds.pl/apply/abc123",
    kind: "job",
    slug: null,
    job: { id: 90, title: "Tester automatyzujący" },
    label: null,
    expires_at: "2026-08-30T00:00:00Z",
    revoked: false,
    use_count: 2,
    last_used_at: null,
    created_at: "2026-07-31T09:00:00Z",
    status: "expired",
  },
];

const CAREER_LINK: CareerLinkState = {
  link: {
    slug: "marta-n",
    public_url: "https://kariera.dynaminds.pl/marta-n",
    created_at: "2026-09-01T10:00:00Z",
    visit_count: 112,
  },
  stats: { days: 30, applications: 9, new_candidates: 6 },
  suggested_slug: "marta-n",
  base_url: "https://kariera.dynaminds.pl",
  recruiter_base_url: "https://kariera.dynaminds.pl/",
  jobs: [
    { job_id: 101, title: "Senior Java Developer", profile_status: "draft", show_on_recruiter_page: true, has_link: false },
    { job_id: 102, title: "DevOps Engineer (Azure)", profile_status: "approved", show_on_recruiter_page: true, has_link: true },
    { job_id: 103, title: "Analityk biznesowy", profile_status: "none", show_on_recruiter_page: false, has_link: true },
  ],
};

function Case({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section data-testid={id} className="rounded-xl border border-dashed border-border p-4">
      <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {/* Ramka imituje okno — zakładki renderują DialogBody/DialogFooter. */}
      <div className="flex max-h-[900px] flex-col overflow-hidden rounded-xl border border-border bg-card">
        {children}
      </div>
    </section>
  );
}

export default function CareerSharePreviewPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          retryOnMount: false,
          staleTime: Infinity,
          refetchOnWindowFocus: false,
          refetchOnReconnect: false,
        },
      },
    });
    const future = { updatedAt: Date.now() + 1_000 * 60 * 60 * 24 * 365 };
    qc.setQueryData(shareablePublishedJobsQueryKey(), JOBS, future);
    qc.setQueryData(shareableJobQueryKey(101), JOBS[0], future);
    qc.setQueryData(inviteLinksQueryKey(), INVITE_LINKS, future);
    qc.setQueryData(jobPublicProfileQueryKey(101), PROFILE_WITH_FINDING, future);
    qc.setQueryData(careerLinkQueryKey(), CAREER_LINK, future);
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto flex max-w-6xl flex-col gap-8 p-6">
          <header className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-lg font-semibold text-foreground">Udostępnij rekrutację — stany</h1>
              <p className="text-xs text-muted-foreground">
                Harness. Zero wywołań API przy ładowaniu; akcje wysyłające dane idą do API.
              </p>
            </div>
            <Button variant="outline" onClick={() => setDialogOpen(true)}>
              Otwórz pełne okno
            </Button>
          </header>

          <Case id="case-job" title="1. Link do tej rekrutacji — opis ze znaleziskiem (kwota)">
            <JobShareTab enabled defaultJobId={101} />
          </Case>

          <Case id="case-general" title="2. Mój link ogólny — link aktywny, statystyki, widoczność">
            <GeneralLinkTab enabled />
          </Case>
        </main>
        <GenerateInviteLinkV2 open={dialogOpen} onOpenChange={setDialogOpen} defaultJobId={101} />
      </ToastProvider>
    </QueryClientProvider>
  );
}
