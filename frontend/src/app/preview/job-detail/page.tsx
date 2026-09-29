"use client";

/**
 * Harness strony rekrutacji (nagłówek + Tablica) w ramce aplikacji —
 * WYŁĄCZNIE mocki, zero zapytań.
 *
 * Powstał po zgłoszeniu z 28.09.2026: na laptopie z Windows (skalowanie 150%,
 * okno ≈ 1280 × 650 px CSS) sam nagłówek zajmował ~60% wysokości, a na Macu
 * z oknem 2666 px wszystko mieściło się w jednej linii. Ramka odwzorowuje
 * powłokę (`AppShellV2`: pasek 48 px, `p-6`, menu 240 px od 1280 px, niżej
 * szyna 60 px) i zwiniętą szynę „Otwarte karty” (40 px od `lg`), żeby dało się
 * zmierzyć, ile miejsca zostaje Tablicy przy typowych rozmiarach okna
 * z Windows: 1280 × 720, 1366 × 768, 1536 × 864
 * (`e2e/responsive-preview.spec.ts`).
 *
 * `?empty=1` — puste kolumny widoczne (przełącznik „Ukryj puste kolumny”
 * wyłączony), `?rail=1` — menu zwinięte do szyny 60 px także od 1280 px
 * (zapamiętany wybór użytkownika).
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { JobDetailCompactHeader } from "@/components/v2/jobs/JobDetailCompactHeader";
import { JobRecruitmentPath } from "@/components/v2/jobs/JobRecruitmentPath";
import { RequestStatusBadge } from "@/components/v2/jobs/JobListCells";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { screenedOutQueryKey } from "@/lib/api/applicationScreenings";
import type { NearestStep, PathStep } from "@/lib/job-recruitment-path";
import type { JobHeaderKpi } from "@/lib/job-header-kpis";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";

const JOB_ID = 4344;
const HOUR = 3_600_000;

let nextId = 1;
function card(first: string, last: string, extra: Partial<KanbanItem> = {}): KanbanItem {
  const id = nextId++;
  return {
    id,
    candidate_id: 9100 + id,
    stage: "new",
    name: first,
    lastname: last,
    days_in_stage: 0,
    added_to_job_by_name: "Marta Nowak",
    process_state_version: 1,
    entry_source: "added_manual",
    claim_user_id: 7,
    claim_user_name: "Marta Nowak",
    claim_until: new Date(Date.now() + 11 * HOUR).toISOString(),
    ...extra,
  } as KanbanItem;
}

function col(
  stage: string,
  name: string,
  defId: number,
  items: KanbanItem[],
  category: "internal" | "external" | "terminal" = "internal",
  terminal_type: string | null = null,
): KanbanColumn {
  return {
    stage,
    name,
    category,
    stage_def_id: defId,
    terminal_type,
    count: items.length,
    items: items.map((i) => ({ ...i, stage })),
  } as unknown as KanbanColumn;
}

function columns(): KanbanColumn[] {
  nextId = 1;
  return [
    col("new", "Nowi / Analiza CV", 21, [
      card("Anna", "Przykładowa"),
      card("Jan", "Testowy"),
      card("Ewa", "Fikcyjna"),
      card("Piotr", "Próbny"),
      card("Kamila", "Wzorcowa"),
      card("Tomasz", "Makietowy"),
      card("Zofia", "Szkicowa"),
      card("Adam", "Podglądowy"),
    ]),
    col("screening", "Screening", 22, [
      card("Marek", "Przykładowy", { entry_source: "proposal" }),
    ]),
    col("verified", "Zweryfikowany", 23, []),
    col("interview", "Przepuszczony przez DZ", 24, []),
    col("cv_sent", "CV Wysłane", 25, []),
    col("client_interview", "Rozmowa z klientem", 26, []),
    col("offer_sent", "Umowa", 27, []),
    col("hired", "Zatrudniony", 28, []),
    col("rejected", "Odrzucony", 29, [], "terminal", "rejected"),
    col("withdrawn", "Wycofany", 30, [], "terminal", "withdrawn"),
  ];
}

const STEPS: PathStep[] = [
  { key: "order", label: "Zlecenie", state: "done", detail: "kompletne" },
  { key: "candidates", label: "Kandydaci", state: "active", detail: "9 w procesie · 20 propozycji" },
  { key: "cv", label: "CV do klienta", state: "todo", detail: "0 w QC · 0 wysłanych" },
  { key: "interviews", label: "Rozmowy", state: "todo", detail: "brak zaplanowanych" },
  { key: "contract", label: "Umowa", state: "todo", detail: "obsada 0 / 1" },
];

const NEAREST: NearestStep = {
  rule: "similar",
  sentence: "Przejrzyj 14 osób z podobnych rekrutacji, które klient już zna",
  cta: "Podobne rekrutacje",
  action: { kind: "similar" },
};

const KPIS: JobHeaderKpi[] = [
  { key: "in", label: "w procesie", value: 9, tone: "neutral" },
  { key: "stuck", label: "utknęli > 7 d", value: 0, tone: "neutral" },
  { key: "client", label: "u klienta (CV → interview)", value: 0, tone: "neutral" },
];

const noop = () => undefined;

function JobDetailHarness() {
  const params = useSearchParams();
  const showEmpty = params.get("empty") === "1";
  const railOnly = params.get("rail") === "1";
  const [client] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    // 0404: „Odrzuceni przez AI” — pusta lista, bez zapytania.
    qc.setQueryData(screenedOutQueryKey(JOB_ID), { job_id: JOB_ID, total: 0, items: [] });
    return qc;
  });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    useAuthStore.setState({
      user: {
        id: 7,
        email: "preview@example.com",
        name: "Marta Nowak",
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
    useUiStore.setState({ hideEmptyKanbanColumns: !showEmpty });
    setReady(true);
  }, [showEmpty]);
  if (!ready) return null;

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TooltipProvider>
          <div className="app-shell-root flex h-dvh overflow-hidden bg-background text-foreground">
            {/* Menu: 240 px od 1280 px (domyślne przypięcie), niżej szyna 60 px. */}
            <div
              aria-hidden="true"
              className={
                railOnly
                  ? "hidden h-full w-[60px] shrink-0 border-r border-border bg-sidebar md:block"
                  : "hidden h-full w-[60px] shrink-0 border-r border-border bg-sidebar md:block xl:w-60"
              }
            />
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
              <div aria-hidden="true" className="h-12 shrink-0 border-b border-border" />
              <main className="relative flex-1 overflow-y-auto" data-testid="harness-main">
                <div className="p-4 pb-24 md:p-6">
                  <div className="flex items-start gap-4 lg:gap-6">
                    {/* Zwinięta szyna „Otwarte karty” (JobTabsRail, w-10). */}
                    <div
                      aria-hidden="true"
                      className="hidden h-24 w-10 shrink-0 rounded-xl border border-border bg-card/60 lg:block"
                    />
                    <div className="min-w-0 flex-1 space-y-2">
                      <JobDetailCompactHeader
                        title="Starszy Programista Frontend (Angular) · Angular, TypeScript · 5+ lat"
                        clientName="Bank Przykładowy S.A."
                        referenceNumber="PRZ/001/2026"
                        clientTitle="Starszy Programista Frontend (Angular)"
                        badges={<RequestStatusBadge status="searching" />}
                        subtitle={
                          <span className="text-[12px]">
                            zdalnie · budżet do 95,00 PLN/h · Marta N. · DL: Marta N. · obsada 0 / 1
                          </span>
                        }
                        path={
                          <JobRecruitmentPath
                            steps={STEPS}
                            nearest={NEAREST}
                            onStepClick={noop}
                            onNearestClick={noop}
                          />
                        }
                        kpis={KPIS}
                        presence={
                          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                            MN
                          </span>
                        }
                        activeView="board"
                        onViewChange={noop}
                        onOpenOrder={noop}
                        onOpenHistoryChat={noop}
                        onOpenQuestions={noop}
                        onOpenSimilar={noop}
                        similarPeopleCount={14}
                        championFound={false}
                        onToggleChampion={noop}
                        onAddCandidate={noop}
                      />
                      <KanbanBoardV2
                        columns={columns()}
                        jobId={JOB_ID}
                        jobTitle="Starszy Programista Frontend (Angular)"
                      />
                    </div>
                  </div>
                </div>
              </main>
            </div>
          </div>
        </TooltipProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function JobDetailPreview() {
  return (
    <Suspense fallback={null}>
      <JobDetailHarness />
    </Suspense>
  );
}
