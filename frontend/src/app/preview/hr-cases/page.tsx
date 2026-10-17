"use client";

/**
 * Harness „Ludzie → Sprawy administracja@” (makieta 11 raportu „Ludzie
 * w NEXUSIE”).
 *
 * Prawdziwe `PageHeader` + `PeopleSectionNav` + `CasesBoard` (jak
 * `/people/cases`) i `CaseDetailView` (jak `/people/cases/[id]`) na zasianym
 * cache, ZERO zapytań (`hr-harness.tsx`). Ogląda osoba z obsługi skrzynki
 * (uprawnienie „Sprawy”), więc widzi „Moje / Wszystkie” i „Nowa sprawa”.
 *
 * Stany (`?state=`):
 * - `board` (domyślnie) — tablica: Nowa 3 (onboarding konsultantki z maila
 *   spięty z kontraktem, faktura z maila, offboarding z odejścia), W toku 2,
 *   Czeka na kogoś 1, Zrobione (41 w miesiącu); zasiane są „Moje”, każdy
 *   obszar i „Pokaż zamknięte” — przełączenie filtra nie wysyła zapytania
 *   (wyszukiwarka tekstem już tak, bo każdy znak to inny klucz);
 * - `detail` — szczegół sprawy onboardingu: opis, mail od klienta
 *   z załącznikiem, komentarz, checklista 1/4, powiązany kontrakt; okno
 *   „Edytuj” ma zasianą listę osób.
 */

import { CaseDetailView } from "@/components/admin-cases/CaseDetailView";
import { CasesBoard } from "@/components/admin-cases/CasesBoard";
import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import type { CaseListFilters } from "@/lib/api/admin-cases";
import type { HrConfig } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST, HR_CONFIG_QUERY_KEY, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import {
  BOARD_AREAS,
  CASE_ASSIGNEES,
  ONBOARDING_CASE_ID,
  caseList,
  onboardingCase,
} from "./fixtures";

const KNOWN = ["board", "detail"] as const;

const STATES = [
  { key: "board", label: "Tablica spraw" },
  { key: "detail", label: "Sprawa onboardingu" },
] as const;

// Klucze `lib/api/admin-cases.ts` — moduł nie eksportuje swojej fabryki kluczy
// (`keys`), więc powtarzamy ją tu 1:1. Obiekt filtrów ma TEN SAM kształt co
// w `CasesBoard` (`mine`, `area` z `null`, `q`, `include_closed`).
const caseKeys = {
  list: (filters: CaseListFilters) => ["admin-cases", "list", filters] as const,
  detail: (id: number) => ["admin-cases", "detail", id] as const,
  assignees: ["admin-cases", "assignees"] as const,
};

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), KNOWN, "board");
  const today = warsawToday();
  const config: HrConfig = hrConfig({ cases: true, has_assigned_cases: true });
  const client = harnessQueryClient();
  client.setQueryData(HR_CONFIG_QUERY_KEY, config);
  client.setQueryData(["hr", "counts"], { approvals: null, cases: 2 });
  for (const mine of [false, true]) {
    for (const area of BOARD_AREAS) {
      for (const includeClosed of [false, true]) {
        const filters: CaseListFilters = { mine, area, q: "", include_closed: includeClosed };
        client.setQueryData(caseKeys.list(filters), caseList(today, filters));
      }
    }
  }
  client.setQueryData(caseKeys.detail(ONBOARDING_CASE_ID), onboardingCase(today));
  client.setQueryData(caseKeys.assignees, CASE_ASSIGNEES);
  return {
    user: { ...HR_CAST.zofia, grants: ["cases" as const] },
    client,
    value: { state, config },
  };
}

export default function HrCasesPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Sprawy administracja@"
      note="Dane fikcyjne, bez zapytań. Ogląda osoba z obsługi skrzynki (uprawnienie „Sprawy”); maile, nowe kontrakty i odejścia zakładają sprawy same."
      states={STATES}
      current={state}
    >
      {state === "detail" ? (
        <CaseDetailView caseId={ONBOARDING_CASE_ID} />
      ) : (
        <div className="space-y-4">
          <PageHeader
            title="Sprawy administracja@"
            description="Maile ze skrzynki, nowe kontrakty i odejścia zakładają sprawy same."
            density="compact"
          />
          <PeopleSectionNav config={config} active="cases" />
          <CasesBoard config={config} />
        </div>
      )}
    </HrHarnessShell>
  );
}
