"use client";

/**
 * Harness „Umowa przedwstępna” (0506, 21.10.2026): PRODUKCYJNE
 * `PreContractSection` (cztery stany pary), `PreContractsList` i kafelek
 * pulpitu na danych wstrzykniętych do pamięci zapytań — zero zapytań.
 * Dane fikcyjne. `?tab=` przełącza zakładkę listy.
 */

import { Suspense, useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { PreContractsTile } from "@/components/v2/dashboard/custom/PreContractsTile";
import { PreContractSection } from "@/components/v2/person/pre-contract/PreContractSection";
import { PreContractsList } from "@/components/v2/recruitment/PreContractsList";
import {
  PRE_CONTRACT_TABS,
  preContractPairKey,
  type PreContractList,
  type PreContractPair,
  type PreContractRequest,
} from "@/lib/api/preContracts";

const JOB = 9001;

function req(id: number, candidateId: number, name: string, over: Partial<PreContractRequest>): PreContractRequest {
  return {
    id,
    candidate_id: candidateId,
    candidate_name: name,
    job_id: JOB,
    job_title: "Backend Java",
    client_name: "Instytut Przykładowy",
    state: "requested",
    state_label: "Prośba — nie wystawiona",
    badge: { state: "requested", label: "Przedwstępna przed wysłaniem CV — nie wystawiona", tone: "missing", detail: "" },
    is_open: true,
    needed_before: "cv_sent",
    needed_before_label: "przed wysłaniem CV",
    reason: "Klient zaprasza tylko dwie osoby na test.",
    requested_by: { id: 2, name: "Paweł Przykładowy (DL)" },
    requested_at: "2026-10-20T08:00:00Z",
    assignee: { id: 3, name: "Kasia Testowa" },
    watchers: [
      { id: 2, name: "Paweł Przykładowy (DL)" },
      { id: 3, name: "Kasia Testowa" },
    ],
    watching: false,
    can_withdraw: true,
    can_decide_penalty: false,
    stage_name: "Zweryfikowany",
    events: [
      { id: id * 10, kind: "requested", label: "Prośba", at: "2026-10-20T08:00:00Z", actor: { id: 2, name: "Paweł Przykładowy (DL)" } },
    ],
    ...over,
  };
}

const REQUESTED = req(1, 101, "Anna Przykładowa", {});
const WAITING_COMPANY = req(2, 102, "Marek Fikcyjny", {
  state: "candidate_signed",
  state_label: "Kandydat podpisał — czeka podpis firmy",
  badge: { state: "candidate_signed", label: "Przedwstępna: czeka na podpis firmy", tone: "signer", detail: "" },
  document_id: 77,
  sent_at: "2026-10-21T09:00:00Z",
  candidate_signed_at: "2026-10-23T10:00:00Z",
  candidate_signature_form: "trusted_profile",
  candidate_signature_form_label: "profil zaufany",
  candidate_file_name: "przedwstepna_kandydat.pdf",
  valid_until: "2026-12-20",
  can_withdraw: false,
  events: [
    { id: 20, kind: "requested", label: "Prośba", at: "2026-10-20T08:00:00Z", actor: { id: 2, name: "Paweł Przykładowy (DL)" } },
    { id: 21, kind: "issued", label: "Wystawiona", at: "2026-10-21T08:30:00Z", actor: { id: 3, name: "Kasia Testowa" } },
    { id: 22, kind: "sent", label: "Wysłana", at: "2026-10-21T09:00:00Z", actor: { id: 3, name: "Kasia Testowa" } },
    { id: 23, kind: "candidate_signed", label: "Kandydat podpisał", at: "2026-10-23T10:00:00Z", actor: { id: 3, name: "Kasia Testowa" } },
  ],
});
const SIGNED_B2B = req(3, 103, "Ola Testowa", {
  state: "signed",
  state_label: "Podpisana",
  needed_before: "b2b_contract",
  needed_before_label: "przed umową B2B",
  badge: { state: "signed", label: "Umowa B2B: zostało 3 dni roboczych", tone: "late", detail: "" },
  document_id: 78,
  sent_at: "2026-10-10T09:00:00Z",
  candidate_signed_at: "2026-10-11T10:00:00Z",
  candidate_signature_form: "handwritten_scan",
  candidate_signature_form_label: "odręcznie, skan",
  candidate_file_name: "skan.pdf",
  company_signed_at: "2026-10-12T10:00:00Z",
  company_file_name: "obie.pdf",
  valid_until: "2026-12-10",
  b2b_deadline: "2026-10-27",
  can_withdraw: false,
  stage_name: "Akceptacja i umowa",
});
const LATE = req(4, 104, "Ewa Fikcyjna", {
  badge: { state: "requested", label: "Przedwstępna przed wysłaniem CV — nie wystawiona", tone: "late", detail: "" },
  requested_by: { id: 5, name: "Monika Przykładowa (HoR)" },
  stage_name: "CV wysłane",
  can_withdraw: false,
});

const PAIRS: ReadonlyArray<{ title: string; candidateId: number; pair: PreContractPair }> = [
  { title: "Bez prośby", candidateId: 100, pair: { current: null, history: [], documents: [] } },
  {
    title: "Prośba DL — do wystawienia",
    candidateId: 101,
    pair: {
      current: REQUESTED,
      history: [],
      documents: [{ id: 76, document_type: "preliminary_participation_jdg", document_date: "2026-10-21", status: "issued", signed: false, linked: false }],
    },
  },
  { title: "Kandydat podpisał", candidateId: 102, pair: { current: WAITING_COMPANY, history: [], documents: [] } },
  { title: "Podpisana, termin B2B", candidateId: 103, pair: { current: SIGNED_B2B, history: [], documents: [] } },
];

const LIST: PreContractList = {
  items: [WAITING_COMPANY, REQUESTED, LATE],
  counts: { todo: 3, mine: 2, expiring: 0, b2b: 1, penalty: 0, all: 4 },
};

export default function PreContractsPreviewPage() {
  const client = useMemo(() => {
    const c = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    for (const p of PAIRS) c.setQueryData(preContractPairKey(p.candidateId, JOB), p.pair);
    for (const t of PRE_CONTRACT_TABS) {
      const items =
        t.value === "b2b" ? [SIGNED_B2B] : t.value === "all" ? [...LIST.items, SIGNED_B2B] : t.value === "todo" ? LIST.items : [];
      c.setQueryData(["pre-contract", "list", t.value], { ...LIST, items });
    }
    return c;
  }, []);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <div className="mx-auto max-w-[1280px] space-y-8 p-6">
          <h1 className="text-xl font-bold">Umowa przedwstępna — harness (dane fikcyjne)</h1>
          <section className="grid gap-4 lg:grid-cols-2">
            {PAIRS.map((p) => (
              <div key={p.candidateId} className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">{p.title}</p>
                <PreContractSection candidateId={p.candidateId} jobId={JOB} personLabel={`Osoba ${p.candidateId} · Backend Java`} />
              </div>
            ))}
          </section>
          <section className="space-y-2">
            <h2 className="text-lg font-semibold">Lista „Umowy przedwstępne”</h2>
            <Suspense fallback={null}>
              <PreContractsList />
            </Suspense>
          </section>
          <section className="max-w-xs space-y-2 rounded-lg border border-border p-3">
            <h2 className="text-sm font-semibold">Kafelek pulpitu</h2>
            <PreContractsTile />
          </section>
        </div>
      </ToastProvider>
    </QueryClientProvider>
  );
}
