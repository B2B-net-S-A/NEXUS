"use client";

/**
 * Harness „Opieka nad konsultantem” (makieta 9 raportu „Ludzie w NEXUSIE”).
 *
 * W aplikacji to zakładka „Opieka” na kontrakcie (`/contracts/[id]?tab=care`).
 * Harness nie montuje całej strony kontraktu — pokazuje prosty nagłówek
 * kontraktu i pod nim prawdziwy `ContractCareTab` na zasianym cache, ZERO
 * zapytań (`hr-harness.tsx`). Ogląda Talent Community Manager (opiekunka).
 * Kontrakt jest zawsze w 45. dniu współpracy — daty liczymy od „dziś”
 * przeglądarki (`fixtures.ts`).
 *
 * Stany (`?state=`):
 * - `tab` (domyślnie) — opiekun, dzień 45, zadowolenie 4/5, plan 7/30/90
 *   (dwa zrobione, „Dzień 90” otwarty), sygnały (koniec projektu, klient
 *   zatrudnia), oś opieki z kartą technologiczną i dwiema rozmowami;
 *   „Zapisz rozmowę” i „Karta technologiczna” otwierają okna bez zapytań;
 * - `techcard` — otwarte okno karty technologicznej z 31. dnia (prawdziwy
 *   `TechCardDialog`, ten sam, który otwiera „Edytuj” na osi — zakładka nie
 *   umie otworzyć go bez kliknięcia); obszary klienta są zasiane;
 * - `list` — ekran `/care`: domyślnie „Ten tydzień” (makieta 7 etapu 2 —
 *   prośby o opinię od menedżerów, rozmowy z powodem, licznik zaległych),
 *   dalej „Konsultanci” (etap 3, M1 — rytm przy każdej osobie, sygnały),
 *   „Przydział” (M3 — obciążenie opiekunów z rytmów, próg, bez opiekuna),
 *   „Do przepięcia”, „Technologie”; zakładkę wybiera sam ekran z `?tab=`,
 *   listy i kolejki są zasiane („Komunikaty” mają własny harness
 *   `/preview/hr-announcements`). `&contract=4504` otwiera oś Pawła
 *   z „Przekaż do front office” (dwie pasujące rekrutacje); osie i „front
 *   office” pozostałych osób z tygodnia też są zasiane, a okno rozmowy ma
 *   pytania z mapy technologii klienta;
 * - `cadence` — „Konsultanci” z otwartym oknem „Rytm kontaktu” Bartosza
 *   (M2: słaba opinia menedżera, podgląd „co 2 tygodnie” zasiany).
 */

import { Suspense, useState } from "react";

import { CadenceDialog } from "@/components/care/CadenceDialog";
import { CareScreen } from "@/components/care/CareScreen";
import { ContractCareTab } from "@/components/care/ContractCareTab";
import { TechCardDialog } from "@/components/care/TechCardDialog";
import { careKeys } from "@/lib/api/care";
import { warsawToday } from "@/lib/warsaw-date";
import { hrKeys } from "@/lib/api/hr";
import { formatIsoDatePl } from "@/lib/date-pl";

import { clientTechMap } from "../hr-client-tech/fixtures";
import {
  HR_CAST,
  HR_CLIENTS,
  HR_CONSULTANTS,
  hrConfig,
} from "../hr-fixtures";
import {
  HrHarnessLoading,
  HrHarnessShell,
  harnessQueryClient,
  pickState,
  useHrHarness,
} from "../hr-harness";
import {
  CARE_CLIENT,
  CARE_CONTRACT_ID,
  CARE_OWNERS,
  CARE_SUMMARY,
  CLIENT_AREAS,
  careTechCard,
  contractCare,
  contractStart,
  redeployQueue,
  skillReview,
} from "./fixtures";
import {
  BARTOSZ_CONTRACT,
  bartoszCadence,
  bartoszCadencePreview,
  careAssignment,
  careConsultants,
  michalCadence,
} from "./rhythm-fixtures";
import {
  WEEK_HANDOFF_CONTRACT,
  careWeek,
  karolinaFrontOffice,
  pawelFrontOffice,
  pawelTimeline,
  shortTimeline,
  telecomTechMap,
} from "./week-fixtures";

const KNOWN = ["tab", "techcard", "list", "cadence"] as const;
type State = (typeof KNOWN)[number];

const STATES = [
  { key: "tab", label: "Zakładka „Opieka”" },
  { key: "techcard", label: "Karta technologiczna" },
  { key: "list", label: "Ten tydzień (/care)" },
  {
    key: "panel",
    label: "Oś konsultanta i front office",
    href: `?state=list&contract=${WEEK_HANDOFF_CONTRACT}`,
  },
  { key: "consultants", label: "Konsultanci (rytm)", href: "?state=list&tab=consultants" },
  { key: "cadence", label: "Zmiana rytmu", href: "?state=cadence&tab=consultants" },
  { key: "assignment", label: "Przydział opiekunów", href: "?state=list&tab=assignment" },
] as const;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), KNOWN, "tab");
  const today = warsawToday();
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, hrConfig());
  client.setQueryData(careKeys.contract(CARE_CONTRACT_ID), contractCare(today));
  client.setQueryData(careKeys.owners, CARE_OWNERS);
  client.setQueryData(careKeys.clientAreas(CARE_CLIENT.id), CLIENT_AREAS);
  client.setQueryData(careKeys.summary, CARE_SUMMARY);
  client.setQueryData(careKeys.consultants, careConsultants(today));
  client.setQueryData(careKeys.assignment, careAssignment(today));
  client.setQueryData(careKeys.cadence(BARTOSZ_CONTRACT), bartoszCadence(today));
  client.setQueryData(careKeys.cadence(BARTOSZ_CONTRACT, "biweekly"), bartoszCadencePreview(today));
  client.setQueryData(careKeys.cadence(CARE_CONTRACT_ID), michalCadence(today));
  for (const queue of ["active", "closed"] as const) {
    client.setQueryData(careKeys.redeploy(queue), redeployQueue(today, queue));
  }
  for (const review of ["open", "closed"] as const) {
    client.setQueryData(careKeys.skillReview(review), skillReview(today, review));
  }
  // „Ten tydzień”: obie listy, osie każdej osoby, „front office” i mapa klienta
  // (pytania w oknie rozmowy).
  for (const scope of ["mine", "all"] as const) {
    client.setQueryData(careKeys.week(scope, null), careWeek(today, scope));
  }
  for (const row of careWeek(today, "all").contacts) {
    client.setQueryData(careKeys.timeline(row.contract_id), shortTimeline(today, row));
  }
  client.setQueryData(careKeys.timeline(WEEK_HANDOFF_CONTRACT), pawelTimeline(today));
  client.setQueryData(careKeys.frontOffice(WEEK_HANDOFF_CONTRACT), pawelFrontOffice(today));
  client.setQueryData(careKeys.frontOffice(4502), karolinaFrontOffice(today));
  client.setQueryData(careKeys.clientMap(CARE_CLIENT.id), clientTechMap(today));
  client.setQueryData(careKeys.clientMap(HR_CLIENTS.telecom.id), telecomTechMap(today));
  return { user: HR_CAST.natalia, client, value: { state, today } };
}

/** Uproszczony nagłówek strony kontraktu — tylko kontekst dla zakładki. */
function ContractHeader({ start }: { start: string }) {
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          Kontrakty · B2B · aktywny od {formatIsoDatePl(start)}
        </p>
        <h2 className="text-xl font-semibold text-foreground">{HR_CONSULTANTS.michal.name}</h2>
        <p className="text-sm text-muted-foreground">Java Developer @ {CARE_CLIENT.name}</p>
      </div>
      <div className="border-b border-border text-[13px]">
        <span className="inline-block border-b-2 border-primary px-3 py-2 font-semibold text-foreground">
          Opieka
        </span>
      </div>
    </div>
  );
}

function OpenTechCard({ today }: { today: string }) {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return (
    <TechCardDialog
      contractId={CARE_CONTRACT_ID}
      clientId={CARE_CLIENT.id}
      card={careTechCard(today)}
      open
      onOpenChange={setOpen}
    />
  );
}

function OpenCadence() {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return <CadenceDialog contractId={BARTOSZ_CONTRACT} open onOpenChange={setOpen} />;
}

function body(state: State, today: string) {
  if (state === "list" || state === "cadence") {
    return (
      <Suspense fallback={<HrHarnessLoading />}>
        <CareScreen />
        {state === "cadence" ? <OpenCadence /> : null}
      </Suspense>
    );
  }
  return (
    <div className="space-y-4">
      <ContractHeader start={contractStart(today)} />
      <ContractCareTab contractId={CARE_CONTRACT_ID} />
      {state === "techcard" ? <OpenTechCard today={today} /> : null}
    </div>
  );
}

export default function HrCarePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  const { state, today } = ready.value;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Opieka nad konsultantem"
      note="Dane fikcyjne, bez zapytań. Ogląda opiekunka (Talent Community Manager); plan kontaktów liczy się od startu kontraktu."
      states={STATES}
      current={state}
    >
      {body(state, today)}
    </HrHarnessShell>
  );
}
