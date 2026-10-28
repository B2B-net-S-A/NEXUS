"use client";

import { Suspense } from "react";

import { OpportunitiesView } from "@/components/sales/OpportunitiesView";
import { SalesShell } from "@/components/sales/SalesShell";
import { salesKeys, type Opportunity, type Pipeline, type Stage } from "@/lib/api/sales";

import { harnessQueryClient, HrHarnessShell, useHrHarness } from "../hr-harness";

// Sprzedaż → Szanse (tablica i lista) na fikcyjnych danych, bez zapytań.
// `?view=list` przełącza na listę (ten sam parametr co prawdziwy ekran).

const STAGES: Stage[] = [
  ["lead", "Lead", 5, "open"],
  ["qualifying-meeting", "Spotkanie kwalifikujące", 20, "open"],
  ["qualified", "Lead kwalifikowany", 40, "open"],
  ["offer-sent", "Oferta wysłana", 60, "open"],
  ["not-qualified", "Niezakwalifikowany", 0, "lost"],
  ["won", "Wygrana", 100, "won"],
  ["lost", "Przegrana", 0, "lost"],
].map(([key, name, probability, outcome], index) => ({
  id: index + 1,
  key: key as string,
  name: name as string,
  position: index,
  probability: probability as number,
  outcome: outcome as Stage["outcome"],
  qualifies: key === "qualified",
  color: null,
}));

const PIPELINE: Pipeline = { id: 1, key: "sales", name: "Sprzedaż", is_default: true, stages: STAGES };

function opportunity(
  id: number,
  company: string,
  title: string,
  stageKey: string,
  value: string | null,
  lastActivityDaysAgo: number,
): Opportunity {
  const stage = STAGES.find((s) => s.key === stageKey) ?? STAGES[0];
  // Od dziś, nie od stałej daty: ekran liczy „bez kontaktu N dni” od Date.now().
  const at = new Date(Date.now() - lastActivityDaysAgo * 86_400_000).toISOString();
  return {
    id,
    title,
    description: null,
    company: { id: id + 100, name: company },
    pipeline_id: 1,
    stage,
    status: stage.outcome,
    service_line: "bodyleasing",
    value,
    mrr_value: value,
    one_off_value: null,
    margin_pct: null,
    currency: "PLN",
    contract_months: 12,
    probability: stage.probability,
    weighted_value: value ? String((Number(value) * stage.probability) / 100) : null,
    expected_close_date: "2026-11-30",
    qualified_at: stage.position >= 2 ? at : null,
    won_at: stage.outcome === "won" ? at : null,
    lost_at: null,
    lost_reason: null,
    primary_contact_id: null,
    roles: [{ title: "Tester automatyzujący", count: 3 }],
    source: null,
    campaign: null,
    tags: [],
    owner: { id: 7, name: "Anna Przykładowa" },
    last_activity_at: at,
    keep_open_until: null,
    archived_at: null,
    created_at: at,
    updated_at: at,
  };
}

const ITEMS: Opportunity[] = [
  opportunity(1, "Bank Przykładowy", "Zespół QA i automatyzacji", "offer-sent", "45000", 2),
  opportunity(2, "Żuraw Systemy Przykładowe", "Data engineering", "lead", "60000", 3),
  opportunity(3, "Kormoran Usługi Fikcyjne", "Analitycy biznesowi", "qualified", "38000", 21),
  opportunity(4, "Czapla Logistyka Testowa", "DevOps", "qualifying-meeting", null, 1),
  opportunity(5, "Mewa Energia Przykładowa", "Java", "won", "52000", 6),
];

function prepare() {
  const client = harnessQueryClient();
  client.setQueryData(salesKeys.pipelines, [PIPELINE]);
  client.setQueryData(
    salesKeys.opportunities({ pipeline_id: 1, owner_id: null, q: "", sort: "updated", archived: false }),
    { items: ITEMS, total: ITEMS.length },
  );
  // Filtr opiekuna czyta osoby z podsumowania lejka i etykiety z Atlasa — bez żądań.
  client.setQueryData(salesKeys.summary(null, "all"), {
    pipeline: { id: 1, name: "Sprzedaż" },
    open_count: 0,
    value: "0",
    weighted: "0",
    mrr: "0",
    stale_count: 0,
    by_owner: [],
    by_stage: [],
  });
  client.setQueryData(salesKeys.ownerLabels, []);
  return {
    user: {
      id: 7,
      name: "Anna Przykładowa",
      email: "anna.przykladowa@example.com",
      role: "recruiter" as const,
      grants: ["sales_view" as const, "sales_edit" as const],
    },
    client,
    value: null,
  };
}

export default function SalesPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <p className="p-6 text-sm text-muted-foreground">Ładowanie…</p>;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Sprzedaż → Szanse"
      note="Handlowiec z „Sprzedaż: edycja”, fikcyjne firmy i szanse."
      param="view"
      states={[
        { key: "board", label: "Tablica" },
        { key: "list", label: "Lista" },
      ]}
    >
      <SalesShell title="Sprzedaż" description="Szanse w lejku, firmy i kogo w nich znamy.">
        <Suspense fallback={null}>
          <OpportunitiesView />
        </Suspense>
      </SalesShell>
    </HrHarnessShell>
  );
}
