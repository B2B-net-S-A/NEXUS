"use client";

// Publiczny harness ekranu „Jakość podpowiedzi systemu” (silnik „Nowi na 20”,
// 23.10.2026). Renderuje PRAWDZIWY `AutofillQualityView`; liczby i raport są
// zasiane w cache ze znacznikiem czasu w przyszłości, więc widok nie pyta API
// (sieć i tak odcina layout `/preview`). Dane fikcyjne. Patrzący jest adminem —
// widać „Robimy / Nie”.

import { useEffect, useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AutofillQualityView } from "@/components/insights/AutofillQualityView";
import {
  autofillQualityKeys,
  type AutofillQualityReport,
  type AutofillQualitySummary,
} from "@/lib/api/autofillQuality";
import { useAuthStore } from "@/store/auth";

const SUMMARY: AutofillQualitySummary = {
  since: "2026-10-16T00:00:00Z",
  until: "2026-10-23T00:00:00Z",
  added: 2840,
  called: 650,
  rejected: 1250,
  decided_pct: 66.9,
  called_pct: 34.2,
  search_error_pct: 41,
  verified: {
    system: { added: 2840, verified: 165, verified_pct: 5.8 },
    manual: { added: 960, verified: 78, verified_pct: 8.1 },
  },
  waiting_now: 412,
  buckets: [
    {
      bucket: "search",
      label: "Błąd wyszukiwania",
      total: 512,
      reasons: [
        { reason: "other_level_or_role", label: "Inny poziom lub inna rola", count: 204 },
        { reason: "too_junior", label: "Za mało doświadczenia", count: 141 },
        { reason: "missing_skill", label: "Brak kluczowej umiejętności", count: 96 },
        { reason: "location_mode", label: "Lokalizacja lub tryb pracy", count: 71 },
      ],
    },
    {
      bucket: "data",
      label: "Brak danych",
      total: 388,
      reasons: [
        { reason: "too_expensive", label: "Za droga", count: 231 },
        { reason: "outdated_cv", label: "CV nieaktualne", count: 157 },
      ],
    },
    {
      bucket: "person",
      label: "Sprawa osoby",
      total: 350,
      reasons: [
        { reason: "not_looking", label: "Nie szuka pracy", count: 198 },
        { reason: "no_answer", label: "Nie odbiera (3 próby)", count: 152 },
      ],
    },
    { bucket: "other", label: "Inne", total: 0, reasons: [] },
  ],
  worst_jobs: [
    { job_id: 9301, job_title: "DevOps (Azure)", feedback: 32, search_errors: 25, search_pct: 78.1, top_reason: "other_level_or_role", top_reason_label: "Inny poziom lub inna rola" },
    { job_id: 9302, job_title: "Analityk biznesowy", feedback: 28, search_errors: 20, search_pct: 71.4, top_reason: "too_junior", top_reason_label: "Za mało doświadczenia" },
    { job_id: 9303, job_title: "Tester automatyzujący", feedback: 14, search_errors: 9, search_pct: 64.3, top_reason: "location_mode", top_reason_label: "Lokalizacja lub tryb pracy" },
  ],
};

const REPORT: AutofillQualityReport = {
  id: 1,
  week_start: "2026-10-19",
  summary: SUMMARY,
  from_model: true,
  created_at: "2026-10-26T07:00:00Z",
  proposals: [
    {
      title: "System dodaje osoby z niższego poziomu do rekrutacji „Senior”",
      kind: "search",
      evidence: "204 odrzucenia „Inny poziom lub inna rola”, głównie w rekrutacjach z „Senior” w tytule.",
      fix: "Uwzględnić w wyniku poziom i tytuł roli z CV; zmierzyć przed i po.",
      decision: null,
    },
    {
      title: "Brak stawki to najczęstszy powód „za droga”",
      kind: "data",
      evidence: "231 odrzuceń „Za droga” przy nieznanej stawce.",
      fix: "Pomijać w dopełnianiu osoby ze znaną „Stawką od” powyżej budżetu +15%.",
      decision: "yes",
    },
    {
      title: "„Nie szuka pracy” wraca w kolejnych rekrutacjach",
      kind: "person",
      evidence: "198 odrzuceń „Nie szuka pracy”.",
      fix: "Pomijać takie osoby w dopełnianiu przez 90 dni.",
      decision: null,
    },
  ],
};

export default function AutofillQualityHarness() {
  const client = useMemo(() => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const fresh = { updatedAt: Date.now() + 86_400_000 };
    for (const days of [7, 30, 90]) qc.setQueryData(autofillQualityKeys.summary(days), SUMMARY, fresh);
    qc.setQueryData(autofillQualityKeys.reports, [REPORT], fresh);
    return qc;
  }, []);
  // Admin w efekcie, nie w renderze — zmiana magazynu w trakcie renderu
  // przerysowuje inny komponent (ostrzeżenie Reacta).
  useEffect(() => {
    useAuthStore.setState({ user: { id: 1, role: "admin", name: "Admin Przykładowy" } } as never);
  }, []);
  return (
    <QueryClientProvider client={client}>
      <div className="p-6">
        <AutofillQualityView />
      </div>
    </QueryClientProvider>
  );
}
