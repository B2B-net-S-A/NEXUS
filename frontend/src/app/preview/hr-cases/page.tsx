"use client";

/**
 * Harness „Ludzie → Sprawy administracja@” (makieta 11 raportu „Ludzie
 * w NEXUSIE”) i wspólnej tablicy pracy z opieką (22.10.2026).
 *
 * Prawdziwe `PageHeader` + `PeopleSectionNav` + `CasesBoard` (jak
 * `/people/cases`), `WorkBoard scope="care"` (jak Opieka → Do zrobienia)
 * i `CaseDetailView` (jak `/people/cases/[id]`) na zasianym cache, ZERO
 * zapytań (`hr-harness.tsx`).
 *
 * Stany (`?state=`):
 * - `board` (domyślnie) — tablica z makiety 19.10.2026 oglądana przez obsługę
 *   skrzynki bez dostępu do opieki (recepcja): Nowa 4, W toku 2, Czeka na
 *   kogoś 1, wąska kolumna „Zrobione” (41 w miesiącu); termin w kolorze,
 *   ikona źródła, kropka priorytetu, pasek listy kontrolnej, „Weź”, „Przenieś
 *   do…”; zasiane są „Moje”, każdy obszar, „Na ten tydzień”, „Bez osoby”
 *   i „Pokaż zamknięte” (wyszukiwarka tekstem wysyła zapytanie, harness je
 *   blokuje);
 * - `detail` — szczegół sprawy onboardingu: opis, mail od klienta
 *   z załącznikiem, komentarz, checklista 1/4, karta „Konsultant”;
 * - `board-care` — te same Sprawy oglądane przez opiekunkę (TCM z „Sprawami”):
 *   obok spraw karty opieki (rozmowy, opinia menedżera, decyzja, popyt),
 *   chip „Opieka”, „Moi podopieczni”, kropka zdrowia przy sprawach
 *   z konsultantem;
 * - `todo` / `todo-list` — Opieka → Do zrobienia (`scope="care"`): karty
 *   opieki nad sprawami przypisanymi do opiekunki; widok Tablica albo Lista;
 * - `panel-case` — panel boczny sprawy onboardingu (skrót, checklista,
 *   komentarz, „Konsultant” z „Przypisz opiekunowi”);
 * - `panel-care` — panel boczny karty rozmowy (przesunięcia, akcja, skrót
 *   Karty konsultanta);
 * - `who` — sprawa z maila z firmy klienta bez kontraktu: pasek „Kogo
 *   dotyczy?” z propozycją.
 */

import { CaseDetailView } from "@/components/admin-cases/CaseDetailView";
import { CasesBoard } from "@/components/admin-cases/CasesBoard";
import { PageHeader } from "@/components/ds/PageHeader";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { WorkBoard } from "@/components/work-board/WorkBoard";
import { caseKeys, type CaseArea, type CaseListFilters } from "@/lib/api/admin-cases";
import { careBoardKeys } from "@/lib/api/care-board";
import { hrKeys, type HrConfig } from "@/lib/api/hr";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
  type HarnessUser,
} from "../hr-harness";
import { PANEL_CARE_KEY, careBoard, contractCards } from "./care-fixtures";
import {
  BOARD_AREAS,
  CASE_ASSIGNEES,
  ONBOARDING_CASE_ID,
  WHO_CASE_ID,
  caseList,
  onboardingCase,
  weekEnd,
  whoCase,
} from "./fixtures";

const KNOWN = [
  "board",
  "detail",
  "board-care",
  "todo",
  "todo-list",
  "panel-case",
  "panel-care",
  "who",
] as const;
type State = (typeof KNOWN)[number];

const STATES = [
  { key: "board", label: "Tablica spraw" },
  { key: "detail", label: "Sprawa onboardingu" },
  { key: "board-care", label: "Sprawy z opieką" },
  { key: "todo", label: "Opieka · Do zrobienia" },
  { key: "todo-list", label: "Do zrobienia · Lista" },
  { key: "panel-case", label: "Panel sprawy" },
  { key: "panel-care", label: "Panel karty opieki" },
  { key: "who", label: "Kogo dotyczy?" },
] as const;

/** Opiekunka (TCM) z dostępem do opieki; w Sprawach — także z uprawnieniem „Sprawy”. */
const CARE_STATES: ReadonlySet<State> = new Set([
  "board-care",
  "todo",
  "todo-list",
  "panel-case",
  "panel-care",
  "who",
]);
/** W „Opiece” opiekunka nie obsługuje skrzynki — widzi tylko sprawy przypisane do siebie. */
const TODO_STATES: ReadonlySet<State> = new Set(["todo", "todo-list", "panel-care"]);

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), KNOWN, "board");
  const today = warsawToday();
  const friday = weekEnd(today);
  const care = CARE_STATES.has(state);
  const handler = !TODO_STATES.has(state);
  const viewer: HarnessUser = care
    ? { ...HR_CAST.natalia, grants: handler ? ["cases"] : [] }
    : { ...HR_CAST.zofia, grants: ["cases"] };
  const config: HrConfig = hrConfig({ cases: handler, has_assigned_cases: true });
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, config);
  client.setQueryData(hrKeys.counts, { approvals: null, cases: 2 });
  const areas: (CaseArea | null)[] = BOARD_AREAS;
  for (const mine of [false, true]) {
    for (const area of areas) {
      for (const includeClosed of [false, true]) {
        for (const week of [false, true]) {
          for (const unassigned of [false, true]) {
            for (const mineCare of [false, true]) {
              // TEN SAM kształt filtrów co w `WorkBoard` — inaczej klucz listy się nie zgodzi.
              const filters: CaseListFilters = {
                mine,
                area,
                q: "",
                include_closed: includeClosed,
                week,
                unassigned,
                ...(mineCare ? { mine_care: true } : {}),
              };
              client.setQueryData(caseKeys.list(filters), caseList(today, filters, viewer.id));
            }
          }
        }
      }
    }
  }
  client.setQueryData(caseKeys.detail(ONBOARDING_CASE_ID), onboardingCase(today, care));
  client.setQueryData(caseKeys.detail(WHO_CASE_ID), whoCase(today));
  client.setQueryData(caseKeys.assignees, CASE_ASSIGNEES);
  for (const scope of ["mine", "all"] as const) {
    client.setQueryData(careBoardKeys.board(scope), careBoard(today, friday, scope));
  }
  for (const card of contractCards(today)) {
    client.setQueryData(careBoardKeys.contractCard(card.contract_id), card);
  }
  return { user: viewer, client, value: { state, config } };
}

/** Okna opieki dostarcza ekran /care — w harnessie akcje niczego nie otwierają. */
const noop = () => undefined;

export default function HrCasesPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, config } = ready.value;
  const cases = (
    <div className="space-y-4">
      <PageHeader
        title="Sprawy administracja@"
        description="Maile ze skrzynki, nowe kontrakty i odejścia zakładają sprawy same."
        density="compact"
      />
      <PeopleSectionNav config={config} active="cases" />
      {state === "panel-case" ? (
        <WorkBoard scope="cases" config={config} initialSelectedKey={`case:${ONBOARDING_CASE_ID}`} />
      ) : (
        <CasesBoard config={config} />
      )}
    </div>
  );
  const todo = (
    <div className="space-y-4">
      <PageHeader
        title="Opieka nad konsultantami"
        description="Do zrobienia: rozmowy, opinie menedżerów, decyzje i popyt — razem ze sprawami."
        density="compact"
      />
      <WorkBoard
        scope="care"
        config={config}
        initialView={state === "todo-list" ? "list" : "board"}
        initialSelectedKey={state === "panel-care" ? PANEL_CARE_KEY : null}
        onOpenConversation={noop}
        onOpenFeedback={noop}
        onOpenFrontOffice={noop}
        onOpenDemand={noop}
      />
    </div>
  );
  return (
    <HrHarnessShell
      client={ready.client}
      title="Ludzie → Sprawy administracja@"
      note="Dane fikcyjne, bez zapytań. „Tablica spraw” ogląda recepcja (uprawnienie „Sprawy”); stany z opieką — opiekunka konsultantów (TCM)."
      states={STATES}
      current={state}
    >
      {state === "detail" ? (
        <CaseDetailView caseId={ONBOARDING_CASE_ID} />
      ) : state === "who" ? (
        <CaseDetailView caseId={WHO_CASE_ID} />
      ) : TODO_STATES.has(state) ? (
        todo
      ) : (
        cases
      )}
    </HrHarnessShell>
  );
}
