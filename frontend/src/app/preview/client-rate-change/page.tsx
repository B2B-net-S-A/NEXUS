"use client";

// Harness zmiany stawki do klienta po wysyłce CV (20.10.2026, wariant A):
// wiersz stawek z profilu kandydata (Rekrutacje) i okno „Zmień stawkę do
// klienta” — para bez zamówienia (z jedną zmianą) i para z zamówieniem.
// Dane fikcyjne, ZERO zapytań: historia i sprawy stawki kandydata są zasiane
// w cache tymi samymi kluczami, których używają komponenty, a interceptor
// odcina sieć — „Zapisz stawkę” kończy się komunikatem o błędzie.

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { RecruitmentRateRow } from "@/components/v2/candidate-profile/RecruitmentsTab";
import { ClientRateChangeDialog } from "@/components/v2/rate-change/ClientRateChangeDialog";
import { api } from "@/lib/api";
import {
  clientRateHistoryQueryKey,
  type ClientRateHistory,
} from "@/lib/api/clientRateHistory";
import { rateChangesQueryKey } from "@/lib/rate-change";
import { useAuthStore } from "@/store/auth";

const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString();

const REASONS: ClientRateHistory["reasons"] = [
  { value: "client_negotiated", label: "Klient wynegocjował inną stawkę" },
  { value: "send_mistake", label: "Pomyłka przy wysyłce CV" },
  { value: "other", label: "Inny powód" },
];

const CHANGED: ClientRateHistory = {
  current: { value: 145, unit: "hourly", currency: "PLN" },
  current_label: "145 zł/h",
  sent: {
    at: daysAgo(3),
    by_name: "Ewa Przykładowa",
    rate: { value: 150, unit: "hourly", currency: "PLN" },
    label: "150 zł/h",
  },
  changes: [
    {
      at: daysAgo(1),
      by_name: "Ewa Przykładowa",
      old: { value: 150, unit: "hourly", currency: "PLN" },
      new: { value: 145, unit: "hourly", currency: "PLN" },
      old_label: "150 zł/h",
      new_label: "145 zł/h",
      reason: "client_negotiated",
      reason_label: "Klient wynegocjował inną stawkę",
      note: "Klient zszedł do 145 po drugiej rozmowie",
    },
  ],
  order_lock: null,
  can_write: true,
  reasons: REASONS,
};

const LOCKED: ClientRateHistory = {
  current: { value: 160, unit: "hourly", currency: "PLN" },
  current_label: "160 zł/h",
  sent: {
    at: daysAgo(40),
    by_name: "Ewa Przykładowa",
    rate: { value: 160, unit: "hourly", currency: "PLN" },
    label: "160 zł/h",
  },
  changes: [],
  order_lock: {
    order_id: 501,
    contract_id: 601,
    title: "Bank Przykładowy — Senior Java Developer",
    rate_client: 160,
    rate_unit: "hourly",
    currency: "PLN",
  },
  can_write: false,
  reasons: REASONS,
};

const PAIRS = [
  { candidateId: 31, jobId: 41, title: "Anna Przykładowa · Senior Java Developer · Bank Przykładowy", history: CHANGED, candidateRate: 120 },
  { candidateId: 32, jobId: 42, title: "Jan Testowy · Senior Java Developer · Bank Przykładowy (jest zamówienie)", history: LOCKED, candidateRate: 125 },
];

export default function ClientRateChangePreviewPage() {
  const [ready, setReady] = useState(false);
  const [openFor, setOpenFor] = useState<number | null>(null);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
    });
    for (const pair of PAIRS) {
      // `updatedAt` w przyszłości: hook ma własne `staleTime`, a odświeżenie
      // przy odciętej sieci kończy się błędem zamiast danych.
      qc.setQueryData(clientRateHistoryQueryKey(pair.candidateId, pair.jobId), pair.history, {
        updatedAt: Date.now() + 86_400_000,
      });
      qc.setQueryData(rateChangesQueryKey(pair.candidateId, pair.jobId), {
        candidate_id: pair.candidateId,
        job_id: pair.jobId,
        current: null,
        board_column: "client_interview",
        notifies: true,
        cv_at_client: true,
        client_rate: null,
        changes: [],
      }, { updatedAt: Date.now() + 86_400_000 });
    }
    return qc;
  });

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 4,
        email: "preview@example.com",
        name: "Ewa Przykładowa",
        role: "delivery_lead",
        roles: ["delivery_lead"],
        permissions: { recruitment_manage: "allow" },
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
      } as never,
      token: "preview",
    } as never);
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  const open = PAIRS.find((p) => p.candidateId === openFor) ?? null;
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
          <h1 className="text-lg font-semibold">Podgląd: zmiana stawki do klienta po wysyłce CV</h1>
          {PAIRS.map((pair) => (
            <section key={pair.candidateId} className="rounded-lg border border-border bg-card p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold">{pair.title}</h2>
                <button
                  type="button"
                  className="text-sm text-primary underline"
                  onClick={() => setOpenFor(pair.candidateId)}
                >
                  Otwórz okno „Zmień”
                </button>
              </div>
              <RecruitmentRateRow
                candidateId={pair.candidateId}
                jobId={pair.jobId}
                clientRate={{ value: pair.history.current?.value ?? 0, unit: "hourly", currency: "PLN" }}
                expectedRate={{ value: pair.candidateRate, unit: "hourly", currency: "PLN" }}
                clientRateAccess={{ canView: true, canWrite: true }}
              />
            </section>
          ))}
        </main>
        {open ? (
          <ClientRateChangeDialog
            open
            onOpenChange={(o) => !o && setOpenFor(null)}
            candidateId={open.candidateId}
            jobId={open.jobId}
            description={open.title}
            candidateRate={{ value: open.candidateRate, unit: "hourly" }}
          />
        ) : null}
      </ToastProvider>
    </QueryClientProvider>
  );
}
