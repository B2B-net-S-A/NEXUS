"use client";

/**
 * Harness „Struktura u klientów” — propozycje automatu i akcept Delivery Leada
 * (decyzja Artura 18.10.2026 „Propozycja automatu + akcept DL”).
 *
 * W aplikacji to zakładka Opieki `/care?tab=structure` (dzwonek „Uzupełnij
 * strukturę u klienta” prowadzi tu z `&client=<id>`) i zwijana sekcja
 * „Propozycje automatu” nad drzewem w zakładce klienta. Harness pokazuje
 * prawdziwy `StructureTab` na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 * Ogląda Delivery Lead klientów.
 *
 * Stany: lista klientów z Telekomem (pewne, do sprawdzenia z alternatywą,
 * bez propozycji, pominięte; „Podlega pod”) i Bank z jedną pewną propozycją
 * z pola „Line Manager”. Stan `bar` — pasek „Do zatwierdzenia” z zakładki
 * klienta „Ludzie i technologie” (22.10.2026): jedna propozycja Telekomu
 * i „Wszystkie propozycje (N)”. „Zatwierdź”, „Zmień” i „Pomiń” odcina
 * interceptor harnessu — toast mówi wtedy o błędzie zapisu.
 */

import { ApprovalBar } from "@/components/care/client/ApprovalBar";
import { StructureTab } from "@/components/care/structure/StructureTab";
import { hrKeys } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST, HR_CLIENTS, hrConfig } from "../hr-fixtures";
import { HrHarnessLoading, HrHarnessShell, harnessQueryClient, pickState, useHrHarness } from "../hr-harness";
import { seedStructure } from "./fixtures";

const KNOWN = ["telecom", "bank", "bar"] as const;
const STATES = [
  { key: "telecom", label: "Telekom (wszystkie stany)", href: `?state=telecom&client=${HR_CLIENTS.telecom.id}` },
  { key: "bank", label: "Bank (jedna pewna)", href: `?state=bank&client=${HR_CLIENTS.bank.id}` },
  { key: "bar", label: "Pasek „Do zatwierdzenia” (zakładka klienta)", href: "?state=bar" },
] as const;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), KNOWN, "telecom");
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, hrConfig());
  seedStructure(client, warsawToday());
  return { user: HR_CAST.kamil, client, value: { state } };
}

export default function HrClientStructurePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Struktura u klientów"
      note="Dane fikcyjne, bez zapytań. Ogląda Delivery Lead; propozycje menedżerów konsultantów i „Podlega pod” z pewnością i źródłem — nic nie zapisuje się samo."
      states={STATES}
      current={ready.value.state}
    >
      {ready.value.state === "bar" ? (
        <ApprovalBar clientId={HR_CLIENTS.telecom.id} />
      ) : (
        <StructureTab />
      )}
    </HrHarnessShell>
  );
}
