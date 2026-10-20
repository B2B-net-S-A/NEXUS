"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { TabbedNav } from "@/components/ds/TabbedNav";
import { B2BRegisterImportPanel } from "@/components/settings/B2BRegisterImportPanel";
import { ContractDocsSharePointPanel } from "@/components/settings/ContractDocsSharePointPanel";
import { TraffitSyncCard } from "@/components/settings/TraffitSyncCard";
import { useUrlWriter } from "@/lib/url-selection";

export type ImportsTab = "excel" | "sharepoint" | "traffit";

const TABS: { value: ImportsTab; label: string }[] = [
  { value: "excel", label: "Rejestr umów z Excela" },
  { value: "sharepoint", label: "Dokumenty z SharePointa" },
  { value: "traffit", label: "Traffit (archiwum)" },
];

export const IMPORTS_TAB_PARAM = "zakladka";

/**
 * Ustawienia → System → Importy (20.10.2026, decyzja Artura): importy admina
 * w jednym miejscu zamiast trzech obszarów. Panele bez zmian w środku; stare
 * adresy (`/settings/b2b-register-import`, `/settings/contract-docs-sharepoint`,
 * `?item=traffit`) dalej prowadzą do tych samych paneli.
 */
export function ImportsSettings() {
  const searchParams = useSearchParams();
  const pathname = usePathname() ?? "/settings";
  const { replaceUrl } = useUrlWriter();
  const requested = searchParams?.get(IMPORTS_TAB_PARAM);
  const tab: ImportsTab = TABS.some((t) => t.value === requested)
    ? (requested as ImportsTab)
    : "excel";

  const select = (next: string) => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set(IMPORTS_TAB_PARAM, next);
    replaceUrl(`${pathname}?${params.toString()}`);
  };

  return (
    <div className="space-y-4">
      <TabbedNav tabs={TABS} value={tab} onValueChange={select} ariaLabel="Importy" />
      {tab === "excel" ? <B2BRegisterImportPanel /> : null}
      {tab === "sharepoint" ? <ContractDocsSharePointPanel /> : null}
      {tab === "traffit" ? <TraffitSyncCard /> : null}
    </div>
  );
}

export default ImportsSettings;
