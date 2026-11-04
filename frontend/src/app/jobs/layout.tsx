"use client";

import { usePathname } from "next/navigation";
import { JOBS_LIST_RAIL_GAP_CLASS, JobTabsRail } from "@/components/v2/jobs/JobTabsRail";
import {
  OPEN_TABS_RAIL_CLASS,
  OpenTabsRailFrame,
} from "@/components/v2/shell/OpenTabsRail";

/**
 * Sekcja `/jobs` z szyną „Otwarte karty” (ostatnio otwarte rekrutacje, jak
 * w Traffit) po lewej stronie. Szyna stoi na stronach rekrutacji
 * (`/jobs/<id>…`) i — od 02.10.2026 — na liście `/jobs`: z listy wraca się do
 * rekrutacji, nad którymi się pracuje, bez szukania ich w tabeli. Formularz
 * nowej rekrutacji i „Porządek w requestach” renderują się bez szyny.
 *
 * Szyna sama znika, gdy nie ma otwartych kart, i poniżej 1024 px.
 */
export default function JobsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const isDetail = /^\/jobs\/\d+/.test(pathname);
  const isList = pathname === "/jobs";

  if (!isDetail && !isList) return <>{children}</>;

  return (
    <OpenTabsRailFrame
      // Lista na laptopie nie ma odstępu: szyna jest tam zakładką w marginesie
      // i nie zabiera tabeli szerokości. Strona rekrutacji — bez zmian.
      className={isList ? JOBS_LIST_RAIL_GAP_CLASS : "gap-4 lg:gap-6"}
      rail={
        <JobTabsRail
          variant={isList ? "list" : "detail"}
          className={OPEN_TABS_RAIL_CLASS}
        />
      }
    >
      {children}
    </OpenTabsRailFrame>
  );
}
