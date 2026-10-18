"use client";

/**
 * Harness „Dokumenty osoby” (e-teczka, etap 5, E4; makieta „Dokumenty osoby”
 * z rekomendacji „NEXUS a eBI24”, 17.10.2026).
 *
 * Prawdziwe komponenty na zasianym cache, ZERO zapytań (`hr-harness.tsx`).
 *
 * Stany (`?state=`):
 * - `hr` (domyślnie) — Kadry oglądają e-teczkę Celiny na zleceniu: umowa
 *   i aneks z generatora, oświadczenie studenta, protokół sprzętu jako
 *   odnośnik, ślad usuniętej pomyłki; przyciski „Wgraj”, „Zmień”, „Usuń”;
 * - `person` — Celina ogląda swoje dokumenty (bez zmian);
 * - `payroll` — Płace: tylko dokumenty ze znacznikiem Płac, bez protokołów;
 * - `empty` — Kadry: osoba bez dokumentów;
 * - `retention` — Ustawienia → Kadry: dokumenty po terminie przechowywania
 *   i okresy na rodzaj.
 * Zapisy i pobrania blokuje harness.
 */

import { DocumentsRetentionCard } from "@/components/hr/people/documents/DocumentsRetentionCard";
import { PersonDocumentsSection } from "@/components/hr/people/documents/PersonDocumentsSection";
import { hrKeys } from "@/lib/api/hr";
import { documentKeys } from "@/lib/api/hr-documents";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import {
  CELINA,
  emptyView,
  hrView,
  payrollView,
  personView,
  retentionDue,
} from "./fixtures";

const STATE_KEYS = ["hr", "person", "payroll", "empty", "retention"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "hr", label: "Kadry: e-teczka" },
  { key: "person", label: "Osoba: moje dokumenty" },
  { key: "payroll", label: "Płace" },
  { key: "empty", label: "Kadry: bez dokumentów" },
  { key: "retention", label: "Kadry: po terminie" },
] as const;

const NOTES: Record<State, string> = {
  hr: "Dane fikcyjne, bez zapytań. Oglądają Kadry — wszystko, także ślad usuniętej pomyłki.",
  person: "Dane fikcyjne, bez zapytań. Ogląda Celina — swoje dokumenty, bez zmian.",
  payroll: "Dane fikcyjne, bez zapytań. Płace widzą dokumenty ze swoim znacznikiem, bez protokołów sprzętu.",
  empty: "Dane fikcyjne, bez zapytań. Kadry, osoba jeszcze bez dokumentów.",
  retention: "Dane fikcyjne, bez zapytań. Ustawienia → Kadry: lista do usunięcia po terminie.",
};

const CELINA_USER: HarnessUser = { ...CELINA, role: "employee" };

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "hr");
  const client = harnessQueryClient();
  let user: HarnessUser = { ...HR_CAST.paulina, grants: ["people_admin"] };
  let config = hrConfig({ people_admin: true, has_profile: false });
  if (state === "hr") {
    client.setQueryData(documentKeys.person(CELINA.id), hrView());
  } else if (state === "person") {
    user = CELINA_USER;
    config = hrConfig();
    client.setQueryData(documentKeys.person(CELINA.id), personView());
  } else if (state === "payroll") {
    user = { ...HR_CAST.piotr, grants: ["payroll"] };
    config = hrConfig({ payroll: true, has_profile: false });
    client.setQueryData(documentKeys.person(CELINA.id), payrollView());
  } else if (state === "empty") {
    client.setQueryData(documentKeys.person(CELINA.id), emptyView());
  } else {
    client.setQueryData(documentKeys.retention, retentionDue());
  }
  client.setQueryData(hrKeys.config, config);
  return { user, client, value: { state } };
}

export default function HrDocumentsPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Dokumenty osoby"
      note={NOTES[state]}
      states={STATES}
      current={state}
    >
      {state === "retention" ? (
        <DocumentsRetentionCard />
      ) : (
        <PersonDocumentsSection userId={CELINA.id} name={CELINA.name} enabled />
      )}
    </HrHarnessShell>
  );
}
