"use client";

/**
 * „Moi ludzie” w pasku źródeł rekrutacji (07.11.2026, makieta
 * https://claude.ai/artifact/SM5Q8dK2temXWcc6GxUCZf, rekomendacja 1).
 *
 * Lista „Moi ludzie” dla rekrutacji była dotąd tylko w panelu z paska
 * górnego i w czacie Jarvisa: 20 z 146 pytań do Jarvisa brzmiało „Kogo
 * z moich ludzi warto przepiąć na rekrutację #…”. Kafel otwiera ten sam
 * panel, który na stronie rekrutacji sam staje na zakładce tej rekrutacji.
 *
 * Bez liczby: `for-job` liczy dopasowanie na żądanie (ok. 3 s), więc pasek
 * jej nie pyta przy każdym wejściu na Tablicę.
 */

import { Users } from "lucide-react";

import { useCapability } from "@/hooks/useCapability";
import { useMyPeoplePanel } from "@/store/my-people";

export const MY_PEOPLE_TILE_DESCRIPTION = "Twoi ludzie pasujący do tej rekrutacji, ze stawką i budżetem";

export function MyPeopleTileView({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid="source-tile-my-people"
      data-tour="jobs.sources.my-people"
      title={MY_PEOPLE_TILE_DESCRIPTION}
      className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/25 bg-card px-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
    >
      <Users className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      Moi ludzie
      <span className="sr-only">— {MY_PEOPLE_TILE_DESCRIPTION}</span>
    </button>
  );
}

export function MyPeopleTile() {
  const allowed = useCapability("nav.my_people");
  const openPanel = useMyPeoplePanel((s) => s.openPanel);
  if (!allowed) return null;
  return <MyPeopleTileView onOpen={openPanel} />;
}
