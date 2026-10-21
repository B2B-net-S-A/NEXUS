"use client";

import { Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PrepReviewSettings } from "@/components/settings/PrepReviewSettings";
import type { PrepReviewConfig, PrepReviewConfigState } from "@/lib/api/prepReviewConfig";

// Harness Ustawienia → Ocena prepów (0505). Fikcyjne dane, zero zapytań przy
// ładowaniu. `?tryb=odczyt` = widok rekrutera i Delivery Leada (bez edycji).

const DAY_MS = 24 * 60 * 60 * 1000;
const SEED_FRESH = { updatedAt: Date.now() + DAY_MS };

const CONFIG: PrepReviewConfig = {
  prep1: {
    weights: { topics: 25, must_answers: 40, client_questions: 20, talk_share: 15 },
    topics: [
      { label: "Klient i projekt: zespół, technologia, tryb pracy", required: true },
      { label: "Przebieg rozmowy u klienta: kto, ile trwa, live coding", required: true },
      { label: "Doświadczenie pod każdy must-have", required: true },
      { label: "Stawka i dostępność", required: true },
      { label: "Pytania kandydata do klienta", required: false },
    ],
  },
  prep2: {
    weights: { prep1_followup: 40, topics: 25, client_questions: 20, talk_share: 15 },
    topics: [
      { label: "Punkty z notatki na Prep 2", required: true },
      { label: "Powtórka pytań klienta", required: true },
      { label: "Logistyka: link Teams, kamera, punktualność", required: true },
      { label: "Motywacja i ostatnie wątpliwości", required: false },
    ],
  },
  answer_scale: {
    strong: { description: "Konkretny projekt, własna rola („ja”), skala albo liczby", points: 100 },
    general: { description: "Zna temat, ale bez przykładu albo mówi „my” zamiast „ja”", points: 50 },
    weak: { description: "Nie umie odpowiedzieć, myli pojęcia albo zmienia temat", points: 0 },
    missing: { description: "Temat nie padł na prepie", points: 0 },
  },
  max_client_questions: 6,
  good_threshold: 80,
  weak_threshold: 50,
  min_minutes_enabled: true,
  min_minutes: 10,
  talk_share_enabled: true,
  talk_share_target: 45,
  required_topic_caps_ok: true,
  weak_must_caps_ok: true,
  followup: {
    weak_answers: true,
    general_answers: true,
    missing_required_topics: true,
    unpracticed_client_questions: true,
    max_items: 5,
  },
  ai_hints: "Przy „Co usprawnić” pisz do prowadzącego konkretnie: który temat i w którym momencie rozmowy.",
};

function seededClient(canEdit: boolean): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  const state: PrepReviewConfigState = {
    config: CONFIG,
    version: 2,
    defaults: { ...CONFIG, max_client_questions: 20, ai_hints: "" },
    can_edit: canEdit,
    history: [
      {
        version: 2,
        created_at: "2026-10-22T09:30:00Z",
        author: "Anna Przykładowa",
        reason: "za dużo punktów, prep zawsze słaby",
        changes: ["Najwięcej pytań klienta: 20 → 6", "Zmieniono wskazówki dla AI"],
      },
      {
        version: 1,
        created_at: "2026-10-21T15:00:00Z",
        author: "Jan Testowy",
        reason: null,
        changes: ["Prep 1 · tematy prowadzącego zmienione"],
      },
    ],
  };
  qc.setQueryData(["prep-review-config"], state, SEED_FRESH);
  return qc;
}

function PrepReviewSettingsPreview() {
  const readOnly = useSearchParams().get("tryb") === "odczyt";
  const client = useMemo(() => seededClient(!readOnly), [readOnly]);
  return (
    <QueryClientProvider client={client}>
      <main className="min-h-dvh bg-background p-4 sm:p-6">
        <div className="mx-auto max-w-7xl space-y-6">
          <h1 className="text-2xl font-bold text-foreground">Ocena prepów</h1>
          <PrepReviewSettings />
        </div>
      </main>
    </QueryClientProvider>
  );
}

export default function PrepReviewSettingsPreviewPage() {
  return (
    <Suspense>
      <PrepReviewSettingsPreview />
    </Suspense>
  );
}
