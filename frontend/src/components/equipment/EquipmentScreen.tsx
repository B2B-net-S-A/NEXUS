"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PackageMinus, PackagePlus, Plus } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { Button } from "@/components/ui/button";
import type { HrConfig } from "@/lib/api/hr";
import { useEquipmentSummary, type EquipmentHolder } from "@/lib/api/equipment";
import { useUrlSyncedState, useUrlWriter } from "@/lib/url-selection";

import { ImportTab } from "./ImportTab";
import { IssueWizard } from "./IssueWizard";
import { ItemDetailDialog } from "./ItemDetailDialog";
import { ItemFormDialog } from "./ItemFormDialog";
import { ItemsTab } from "./ItemsTab";
import { PriceListTab } from "./PriceListTab";
import { ProtocolDialog } from "./ProtocolDialog";
import { ProtocolsTab } from "./ProtocolsTab";
import { ReturnWizard } from "./ReturnWizard";
import { TasksTab } from "./TasksTab";

export type EquipmentTab = "items" | "tasks" | "protocols" | "prices" | "import";
const TABS: EquipmentTab[] = ["items", "tasks", "protocols", "prices", "import"];

function tabFrom(value: string | null): EquipmentTab | null {
  return TABS.includes(value as EquipmentTab) ? (value as EquipmentTab) : null;
}

const MODULE_OFF =
  "Moduł „Sprzęt” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";
const NO_PERMISSION =
  "Sprzęt prowadzi recepcja: ekran widzą osoby z uprawnieniem „Sprzęt” (Ustawienia → Osoby i role).";

/** „Sprzęt” — rejestr, Do zrobienia, Protokoły, Cennik, Import (recepcja). */
export function EquipmentScreen({ config }: { config: HrConfig }) {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [tab, setTab] = useUrlSyncedState<EquipmentTab>(tabFrom(searchParams.get("tab")), "items");
  const protocolFromUrl = Number(searchParams.get("protocol")) || null;
  const [protocolId, setProtocolId] = useState<number | null>(protocolFromUrl);
  // Dzwonek „protokół podpisany” prowadzi tu miękką nawigacją — bez odmontowania.
  useEffect(() => {
    if (protocolFromUrl) setProtocolId(protocolFromUrl);
  }, [protocolFromUrl]);
  const [itemId, setItemId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [issuing, setIssuing] = useState<{ holder: EquipmentHolder | null } | null>(null);
  const [returning, setReturning] = useState<{ holder: EquipmentHolder | null } | null>(null);
  const allowed = config.me.equipment || config.me.is_admin;
  const moduleOpen = config.open_modules.equipment;
  const summary = useEquipmentSummary(allowed && moduleOpen);

  if (!moduleOpen) {
    return <QueryStateNotice state="not_found" description={MODULE_OFF} />;
  }
  if (!allowed) {
    return <QueryStateNotice state="forbidden" description={NO_PERMISSION} />;
  }

  const changeTab = (value: string) => {
    const next = tabFrom(value) ?? "items";
    setTab(next);
    const params = new URLSearchParams(window.location.search);
    params.set("tab", next);
    params.delete("protocol");
    replaceUrl(`?${params.toString()}`);
  };
  const s = summary.data;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Sprzęt"
        description="Ewidencja egzemplarzy, wydania i zwroty z protokołem recepcji."
        density="compact"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              Dodaj pozycję
            </Button>
            <Button variant="outline" onClick={() => setReturning({ holder: null })}>
              <PackageMinus className="h-4 w-4" aria-hidden />
              Przyjmij zwrot
            </Button>
            <Button onClick={() => setIssuing({ holder: null })}>
              <PackagePlus className="h-4 w-4" aria-hidden />
              Wydaj sprzęt
            </Button>
          </div>
        }
      />
      {s ? (
        <InlineStats
          stats={[
            { id: "laptops", label: "wolnych laptopów", value: s.free_by_category.laptop },
            { id: "phones", label: "wolnych telefonów", value: s.free_by_category.telefon },
            { id: "monitors", label: "wolnych monitorów", value: s.free_by_category.monitor },
            { id: "sims", label: "wolnych kart SIM", value: s.free_by_category.karta_sim },
            { id: "service", label: "w serwisie", value: s.by_status.serwis },
            { id: "waiting", label: "czeka na podpis", value: s.protocols_waiting },
            {
              id: "unresolved",
              label: "do wyjaśnienia (z importu)",
              value: s.import_unresolved,
            },
          ]}
        />
      ) : summary.isError ? (
        <p className="text-xs text-muted-foreground">Liczby chwilowo niedostępne.</p>
      ) : null}
      <TabbedNav
        ariaLabel="Sekcje sprzętu"
        value={tab ?? "items"}
        onValueChange={changeTab}
        tabs={[
          { value: "items", label: "Sprzęt" },
          { value: "tasks", label: "Do zrobienia" },
          { value: "protocols", label: "Protokoły", count: s?.protocols_waiting || undefined },
          { value: "prices", label: "Cennik" },
          { value: "import", label: "Import" },
        ]}
      />
      {tab === "tasks" ? (
        <TasksTab
          onIssue={(holder) => setIssuing({ holder })}
          onReturn={(holder) => setReturning({ holder })}
          onOpenProtocol={setProtocolId}
        />
      ) : tab === "protocols" ? (
        <ProtocolsTab onOpenProtocol={setProtocolId} />
      ) : tab === "prices" ? (
        <PriceListTab />
      ) : tab === "import" ? (
        <ImportTab />
      ) : (
        <ItemsTab onOpenItem={setItemId} />
      )}

      {adding ? <ItemFormDialog open onOpenChange={setAdding} /> : null}
      {itemId ? (
        <ItemDetailDialog
          key={itemId}
          itemId={itemId}
          onClose={() => setItemId(null)}
          onOpenProtocol={(id) => {
            setItemId(null);
            setProtocolId(id);
          }}
        />
      ) : null}
      {protocolId ? (
        <ProtocolDialog key={protocolId} protocolId={protocolId} onClose={() => setProtocolId(null)} />
      ) : null}
      {issuing ? (
        <IssueWizard presetHolder={issuing.holder} onClose={() => setIssuing(null)} />
      ) : null}
      {returning ? (
        <ReturnWizard presetHolder={returning.holder} onClose={() => setReturning(null)} />
      ) : null}
    </div>
  );
}
