"use client";

import { useRouter, usePathname } from "next/navigation";
import { FileText } from "lucide-react";

import {
  LIST_RAIL_GAP_CLASS,
  OpenTabsRail,
  useMinViewportWidth,
  useRailCollapsed,
  type OpenTabsRailLabels,
} from "@/components/v2/shell/OpenTabsRail";
import {
  JOB_TABS_RAIL_COLLAPSED_DEFAULT,
  JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY,
} from "@/lib/job-tabs-rail-preferences";
import { useTabsStore, type Tab } from "@/store/tabs";

const LABELS: OpenTabsRailLabels = {
  title: "Rekrutacje",
  count: "Otwarte karty",
  region: "Otwarte rekrutacje",
  collapsedRegion: "Otwarte rekrutacje (zwinięte)",
  show: "Pokaż pasek rekrutacji",
  showTitle: "Pokaż rekrutacje",
  hide: "Ukryj pasek rekrutacji",
};

/**
 * Od tej szerokości okna lista rekrutacji ma obok siebie miejsce na
 * rozwiniętą szynę (240 px) — przy 1920 px z przypiętym menu zostaje jej
 * ~1370 px. Węziej szyna zabierałaby tabeli kolumny, więc startuje zwinięta.
 */
const LIST_EXPANDED_MIN_WIDTH = 1920;

/** Odstęp szyna–lista na `/jobs` (układ strony i harness listy czytają tę samą stałą). */
export const JOBS_LIST_RAIL_GAP_CLASS = LIST_RAIL_GAP_CLASS;

/** Gdzie stoi szyna: na stronie rekrutacji czy na liście `/jobs`. */
export type JobTabsRailVariant = "detail" | "list";

export interface JobTabsRailViewProps {
  tabs: readonly Tab[];
  currentId: number | null;
  onOpen: (tab: Tab) => void;
  onClose: (tab: Tab) => void;
  onCloseAll: () => void;
  variant?: JobTabsRailVariant;
  routeKey?: string | null;
  /** Klucz zapamiętanego stanu; harness podaje własny, żeby nie ruszać preferencji. */
  storageKey?: string;
  className?: string;
}

/**
 * Szyna rekrutacji bez źródła danych — karty i akcje podaje wołający
 * (`JobTabsRail` ze store'u, harness listy z danych fikcyjnych).
 *
 * Stan bez zapisanej preferencji zależy od strony: na stronie rekrutacji
 * szyna jest zwinięta (edytor Championa i Tablica potrzebują szerokości),
 * na liście — rozwinięta od 1920 px okna. Kliknięcie „Pokaż” albo „Ukryj”
 * zapisuje wybór, wspólny dla obu stron, i odtąd to on obowiązuje.
 */
export function JobTabsRailView({
  tabs,
  currentId,
  onOpen,
  onClose,
  onCloseAll,
  variant = "detail",
  routeKey,
  storageKey = JOB_TABS_RAIL_COLLAPSED_STORAGE_KEY,
  className,
}: JobTabsRailViewProps) {
  const roomForList = useMinViewportWidth(LIST_EXPANDED_MIN_WIDTH, false);
  const [collapsed, toggleCollapsed] = useRailCollapsed(
    storageKey,
    variant === "list" ? !roomForList : JOB_TABS_RAIL_COLLAPSED_DEFAULT,
  );
  return (
    <OpenTabsRail
      tabs={tabs}
      currentId={currentId}
      icon={FileText}
      labels={LABELS}
      collapsed={collapsed}
      onToggleCollapsed={toggleCollapsed}
      onOpen={onOpen}
      onClose={onClose}
      onCloseAll={onCloseAll}
      routeKey={routeKey}
      // Lista na laptopie: zakładka w marginesie zamiast paska 40 px — tabela
      // rekrutacji nie traci szerokości. Strona rekrutacji zostaje przy pasku.
      narrow={variant === "list" ? "gutter" : "strip"}
      className={className}
    />
  );
}

/**
 * JobTabsRail — lista otwartych rekrutacji po lewej stronie (jak „Otwarte
 * karty” w Traffit). Karty pochodzą ze wspólnego store'u (zapisywanego
 * w `localStorage`), więc szyna zbiera każdą otwartą rekrutację i przeżywa
 * odświeżenie. Klik w wiersz przełącza rekrutację, „×” przy wierszu zamyka
 * jedną kartę, „×” w nagłówku — wszystkie.
 *
 * Renderowana z `app/jobs/layout.tsx`: na stronach rekrutacji i — od
 * 02.10.2026 — na liście `/jobs`. Bez otwartych kart nie renderuje nic.
 */
export function JobTabsRail({
  className,
  variant = "detail",
}: {
  className?: string;
  variant?: JobTabsRailVariant;
}) {
  const router = useRouter();
  const pathname = usePathname();

  const tabs = useTabsStore((s) => s.tabs);
  const closeTab = useTabsStore((s) => s.closeTab);
  const closeTabsByType = useTabsStore((s) => s.closeTabsByType);
  const activateTab = useTabsStore((s) => s.activateTab);

  const match = pathname?.match(/^\/jobs\/(\d+)/);

  return (
    <JobTabsRailView
      tabs={tabs.filter((t) => t.type === "job")}
      currentId={match ? Number(match[1]) : null}
      onOpen={(tab) => {
        activateTab(tab.id);
        router.push(tab.url);
      }}
      onClose={(tab) => closeTab(tab.id)}
      onCloseAll={() => closeTabsByType("job")}
      variant={variant}
      routeKey={pathname}
      className={className}
    />
  );
}
