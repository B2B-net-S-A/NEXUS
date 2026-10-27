"use client";

import { useEffect, useState } from "react";
import { Menu, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { BreadcrumbV2 } from "./BreadcrumbV2";
import { QuickActionsV2, type QuickActionModal } from "./QuickActionsV2";
import { CommandPaletteV2 } from "./CommandPaletteV2";
import { MyKpiWidget } from "@/components/v2/kpi/MyKpiWidget";
import { MyLeagueWidget } from "@/components/v2/league/MyLeagueWidget";
import { AppearanceMenu } from "./AppearanceMenu";
import { MyPeopleTopbarButton } from "@/components/v2/my-people/MyPeopleLauncher";
import { ChatNotificationsDropdown } from "./ChatNotificationsDropdown";
import { CvNotificationsDropdown } from "./CvNotificationsDropdown";
import { JobsNotificationsDropdown } from "./JobsNotificationsDropdown";
import { ContractsNotificationsDropdown } from "./ContractsNotificationsDropdown";
import { AbsentTodayButton } from "@/components/hr/leave/AbsentTodayButton";
import { ConsentsTopbarButton } from "@/components/hr/approvals/ConsentsTopbarButton";
import { InterviewNotificationsDropdown } from "./InterviewNotificationsDropdown";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";
import {
  TOPBAR_ACTIONS_CLASS,
  TOPBAR_BREADCRUMB_CLASS,
  TOPBAR_HEADER_CLASS,
  TOPBAR_SEARCH_CLASS,
} from "./topbar-layout";
import { P0TopbarButton } from "@/components/v2/jobs/p0/P0TopbarButton";

interface Props {
  onOpenMobileSidebar: () => void;
  pendingModal: QuickActionModal;
  onClearPendingModal: () => void;
  onOpenCommandPalette: () => void;
}

export function TopbarV2({
  onOpenMobileSidebar,
  pendingModal,
  onClearPendingModal,
  onOpenCommandPalette,
}: Props) {
  const [isMac, setIsMac] = useState(false);
  // „Pracownik” (0456) i inne konta bez sekcji pracy nie przeszukują kandydatów,
  // rekrutacji ani klientów — paleta służy im tylko do przejścia na ekran.
  // Przed odczytem konta (`user === null` do `hydrate()`) zostaje podpowiedź
  // większości, inaczej pole na chwilę mówi „Przejdź do ekranu…” każdemu.
  const user = useAuthStore((state) => state.user);
  const searchesWork =
    user === null ||
    (["sourcing", "pipeline", "delivery"] as const).some((section) =>
      hasSectionAccess(user, section),
    );

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setIsMac(/Mac|iPhone|iPad|iPod/.test(navigator.platform));
    }
  }, []);

  return (
    <header className={TOPBAR_HEADER_CLASS}>
      <button
        onClick={onOpenMobileSidebar}
        aria-label="Otwórz menu"
        className="md:hidden h-10 w-10 -ml-1 shrink-0 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      >
        <Menu className="h-4 w-4" />
      </button>

      <div className={TOPBAR_BREADCRUMB_CLASS}>
        <BreadcrumbV2 />
      </div>

      <button
        onClick={onOpenCommandPalette}
        aria-label="Otwórz wyszukiwanie"
        className={TOPBAR_SEARCH_CLASS}
      >
        <Search className="h-4 w-4 shrink-0" />
        <span className="truncate">
          {searchesWork ? "Szukaj kandydatów, rekrutacji, klientów…" : "Przejdź do ekranu…"}
        </span>
        <div className="ml-auto hidden sm:flex items-center gap-1 shrink-0">
          <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
          <Kbd>K</Kbd>
        </div>
      </button>

      <div className={TOPBAR_ACTIONS_CLASS}>
        {/* P0 — ultrapilne rekrutacje (27.10.2026): u każdego, przed resztą. */}
        <P0TopbarButton />
        {/* Liga Mistrzów: miejsce i punkty kwartału — nie ściska się, cele oddają segmenty. */}
        <MyLeagueWidget className="hidden md:block" />
        <MyKpiWidget variant="compact" className="hidden md:block" />
        {/* Motyw, tryb gry i tryb ciemny w jednym menu; na telefonie osobno w szufladzie nawigacji. */}
        <div className="hidden sm:flex items-center">
          <AppearanceMenu />
        </div>
        {/* Bez dzwonka (16.10.2026): każda ikona ma jeden temat —
            `docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md`. */}
        <MyPeopleTopbarButton />
        {/* Stan, nie zdarzenia: moje CV; u DL pigułka kolejki „Do wysłania”. */}
        <CvNotificationsDropdown />
        <JobsNotificationsDropdown />
        <ContractsNotificationsDropdown />
        <ChatNotificationsDropdown />
        <InterviewNotificationsDropdown />
        {/* Zgody na wydatki i premie do decyzji (0483); przy zerze jej nie ma. */}
        <ConsentsTopbarButton />
        {/* „Ludzie w NEXUSIE”: nieobecni dziś (moduł urlopów); przy zerze go nie ma. */}
        <AbsentTodayButton />
        <QuickActionsV2
          externalModal={pendingModal}
          onExternalModalClear={onClearPendingModal}
        />
      </div>
    </header>
  );
}

export { CommandPaletteV2 };
export const _TopbarButton = Button;
