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
 * - `list` — ekran `/care` („Moi konsultanci”, „Do przepięcia”,
 *   „Technologie do przejrzenia”); zakładkę wybiera sam ekran z `?tab=`,
 *   obie kolejki i oba zakresy listy są zasiane.
 */

import { Suspense, useState } from "react";

import { CareScreen } from "@/components/care/CareScreen";
import { ContractCareTab } from "@/components/care/ContractCareTab";
import { TechCardDialog } from "@/components/care/TechCardDialog";
import { careKeys } from "@/lib/api/care";
import { formatDate } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST, HR_CONFIG_QUERY_KEY, HR_CONSULTANTS, hrConfig } from "../hr-fixtures";
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
  myConsultants,
  redeployQueue,
  skillReview,
} from "./fixtures";

const KNOWN = ["tab", "techcard", "list"] as const;
type State = (typeof KNOWN)[number];

const STATES = [
  { key: "tab", label: "Zakładka „Opieka”" },
  { key: "techcard", label: "Karta technologiczna" },
  { key: "list", label: "Moi konsultanci (/care)" },
] as const;

function prepare(params: URLSearchParams) {
  const state = pickState(params.get("state"), KNOWN, "tab");
  const today = warsawToday();
  const client = harnessQueryClient();
  client.setQueryData(HR_CONFIG_QUERY_KEY, hrConfig());
  client.setQueryData(careKeys.contract(CARE_CONTRACT_ID), contractCare(today));
  client.setQueryData(careKeys.owners, CARE_OWNERS);
  client.setQueryData(careKeys.clientAreas(CARE_CLIENT.id), CLIENT_AREAS);
  client.setQueryData(careKeys.summary, CARE_SUMMARY);
  for (const scope of ["mine", "all"] as const) {
    client.setQueryData(careKeys.myConsultants(scope), myConsultants(today, scope));
  }
  for (const queue of ["active", "closed"] as const) {
    client.setQueryData(careKeys.redeploy(queue), redeployQueue(today, queue));
  }
  for (const review of ["open", "closed"] as const) {
    client.setQueryData(careKeys.skillReview(review), skillReview(today, review));
  }
  return { user: HR_CAST.natalia, client, value: { state, today } };
}

/** Uproszczony nagłówek strony kontraktu — tylko kontekst dla zakładki. */
function ContractHeader({ start }: { start: string }) {
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          Kontrakty · B2B · aktywny od {formatDate(start)}
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

function body(state: State, today: string) {
  if (state === "list") {
    return (
      <Suspense fallback={<HrHarnessLoading />}>
        <CareScreen />
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
