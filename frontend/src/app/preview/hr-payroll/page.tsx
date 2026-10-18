"use client";

/**
 * Harness „Ludzie → Płace” (makieta 7 raportu „Ludzie w NEXUSIE”).
 *
 * Prawdziwe `PayrollMonthScreen` (strona `/people/payroll/[ym]`) i
 * `PayrollMonthsScreen` (strona `/people/payroll`) na zasianym cache, ZERO
 * zapytań (`hr-harness.tsx`). Miesiąc to poprzedni miesiąc przeglądarki —
 * ekran liczy „dziś” sam, więc dane i klucze budujemy względem niego.
 *
 * Stany (`?state=`):
 * - `month` (domyślnie) — Finanse z uprawnieniem Płace zamykają poprzedni
 *   miesiąc: osoby ze stawkami, ostrzeżenie o timesheetach, premie do decyzji
 *   z placementów i z Ligi, placementy „liczy się” (10 z 21 dni);
 * - `team` — przełożona bez Płac (D2): godziny i premie swojego zespołu, bez
 *   stawek, kwot wynagrodzenia, eksportu i zamknięcia;
 * - `months` — lista 13 miesięcy (stan, osoby, sumy, premie do decyzji).
 * „Nowa premia” otwiera okno bez zapytań; zapisy blokuje harness.
 */

import { PayrollMonthScreen } from "@/components/hr/payroll/PayrollMonthScreen";
import { PayrollMonthsScreen } from "@/components/hr/payroll/PayrollMonthsScreen";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { payrollKeys } from "@/lib/api/hr-payroll";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import {
  MARTA_REPORTS,
  closingDetail,
  monthsList,
  payrollScene,
} from "./fixtures";

const STATE_KEYS = ["month", "team", "months"] as const;
type State = (typeof STATE_KEYS)[number];

const STATES = [
  { key: "month", label: "Płace: zamknięcie miesiąca" },
  { key: "team", label: "Przełożona (bez stawek, D2)" },
  { key: "months", label: "Lista miesięcy" },
] as const;

const NOTES: Record<State, string> = {
  month: "Dane fikcyjne, bez zapytań. Ogląda Finanse z uprawnieniem Płace; do kwot wchodzą tylko zaakceptowane godziny.",
  team: "Dane fikcyjne, bez zapytań. Ogląda przełożona bez Płac: godziny i premie zespołu, bez stawek (D2).",
  months: "Dane fikcyjne, bez zapytań. Ogląda Finanse z uprawnieniem Płace.",
};

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), STATE_KEYS, "month");
  const scene = payrollScene();
  const team = state === "team";
  const viewer = team ? HR_CAST.marta : { ...HR_CAST.piotr, grants: ["payroll" as const] };
  const config: HrConfig = team
    ? hrConfig({ is_manager: true, direct_reports: MARTA_REPORTS.size })
    : hrConfig({ payroll: true });
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: team ? 2 : null, cases: null });
  client.setQueryData(
    payrollKeys.month(scene.year, scene.month),
    closingDetail(scene, team ? "team" : "payroll"),
  );
  if (!team) client.setQueryData(payrollKeys.months, monthsList(scene));
  return { user: viewer, client, value: { state, config, scene } };
}

export default function HrPayrollPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config, scene } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Płace"
      note={NOTES[state]}
      states={STATES}
      current={state}
    >
      {state === "months" ? (
        <PayrollMonthsScreen config={config} />
      ) : (
        <PayrollMonthScreen config={config} year={scene.year} month={scene.month} />
      )}
    </HrHarnessShell>
  );
}
