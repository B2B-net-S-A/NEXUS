"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, PackageMinus, PackagePlus, Plus } from "lucide-react";

import { EditionLogistics } from "@/components/academy/EditionLogistics";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav, type TabbedNavItem } from "@/components/ds/TabbedNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { HrConfig } from "@/lib/api/hr";
import {
  useEquipmentSummary,
  useEquipmentTasks,
  type EquipmentCategory,
  type EquipmentHolder,
  type EquipmentItem,
} from "@/lib/api/equipment";
import { useUrlSyncedState, useUrlWriter } from "@/lib/url-selection";
import { warsawToday } from "@/lib/warsaw-date";

import { ImportTab } from "./ImportTab";
import { IntuneTab } from "./IntuneTab";
import { IssueWizard } from "./IssueWizard";
import { ItemDetailDialog } from "./ItemDetailDialog";
import { ItemFormDialog } from "./ItemFormDialog";
import { ItemsTab } from "./ItemsTab";
import { PriceListTab } from "./PriceListTab";
import { ProtocolDialog } from "./ProtocolDialog";
import { ProtocolTemplatesTab } from "./ProtocolTemplatesTab";
import { ProtocolsTab } from "./ProtocolsTab";
import { MoveToAccountDialog } from "./MoveToAccountDialog";
import { ReturnWizard } from "./ReturnWizard";
import { StockTiles } from "./StockTiles";
import { TasksTab } from "./TasksTab";
import type { IssueKitKey } from "./equipment-format";

export type EquipmentTab =
  | "items"
  | "tasks"
  | "protocols"
  | "templates"
  | "prices"
  | "import"
  | "intune"
  | "academy";
const TABS: EquipmentTab[] = [
  "items",
  "tasks",
  "protocols",
  "templates",
  "prices",
  "import",
  "intune",
  "academy",
];

/** Rzadkie zakładki — pod „Więcej” (makieta 19.10.2026). */
const MORE_TABS: { value: EquipmentTab; label: string }[] = [
  { value: "templates", label: "Wzory protokołów" },
  { value: "prices", label: "Cennik" },
  { value: "intune", label: "Intune" },
  { value: "academy", label: "Akademia" },
];

interface IssueRequest {
  holder: EquipmentHolder | null;
  items?: EquipmentItem[];
  kit?: IssueKitKey | null;
}

function tabFrom(value: string | null): EquipmentTab | null {
  return TABS.includes(value as EquipmentTab) ? (value as EquipmentTab) : null;
}

const MODULE_OFF =
  "Moduł „Sprzęt” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";
const NO_PERMISSION =
  "Sprzęt prowadzi recepcja: ekran widzą osoby z uprawnieniem „Sprzęt” (Ustawienia → Osoby i role).";

/** „Sprzęt” — rejestr, Do zrobienia, Protokoły, Wzory protokołów, Cennik, Import, Intune (recepcja). */
export function EquipmentScreen({ config }: { config: HrConfig }) {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [tab, setTab] = useUrlSyncedState<EquipmentTab>(tabFrom(searchParams.get("tab")), "items");
  const protocolFromUrl = Number(searchParams.get("protocol")) || null;
  const [protocolId, setProtocolIdState] = useState<number | null>(protocolFromUrl);
  // „Popraw…” z ⋯ listy protokołów otwiera okno protokołu od razu na poprawce.
  const [correctOnOpen, setCorrectOnOpen] = useState(false);
  const setProtocolId = (id: number | null) => {
    setCorrectOnOpen(false);
    setProtocolIdState(id);
  };
  // Dzwonek „protokół podpisany” prowadzi tu miękką nawigacją — bez odmontowania.
  useEffect(() => {
    if (!protocolFromUrl) return;
    setCorrectOnOpen(false);
    setProtocolIdState(protocolFromUrl);
  }, [protocolFromUrl]);
  const [itemId, setItemId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [issuing, setIssuing] = useState<IssueRequest | null>(null);
  const [itemsCategory, setItemsCategory] = useState<EquipmentCategory | "">("");
  const [returning, setReturning] = useState<{ holder: EquipmentHolder | null } | null>(null);
  const [movingPerson, setMovingPerson] = useState<EquipmentHolder | null>(null);
  const allowed = config.me.equipment || config.me.is_admin;
  const moduleOpen = config.open_modules.equipment;
  const summary = useEquipmentSummary(allowed && moduleOpen);
  const openTasks = useEquipmentTasks("otwarte", allowed && moduleOpen);

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
  const today = warsawToday();
  const taskCount = openTasks.data?.length;
  const overdue = (openTasks.data ?? []).filter((task) => task.due_on && task.due_on < today).length;
  const current = tab ?? "items";
  const rare = MORE_TABS.find((entry) => entry.value === current);
  const tabs: TabbedNavItem[] = [
    { value: "items", label: "Sprzęt" },
    {
      value: "tasks",
      label: overdue ? (
        <span className="inline-flex items-center gap-1.5">
          Do zrobienia
          <Badge size="sm" variant="danger" className="tabular-nums">
            {overdue} po terminie
          </Badge>
        </span>
      ) : (
        "Do zrobienia"
      ),
      count: taskCount || undefined,
    },
    { value: "protocols", label: "Protokoły", count: s?.protocols_waiting || undefined },
    { value: "import", label: "Import", count: s?.import_unresolved || undefined },
    ...(rare ? [rare] : []),
  ];

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
      {current === "items" ? (
        s ? (
          <StockTiles
            summary={s}
            category={itemsCategory}
            onCategory={setItemsCategory}
            onOpenProtocols={() => changeTab("protocols")}
            onOpenImport={() => changeTab("import")}
          />
        ) : summary.isError ? (
          <p className="text-xs text-muted-foreground">Liczby chwilowo niedostępne.</p>
        ) : null
      ) : null}
      <div className="flex items-end gap-1">
        <TabbedNav
          ariaLabel="Sekcje sprzętu"
          value={current}
          onValueChange={changeTab}
          className="min-w-0 flex-1"
          tabs={tabs}
        />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="mb-0.5 shrink-0 text-muted-foreground">
              Więcej
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {MORE_TABS.map((entry) => (
              <DropdownMenuItem key={entry.value} onSelect={() => changeTab(entry.value)}>
                {entry.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {tab === "tasks" ? (
        <TasksTab
          onIssue={(holder, kit) => setIssuing({ holder, kit })}
          onReturn={(holder) => setReturning({ holder })}
          onOpenProtocol={setProtocolId}
        />
      ) : tab === "protocols" ? (
        <ProtocolsTab
          onOpenProtocol={setProtocolId}
          onCorrectProtocol={(id) => {
            setProtocolIdState(id);
            setCorrectOnOpen(true);
          }}
        />
      ) : tab === "templates" ? (
        <ProtocolTemplatesTab />
      ) : tab === "prices" ? (
        <PriceListTab />
      ) : tab === "import" ? (
        <ImportTab />
      ) : tab === "intune" ? (
        <IntuneTab isAdmin={config.me.is_admin} onOpenItem={setItemId} />
      ) : tab === "academy" ? (
        // Recepcja bez dostępu do /academy: edycje wszystkich programów.
        <EditionLogistics />
      ) : (
        <ItemsTab
          summary={s}
          category={itemsCategory}
          onCategoryChange={setItemsCategory}
          onOpenItem={setItemId}
          onOpenProtocol={setProtocolId}
          onIssue={(items) => setIssuing({ holder: null, items })}
          onReturn={(holder) => setReturning({ holder })}
          onMoveToAccount={setMovingPerson}
          initialView={searchParams.get("view") === "modele" ? "modele" : "sztuki"}
        />
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
        <ProtocolDialog
          key={`${protocolId}-${correctOnOpen}`}
          protocolId={protocolId}
          startCorrecting={correctOnOpen}
          onClose={() => setProtocolId(null)}
        />
      ) : null}
      {issuing ? (
        <IssueWizard
          presetHolder={issuing.holder}
          presetItems={issuing.items}
          suggestedKit={issuing.kit ?? null}
          onClose={() => setIssuing(null)}
        />
      ) : null}
      {returning ? (
        <ReturnWizard presetHolder={returning.holder} onClose={() => setReturning(null)} />
      ) : null}
      {movingPerson ? (
        <MoveToAccountDialog
          key={movingPerson.id}
          person={movingPerson}
          onClose={() => setMovingPerson(null)}
        />
      ) : null}
    </div>
  );
}
