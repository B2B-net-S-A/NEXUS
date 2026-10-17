"use client";

/**
 * Harness „Struktura u klienta” (makieta 6 etapu 2 „Ludzi w NEXUSIE”).
 *
 * W aplikacji to zakładka „Struktura u klienta” profilu klienta
 * (`/clients/[id]?tab=struktura`). Harness pokazuje prosty nagłówek klienta
 * i pod nim prawdziwy `ClientPeopleTab` na zasianym cache, ZERO zapytań
 * (`hr-harness.tsx`). Ogląda Delivery Lead klienta (edytuje strukturę
 * i zapisuje opinie).
 *
 * Jeden stan: dwa działy i „Bez działu”, Head of Data pod CTO z trzema
 * konsultantami i prośbą o opinię, menedżerka płatności bez opinii,
 * konsultant bez wskazanego menedżera z podpowiedzią z pola „Line Manager”.
 * Wybór osoby otwiera panel, „Zapisz opinię” — okno bez zapytań (zapis
 * odcina interceptor harnessu).
 */

import { ClientPeopleTab } from "@/components/care/ClientPeopleTab";
import { clientPeopleKeys } from "@/lib/api/client-people";
import { warsawToday } from "@/lib/warsaw-date";

import { HR_CAST, HR_CONFIG_QUERY_KEY, hrConfig } from "../hr-fixtures";
import { HrHarnessLoading, HrHarnessShell, harnessQueryClient, useHrHarness } from "../hr-harness";
import { ORG_CLIENT, clientOrg } from "./fixtures";

const STATES = [{ key: "org", label: "Struktura (Delivery Lead klienta)" }] as const;

function prepare() {
  const org = clientOrg(warsawToday());
  const client = harnessQueryClient();
  client.setQueryData(HR_CONFIG_QUERY_KEY, hrConfig());
  client.setQueryData(clientPeopleKeys.org(ORG_CLIENT.id), org);
  return {
    user: HR_CAST.kamil,
    client,
    value: { people: org.people_count, consultants: org.consultants_count },
  };
}

/** Uproszczony nagłówek profilu klienta — tylko kontekst dla zakładki. */
function ClientHeader({ people, consultants }: { people: number; consultants: number }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-5">
        <span className="text-xs text-muted-foreground">Klienci</span>
        <span aria-hidden="true" className="text-xs text-muted-foreground">
          /
        </span>
        <h2 className="font-display text-lg font-semibold text-foreground">{ORG_CLIENT.name}</h2>
        <span className="text-xs text-muted-foreground">
          {people} osób klienta · {consultants} naszych konsultantów
        </span>
      </div>
      <div className="border-t border-border px-3 text-[13px] sm:px-5">
        <span className="inline-block border-b-2 border-primary px-3 py-2 font-semibold text-foreground">
          Struktura u klienta
        </span>
      </div>
    </div>
  );
}

export default function HrClientPeoplePreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Struktura u klienta"
      note="Dane fikcyjne, bez zapytań. Ogląda Delivery Lead klienta; działy, osoby klienta, nasi konsultanci pod menedżerem i prośby o opinię."
      states={STATES}
      current="org"
    >
      <div className="space-y-4">
        <ClientHeader {...ready.value} />
        <ClientPeopleTab clientId={ORG_CLIENT.id} />
      </div>
    </HrHarnessShell>
  );
}
