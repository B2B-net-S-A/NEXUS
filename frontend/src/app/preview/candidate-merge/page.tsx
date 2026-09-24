"use client";

/**
 * Harness wizualny „Scal z…” (scalanie duplikatów kandydatów).
 *
 * Renderuje PRODUKCYJNE `CandidateMergeDialog` i `MergePlanView` na zasianym
 * cache react-query (`staleTime: Infinity`) — zero zapytań, więc strona działa
 * bez logowania. `?step=pick` pokazuje krok wyboru duplikatu, domyślnie okno
 * stoi na porównaniu; niżej wariant zablokowany (oba profile z Traffita).
 * Dane są fikcyjne.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import {
  CandidateMergeDialog,
  MergePlanView,
} from "@/components/v2/candidate-profile/CandidateMergeDialog";
import {
  candidateMergeKeys,
  type DuplicateSuggestion,
  type MergeChoice,
  type MergePlan,
} from "@/lib/api/candidateMerge";

const SURVIVOR = { id: 4102, name: "Anna", lastname: "Przykładowa", email: "anna.p@example.com", phone: "+48 600 000 111", linkedin: null };

const PLAN: MergePlan = {
  survivor_id: 4102,
  duplicate_id: 5877,
  survivor: { id: 4102, name: "Anna", lastname: "Przykładowa", email: "anna.p@example.com", phone: "+48 600 000 111", city: "Warszawa", external_source: "manual", created_at: "2025-11-02T10:00:00Z", updated_at: "2026-09-20T08:00:00Z" },
  duplicate: { id: 5877, name: "Anna", lastname: "Przykładowa-Nowak", email: "anna.nowak@example.com", phone: null, city: "Warszawa", external_source: "traffit", created_at: "2026-03-14T10:00:00Z", updated_at: "2026-09-21T08:00:00Z" },
  fields: [
    { field: "lastname", label: "Nazwisko", survivor: "Przykładowa", duplicate: "Przykładowa-Nowak", conflict: true, default: "survivor" },
    { field: "email", label: "E-mail", survivor: "anna.p@example.com", duplicate: "anna.nowak@example.com", conflict: true, default: "survivor" },
    { field: "phone", label: "Telefon", survivor: "+48 600 000 111", duplicate: null, conflict: false, default: "survivor" },
    { field: "city", label: "Miasto", survivor: "Warszawa", duplicate: "Warszawa", conflict: false, default: "survivor" },
    { field: "availability_date", label: "Dostępny od", survivor: null, duplicate: "2026-11-01", conflict: false, default: "duplicate" },
  ],
  references: [
    { table: "candidate_stages", column: "candidate_id", rows: 7, conflicts: 0, unresolvable: false },
    { table: "recruitment_processes", column: "candidate_id", rows: 2, conflicts: 1, unresolvable: false },
    { table: "notes", column: "candidate_id", rows: 5, conflicts: 0, unresolvable: false },
    { table: "candidate_documents", column: "candidate_id", rows: 2, conflicts: 0, unresolvable: false },
    { table: "application_submissions", column: "matched_candidate_id", rows: 1, conflicts: 0, unresolvable: false },
  ],
  polymorphic: [
    { table: "activities", rows: 12 },
    { table: "notifications", rows: 3 },
  ],
  moved_rows: 32,
  conflicts: 1,
  blockers: [],
  can_apply: true,
  fingerprint: "0".repeat(64),
};

const BLOCKED: MergePlan = {
  ...PLAN,
  survivor: { ...PLAN.survivor, external_source: "traffit" },
  can_apply: false,
  blockers: [
    {
      code: "both_external",
      message: "Oba profile pochodzą z tego samego systemu zewnętrznego (traffit) — scal je najpierw tam, inaczej nocny import odtworzy usunięty profil.",
    },
  ],
};

const SUGGESTIONS: DuplicateSuggestion[] = [
  { candidate_id: 5877, name: "Anna", lastname: "Przykładowa-Nowak", email: "anna.nowak@example.com", match_score: 0.9, match_reasons: ["name_exact"] },
  { candidate_id: 6120, name: "Anna", lastname: "Przykładowa", email: null, match_score: 0.9, match_reasons: ["name_exact"] },
];

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnMount: false } },
  });
  qc.setQueryData(candidateMergeKeys.suggestions(SURVIVOR.id), SUGGESTIONS);
  qc.setQueryData(candidateMergeKeys.preview(SURVIVOR.id, 5877), PLAN);
  qc.setQueryData(candidateMergeKeys.preview(SURVIVOR.id, 6120), BLOCKED);
  return qc;
}

function StandaloneView({ plan, title }: { plan: MergePlan; title: string }) {
  const [choices, setChoices] = useState<Record<string, MergeChoice>>({});
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <MergePlanView plan={plan} choices={choices} onChoose={(f, c) => setChoices((p) => ({ ...p, [f]: c }))} />
    </section>
  );
}

export default function CandidateMergePreviewPage() {
  const params = useSearchParams();
  const client = useMemo(seededClient, []);
  const [open, setOpen] = useState(true);
  const pickStep = params.get("step") === "pick";
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="mx-auto max-w-5xl space-y-6 bg-background p-6">
          <h1 className="text-lg font-semibold">Harness: scalanie duplikatów kandydatów</h1>
          <button
            type="button"
            className="rounded-md border border-border px-3 py-1.5 text-sm"
            onClick={() => setOpen(true)}
          >
            Otwórz okno „Scal z…”
          </button>
          <StandaloneView plan={PLAN} title="Porównanie — można scalić" />
          <StandaloneView plan={BLOCKED} title="Porównanie — zablokowane" />
          <CandidateMergeDialog
            key={pickStep ? "pick" : "compare"}
            open={open}
            onOpenChange={setOpen}
            candidate={SURVIVOR}
            initialDuplicateId={pickStep ? null : 5877}
          />
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
