"use client";

/**
 * Harness „Technologie klienta” (makieta 10 raportu „Ludzie w NEXUSIE”).
 *
 * W aplikacji to zakładka „Technologie” profilu klienta
 * (`/clients/[id]?tab=technologie`). Harness nie montuje całej strony klienta —
 * pokazuje prosty nagłówek klienta i pod nim prawdziwy `ClientTechnologiesTab`
 * na zasianym cache, ZERO zapytań (`hr-harness.tsx`). Ogląda Delivery Lead
 * klienta (może dodać notatkę o stacku i zmienić domyślnego opiekuna).
 *
 * Jeden stan: mapa z czterech źródeł (T rozmowy, R rekrutacje, K nasi
 * konsultanci, N notatki) — 7 technologii w trzech obszarach, „Klient zatrudnia”
 * z karty technologicznej, „Do przepięcia” = 2, trzy otwarte rekrutacje,
 * dostawcy i domyślny opiekun. Filtr obszaru działa w przeglądarce, „Dodaj
 * notatkę o stacku” otwiera okno bez zapytań, lista opiekunów jest zasiana.
 */

import { ClientTechnologiesTab } from "@/components/care/ClientTechnologiesTab";
import { careKeys } from "@/lib/api/care";
import { warsawToday } from "@/lib/warsaw-date";
import { hrKeys } from "@/lib/api/hr";

import { HR_CAST, hrConfig } from "../hr-fixtures";
import { HrHarnessLoading, HrHarnessShell, harnessQueryClient, useHrHarness } from "../hr-harness";
import { CARE_OWNERS, MAP_CLIENT, clientTechMap } from "./fixtures";

const STATES = [{ key: "map", label: "Mapa (Delivery Lead klienta)" }] as const;

function prepare() {
  const map = clientTechMap(warsawToday());
  const client = harnessQueryClient();
  client.setQueryData(hrKeys.config, hrConfig());
  client.setQueryData(careKeys.clientMap(MAP_CLIENT.id), map);
  client.setQueryData(careKeys.owners, CARE_OWNERS);
  return {
    user: HR_CAST.kamil,
    client,
    value: { consultants: map.consultants_count, openJobs: map.open_jobs_count },
  };
}

/** Uproszczony nagłówek profilu klienta — tylko kontekst dla zakładki. */
function ClientHeader({ consultants, openJobs }: { consultants: number; openJobs: number }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-5">
        <span className="text-xs text-muted-foreground">Klienci</span>
        <span aria-hidden="true" className="text-xs text-muted-foreground">
          /
        </span>
        <h2 className="font-display text-lg font-semibold text-foreground">{MAP_CLIENT.name}</h2>
        <span className="text-xs text-muted-foreground">
          {consultants} konsultantów u klienta · {openJobs} otwarte rekrutacje
        </span>
      </div>
      <div className="border-t border-border px-3 text-[13px] sm:px-5">
        <span className="inline-block border-b-2 border-primary px-3 py-2 font-semibold text-foreground">
          Technologie
        </span>
      </div>
    </div>
  );
}

export default function HrClientTechPreviewPage() {
  const ready = useHrHarness(prepare);
  if (!ready) return <HrHarnessLoading />;
  return (
    <HrHarnessShell
      client={ready.client}
      title="Technologie klienta"
      note="Dane fikcyjne, bez zapytań. Ogląda Delivery Lead klienta; liczby źródeł to karty, rekrutacje, konsultanci i notatki z technologią."
      states={STATES}
      current="map"
    >
      <div className="space-y-4">
        <ClientHeader {...ready.value} />
        <ClientTechnologiesTab clientId={MAP_CLIENT.id} />
      </div>
    </HrHarnessShell>
  );
}
