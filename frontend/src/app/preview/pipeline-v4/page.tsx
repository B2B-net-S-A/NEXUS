"use client";

/**
 * Harness Tablicy Pipeline v4 (23.09.2026) — WYŁĄCZNIE mocki.
 *
 * PRODUKCYJNA `KanbanBoardV2` na szablonie „Default B2B” z kartami, które
 * niosą wszystkie odznaki v4: źródło wejścia, blokadę 12 h (własną, cudzą,
 * wolną), przepięcie, „Czeka na DL”, stawkę do klienta, terminarz rozmowy,
 * brak zamówienia i pasek zamkniętych w czterech grupach. Makieta:
 * https://claude.ai/artifact/JQ8qdz16J6wG24WKTSgv6i
 *
 * Żadne zapytanie nie wychodzi z harnessu (interceptor żądania odrzuca je
 * lokalnie) — sekcje, które same pobierają dane (propozycje na górze Nowych),
 * pokazują wtedy swój stan błędu, a nie przerzucają na /login.
 * `?as=dl` — patrzy Delivery Lead (widzi „Przejmij” na cudzej blokadzie).
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 4343;
const HOUR = 3_600_000;

function inHours(h: number): string {
  return new Date(Date.now() + h * HOUR).toISOString();
}

let nextId = 1;
function card(
  first: string,
  last: string,
  extra: Partial<KanbanItem> = {},
): KanbanItem {
  const id = nextId++;
  return {
    id,
    candidate_id: 9000 + id,
    stage: "new",
    name: first,
    lastname: last,
    days_in_stage: 1,
    added_to_job_by_name: "Marta Nowak",
    process_state_version: 1,
    ...extra,
  } as KanbanItem;
}

function col(
  stage: string,
  name: string,
  category: "internal" | "external" | "terminal",
  defId: number,
  items: KanbanItem[],
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

function columns(viewerId: number): KanbanColumn[] {
  nextId = 1;
  return [
    col("posting", "Ogłoszenia", "internal", 10, [
      card("Karolina", "Wiśniewska", { entry_source: "application", can_take: true }),
    ]),
    col("new", "Nowi / Analiza CV", "internal", 11, [
      card("Tomasz", "Zieliński", {
        entry_source: "added_manual",
        claim_user_id: viewerId,
        claim_user_name: "Marta Nowak",
        claim_until: inHours(9.2),
      }),
      card("Paweł", "Nowicki", {
        entry_source: "added_manual",
        added_to_job_by_name: "Anna Kowal",
        claim_user_id: 3,
        claim_user_name: "Anna Kowal",
        claim_until: inHours(3.4),
        can_take: viewerId !== 7,
      }),
      card("Marek", "Lis", {
        entry_source: "added_manual",
        added_to_job_by_name: "Piotr Sowa",
        can_take: true,
        days_in_stage: 2,
      }),
      card("Ewa", "Dąbrowska", {
        entry_source: "reassign",
        reassign_from_title: "Java Developer · PKO BP",
        claim_user_id: viewerId,
        claim_user_name: "Marta Nowak",
        claim_until: inHours(11.5),
      }),
      card("Jakub", "Mazur", { entry_source: "proposal", can_take: true }),
    ]),
    col("screening", "Screening", "internal", 12, []),
    col("verified", "Zweryfikowany", "internal", 13, [
      card("Anna", "Kowalczyk", {
        days_in_stage: 1,
        expected_rate_value: 150,
        expected_rate_unit: "hourly",
        auto_cv_ready: true,
      }),
      card("Michał", "Wójcik", { days_in_stage: 0, auto_cv_ready: true }),
    ]),
    col("interview", "Przepuszczony przez DZ", "internal", 14, []),
    col("new", "Wysłać do Cpro", "internal", 15, []),
    col("cv_sent", "CV Wysłane", "internal", 16, [
      card("Łukasz", "Kamiński", {
        client_rate_value: 165,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
        days_in_stage: 5,
      }),
      card("Natalia", "Lewandowska", {
        client_rate_value: 158,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
        days_in_stage: 2,
      }),
    ]),
    col("new", "Preparation Meeting", "external", 17, []),
    col("client_interview", "Interview Klient", "external", 18, [
      card("Katarzyna", "Woźniak", {
        interview_badge: { kind: "choose_slot", label: "Wybierz termin · 3 propozycje", tone: "wait" },
      }),
      card("Grzegorz", "Jankowski", {
        interview_badge: { kind: "prep_done", label: "czw 25.09 · 14:00 · Prep ✓", tone: "info" },
      }),
      card("Magdalena", "Pawlak", {
        interview_badge: { kind: "call_due", label: "Zadzwoń · 18 min po rozmowie", tone: "urgent" },
      }),
    ]),
    col("acceptance", "Akceptacja", "external", 19, [
      card("Joanna", "Kaczmarek", {
        client_rate_value: 175,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
      }),
    ]),
    col("new", "Umowa wysłana", "external", 20, [card("Krzysztof", "Piotrowski", { days_in_stage: 2 })]),
    col("new", "Umowa podpisana", "external", 21, []),
    col("hired", "Zatrudniony", "terminal", 22, [
      card("Agnieszka", "Grabowska", { order_status: "missing" }),
      card("Bartosz", "Zając", { order_status: "complete" }),
    ], "hired"),
    col("onboarding", "Onboarding", "external", 23, []),
    col("rejected", "Odrzucony", "terminal", 24, [
      card("Robert", "Szymański", { ended_by: "client" }),
      card("Dawid", "Król", { ended_by: "recruiter" }),
      card("Iga", "Wrona", { ended_by: null }),
      card("Olek", "Nowy", { ended_by: "delivery_lead" }),
    ], "rejected"),
    col("withdrawn", "Wycofany", "terminal", 25, [card("Zofia", "Kot", { ended_by: "candidate" })], "withdrawn"),
  ];
}

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/pipeline-v4 nie wysyła zapytań."), {
          isAxiosError: true,
          code: "ERR_PREVIEW_OFFLINE",
        }),
      ),
    ),
  );
  useEffect(
    () => () => {
      api.interceptors.request.eject(interceptorId);
    },
    [interceptorId],
  );
}

function PipelineV4Harness() {
  useNetworkBlocked();
  const params = useSearchParams();
  const asDl = params.get("as") === "dl";
  const viewerId = asDl ? 5 : 7;
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } }),
  );
  const [ready, setReady] = useState(false);
  useEffect(() => {
    // Pełny profil: bez `profile_completed` powłoka przerzuca na /onboarding.
    useAuthStore.setState({
      user: {
        id: viewerId,
        email: "preview@example.com",
        name: asDl ? "Kamil Rudnicki" : "Marta Nowak",
        role: asDl ? "delivery_lead" : "recruiter",
        roles: [asDl ? "delivery_lead" : "recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      hydrated: true,
    });
    setReady(true);
  }, [asDl, viewerId]);
  const cols = useMemo(() => columns(viewerId), [viewerId]);
  if (!ready) return null;

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <TooltipProvider>
          <main className="min-h-screen bg-background p-4 text-foreground">
            <h1 className="mb-3 text-lg font-semibold">
              Tablica Pipeline v4 — harness ({asDl ? "Delivery Lead" : "rekruterka Marta"})
            </h1>
            <KanbanBoardV2 columns={cols} jobId={JOB_ID} jobTitle="Senior Java Developer" />
          </main>
        </TooltipProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function PipelineV4Preview() {
  return (
    <Suspense fallback={null}>
      <PipelineV4Harness />
    </Suspense>
  );
}
