"use client";

import { useCallback, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Database, FileText, Search } from "lucide-react";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { CandidatesListV2 } from "@/components/v2/pages/CandidatesListV2";
import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";
import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";
import {
  CANDIDATES_MODE_PARAM,
  candidatesModeHref,
  parseCandidatesMode,
  type CandidatesMode,
} from "@/lib/candidates-mode";

/**
 * Jeden ekran „Kandydaci" (decyzja właściciela 21.09.2026): dawne trzy wejścia
 * do tej samej bazy — lista, Wyszukiwarka i Talent Radar — są TRYBAMI tego
 * ekranu, różnią się tylko punktem startu (filtry, słowa, treść requestu).
 * Stare adresy `/candidates/search` i `/talent-radar` przekierowują tutaj
 * (linki zapisane w powiadomieniach dalej działają).
 *
 * Tryb czyta się z WARTOŚCI parametru przy każdym renderze, więc miękka
 * nawigacja (klik w powiadomienie przy otwartym ekranie) przełącza widok.
 */
const MODE_TABS = [
  { value: "list", label: "Baza", icon: Database },
  { value: "search", label: "Wyszukiwanie", icon: Search },
  { value: "request", label: "Z treści requestu", icon: FileText },
] satisfies { value: CandidatesMode; label: string; icon: typeof Search }[];

const MODE_HINT: Record<CandidatesMode, string> = {
  list: "Cała baza kandydatów z filtrami.",
  search:
    "Wpisz nazwisko, umiejętności albo opis — rozpoznamy, o co chodzi. Filtry obok zawężają wynik.",
  request:
    "Wklej treść requestu albo wgraj profil Championa — ranking całej bazy, bez zakładania rekrutacji.",
};

// Stały obiekt: wyszukiwarka dopisuje go do adresu przy każdej zmianie filtra,
// więc nowa referencja co render niepotrzebnie odpalałaby jej efekt.
const SEARCH_URL_PARAMS = { [CANDIDATES_MODE_PARAM]: "search" };

export function CandidatesWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = parseCandidatesMode(searchParams?.get(CANDIDATES_MODE_PARAM));
  // Tekst przeniesiony z wyszukiwarki do trybu requestu — w stanie, nie
  // w adresie: to bywa pełna treść requestu klienta (długa, poufna).
  const [requestSeed, setRequestSeed] = useState<{ text: string; key: number } | null>(
    null,
  );

  const changeMode = useCallback(
    (next: string) => {
      const parsed = parseCandidatesMode(next);
      if (parsed === mode) return;
      router.push(candidatesModeHref(parsed));
    },
    [mode, router],
  );

  const useAsRequest = useCallback(
    (text: string) => {
      setRequestSeed({ text, key: Date.now() });
      router.push(candidatesModeHref("request"));
    },
    [router],
  );

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <h1 className="text-lg font-semibold tracking-tight text-foreground/80">Kandydaci</h1>
        <TabbedNav
          tabs={MODE_TABS}
          value={mode}
          onValueChange={changeMode}
          ariaLabel="Tryb ekranu Kandydaci"
          listClassName="w-auto"
        />
        <p className="text-xs text-muted-foreground" data-testid="candidates-mode-hint">
          {MODE_HINT[mode]}
        </p>
      </div>

      {mode === "list" && <CandidatesListV2 hideTitle />}
      {mode === "search" && (
        <CandidateSearchView
          syncUrl
          hideHeader
          persistUrlParams={SEARCH_URL_PARAMS}
          onUseAsRequest={useAsRequest}
        />
      )}
      {mode === "request" && (
        <TalentRadarWorkspace
          key={requestSeed?.key ?? "radar"}
          embedded
          initialText={requestSeed?.text}
        />
      )}
    </div>
  );
}
