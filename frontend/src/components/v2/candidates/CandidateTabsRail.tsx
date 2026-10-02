"use client";

import { useRouter, usePathname } from "next/navigation";
import { User } from "lucide-react";

import {
  OpenTabsRail,
  useMinViewportWidth,
  useRailCollapsed,
  type OpenTabsRailLabels,
} from "@/components/v2/shell/OpenTabsRail";
import { useTabsStore } from "@/store/tabs";

const COLLAPSE_KEY = "nexus.candidateTabsRail.collapsed";

/** Bez zapisanego wyboru szyna jest rozwinięta od tej szerokości okna. */
const EXPANDED_MIN_WIDTH = 1600;

const LABELS: OpenTabsRailLabels = {
  title: "Kandydaci",
  count: "Ostatnio wyświetlani",
  region: "Ostatnio wyświetlani kandydaci",
  collapsedRegion: "Ostatnio wyświetlani kandydaci (zwinięte)",
  show: "Pokaż pasek kandydatów",
  showTitle: "Pokaż kandydatów",
  hide: "Ukryj pasek kandydatów",
};

/**
 * CandidateTabsRail — lista ostatnio otwieranych kandydatów po lewej stronie
 * listy i profilu, odpowiednik szyny „Rekrutacje” (`JobTabsRail`). Karty
 * pochodzą ze wspólnego store'u (zapisywanego w `localStorage`), więc szyna
 * zbiera każdego otwartego kandydata i przeżywa odświeżenie.
 *
 * Renderowana z `app/candidates/layout.tsx`. Od 1536 px stoi w układzie strony
 * (zapamiętany wybór, a bez niego rozwinięta od 1600 px); na laptopie —
 * od 02.10.2026 — jest zakładką w lewym marginesie strony, z której lista
 * kandydatów wysuwa się nad treść. Bez otwartych kart nie renderuje nic.
 */
export function CandidateTabsRail({ className }: { className?: string }) {
  const router = useRouter();
  const pathname = usePathname();

  const roomy = useMinViewportWidth(EXPANDED_MIN_WIDTH, false);
  const [collapsed, toggleCollapsed] = useRailCollapsed(COLLAPSE_KEY, !roomy);

  const tabs = useTabsStore((s) => s.tabs);
  const closeTab = useTabsStore((s) => s.closeTab);
  const closeTabsByType = useTabsStore((s) => s.closeTabsByType);
  const activateTab = useTabsStore((s) => s.activateTab);

  const match = pathname?.match(/^\/candidates\/(\d+)/);

  return (
    <OpenTabsRail
      tabs={tabs.filter((t) => t.type === "candidate")}
      currentId={match ? Number(match[1]) : null}
      icon={User}
      labels={LABELS}
      collapsed={collapsed}
      onToggleCollapsed={toggleCollapsed}
      onOpen={(tab) => {
        activateTab(tab.id);
        router.push(tab.url);
      }}
      onClose={(tab) => closeTab(tab.id)}
      onCloseAll={() => closeTabsByType("candidate")}
      routeKey={pathname}
      // Laptop: zakładka w marginesie strony — lista kandydatów przy 1280 px
      // i tak przewija się w poziomie, więc pasek 40 px zabierałby jej kolumny.
      narrow="gutter"
      className={className}
    />
  );
}
