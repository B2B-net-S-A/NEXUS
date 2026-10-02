"use client";

import { usePathname } from "next/navigation";
import { CandidateTabsRail } from "@/components/v2/candidates/CandidateTabsRail";
import {
  LIST_RAIL_GAP_CLASS,
  OPEN_TABS_RAIL_CLASS,
  OpenTabsRailFrame,
} from "@/components/v2/shell/OpenTabsRail";

/**
 * Sekcja `/candidates` z szyną ostatnio otwieranych kandydatów po lewej
 * stronie listy i profilu — odpowiednik szyny „Rekrutacje” z
 * `app/jobs/layout.tsx`.
 *
 * Szyna stoi na liście (`/candidates`) i w profilu (`/candidates/<id>`).
 * Narzędzia pomocnicze (wyszukiwarka, porównanie, import) renderują się bez
 * niej. Sama znika, gdy nie ma otwartych kart, i poniżej 1024 px.
 */
export default function CandidatesLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const showRail =
    pathname === "/candidates" || /^\/candidates\/\d+/.test(pathname ?? "");

  if (!showRail) return <>{children}</>;

  return (
    // Do 02.10.2026 szyna była dopiero od 1536 px: rozwinięta (240 px) na
    // 1024–1535 px zabierała liście i profilowi połowę szerokości. Na laptopie
    // jest teraz zakładką w marginesie strony (zero szerokości w układzie),
    // a lista kandydatów wysuwa się nad treść.
    <OpenTabsRailFrame
      className={LIST_RAIL_GAP_CLASS}
      rail={<CandidateTabsRail className={OPEN_TABS_RAIL_CLASS} />}
    >
      {children}
    </OpenTabsRailFrame>
  );
}
